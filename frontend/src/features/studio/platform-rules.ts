/**
 * Client-side platform rules for live counters and previews (doc 26). The adapter's validate_content() on the server
 * stays authoritative; these numbers only drive the editor's budgets and warnings.
 */
import type { Platform } from "@/lib/platforms";
import type { ContentFormat } from "@/features/common/types";

export type CountMode = "chars" | "x_weighted" | "utf8_bytes" | "threads";

export interface FieldLimit { key: string; label: string; limit: number; mode: CountMode }
export interface PlatformRule {
  platform: Platform;
  textLimit: number;
  textLabel: string;
  mode: CountMode;
  perSegment?: boolean;
  hashtagCap?: number;
  hashtagRecommended?: number;
  maxMedia?: number;
  mediaRequired?: boolean;
  extraFields?: FieldLimit[];
  formats: ContentFormat[];
  foldAt?: number;
  aspect?: string;
  notes: string[];
}

export const PLATFORM_RULES: Record<Platform, PlatformRule> = {
  x: { platform: "x", textLimit: 280, textLabel: "Post", mode: "x_weighted", perSegment: true, hashtagRecommended: 2, maxMedia: 4, formats: ["text", "image", "carousel", "video", "poll", "link"], aspect: "16 / 9",
       notes: ["280 weighted chars per post (URLs count 23, CJK/emoji 2)", "≤ 4 media per post", "Threads split into segments"] },
  linkedin: { platform: "linkedin", textLimit: 3000, textLabel: "Commentary", mode: "chars", hashtagRecommended: 5, maxMedia: 20, foldAt: 210, formats: ["text", "image", "carousel", "video", "document", "article", "poll", "link"], aspect: "1.91 / 1",
       notes: ["3,000 characters", "Feed folds at ~210 characters (…see more)", "≤ 5 hashtags recommended", "Multi-image 2–20, document PDF ≤ 300 pages"] },
  instagram: { platform: "instagram", textLimit: 2200, textLabel: "Caption", mode: "chars", hashtagCap: 30, maxMedia: 10, mediaRequired: true, foldAt: 125, formats: ["image", "carousel", "short_video", "video", "story"], aspect: "4 / 5",
       notes: ["2,200 characters", "≤ 30 hashtags", "Media required (JPEG, 4:5–1.91:1)", "Carousel ≤ 10 items"] },
  threads: { platform: "threads", textLimit: 500, textLabel: "Post", mode: "threads", perSegment: true, hashtagRecommended: 1, maxMedia: 20, formats: ["text", "image", "carousel", "video", "poll"], aspect: "4 / 5",
       notes: ["500 characters (emoji count as UTF-8 bytes)", "≤ 5 links", "Carousel 2–20"] },
  facebook: { platform: "facebook", textLimit: 63206, textLabel: "Post", mode: "chars", hashtagRecommended: 3, maxMedia: 10, foldAt: 480, formats: ["text", "image", "carousel", "video", "short_video", "story", "link"], aspect: "1.91 / 1",
       notes: ["63,206 characters", "Stories cannot be scheduled via API"] },
  tiktok: { platform: "tiktok", textLimit: 2200, textLabel: "Caption", mode: "chars", maxMedia: 35, mediaRequired: true, formats: ["short_video", "video", "carousel"], aspect: "9 / 16",
       notes: ["2,200 characters", "Video or photo required — no text-only posts", "No delete via API"] },
  youtube: { platform: "youtube", textLimit: 5000, textLabel: "Description", mode: "utf8_bytes", hashtagCap: 15, maxMedia: 1, mediaRequired: true, formats: ["video", "short_video"], aspect: "16 / 9",
       extraFields: [{ key: "title", label: "Title", limit: 100, mode: "chars" }],
       notes: ["Title ≤ 100 characters", "Description ≤ 5,000 bytes", "Tags ≤ 500 characters", "> 15 hashtags are ignored"] },
  pinterest: { platform: "pinterest", textLimit: 800, textLabel: "Description", mode: "chars", hashtagRecommended: 20, maxMedia: 5, mediaRequired: true, formats: ["image", "carousel", "video"], aspect: "2 / 3",
       extraFields: [{ key: "title", label: "Title", limit: 100, mode: "chars" }],
       notes: ["Title ≤ 100 characters", "Description ≤ 800 characters", "Media required (2:3 recommended)"] },
  gbp: { platform: "gbp", textLimit: 1500, textLabel: "Summary", mode: "chars", maxMedia: 1, formats: ["text", "image"], aspect: "4 / 3",
       notes: ["~1,500 characters", "STANDARD / EVENT / OFFER posts", "No per-post insights"] },
};

export function ruleFor(platform: string): PlatformRule | undefined {
  return PLATFORM_RULES[platform as Platform];
}

const URL_RE = /https?:\/\/[^\s]+|www\.[^\s]+/gi;

/** twitter-text style weighting: URLs = 23, code points outside the light ranges weigh 2. */
function xWeighted(text: string): number {
  let total = 0;
  const withoutUrls = text.replace(URL_RE, () => { total += 23; return ""; });
  for (const ch of withoutUrls) {
    const cp = ch.codePointAt(0) ?? 0;
    const light = (cp >= 0 && cp <= 4351) || (cp >= 8192 && cp <= 8205) || (cp >= 8208 && cp <= 8223) || (cp >= 8242 && cp <= 8247);
    total += light ? 1 : 2;
  }
  return total;
}

function utf8Bytes(text: string): number {
  return new TextEncoder().encode(text).length;
}

export function countText(text: string, mode: CountMode): number {
  switch (mode) {
    case "x_weighted": return xWeighted(text);
    case "utf8_bytes": return utf8Bytes(text);
    case "threads": {
      let n = 0;
      for (const ch of text) { const cp = ch.codePointAt(0) ?? 0; n += cp > 0xffff ? utf8Bytes(ch) : 1; }
      return n;
    }
    default: return Array.from(text).length;
  }
}

export function extractHashtags(text: string): string[] {
  return Array.from(text.matchAll(/(^|\s)#([\p{L}\p{N}_]+)/gu)).map((m) => `#${m[2]}`);
}

export function normalizeTag(t: string): string {
  const clean = t.trim().replace(/^#+/, "").replace(/[^\p{L}\p{N}_]/gu, "");
  return clean ? `#${clean}` : "";
}

/** Compose the publishable text for a platform from master parts. */
export function composeMaster(body: { hook?: string; body_md?: string; cta?: string; hashtags?: string[] }): string {
  const plain = stripMarkdown(body.body_md ?? "");
  const tags = (body.hashtags ?? []).map(normalizeTag).filter(Boolean).join(" ");
  return [body.hook?.trim(), plain.trim(), body.cta?.trim(), tags].filter(Boolean).join("\n\n");
}

export function composeVariant(text: string, hashtags: string[] | undefined): string {
  const inline = new Set(extractHashtags(text).map((t) => t.toLowerCase()));
  const extra = (hashtags ?? []).map(normalizeTag).filter((t) => t && !inline.has(t.toLowerCase()));
  return extra.length ? `${text.trimEnd()}\n\n${extra.join(" ")}` : text;
}

export function stripMarkdown(md: string): string {
  return md
    .replace(/^#{1,6}\s+/gm, "")
    .replace(/\*\*(.+?)\*\*/g, "$1")
    .replace(/(^|[^*])\*(?!\s)(.+?)\*/g, "$1$2")
    .replace(/`([^`]+)`/g, "$1")
    .replace(/\[([^\]]+)\]\(([^)]+)\)/g, "$1 $2")
    .replace(/^\s*[-*]\s+/gm, "• ")
    .replace(/\n{3,}/g, "\n\n");
}

export interface BudgetLine { key: string; label: string; used: number; limit: number; over: boolean; mode: CountMode; segmentIndex?: number }

/** Per-platform budget lines for a text (+ segments for thread formats, + extra fields like titles). */
export function budgetFor(platform: string, text: string, opts: { segments?: string[]; metadata?: Record<string, unknown>; hashtags?: string[] } = {}): BudgetLine[] {
  const rule = ruleFor(platform);
  if (!rule) return [];
  const lines: BudgetLine[] = [];
  const segs = rule.perSegment && opts.segments && opts.segments.length > 0 ? opts.segments : null;
  if (segs) {
    segs.forEach((s, i) => {
      const used = countText(s, rule.mode);
      lines.push({ key: `seg-${i}`, label: `${rule.textLabel} ${i + 1}/${segs.length}`, used, limit: rule.textLimit, over: used > rule.textLimit, mode: rule.mode, segmentIndex: i });
    });
  } else {
    const used = countText(text, rule.mode);
    lines.push({ key: "text", label: rule.textLabel, used, limit: rule.textLimit, over: used > rule.textLimit, mode: rule.mode });
  }
  for (const f of rule.extraFields ?? []) {
    const v = typeof opts.metadata?.[f.key] === "string" ? (opts.metadata[f.key] as string) : "";
    const used = countText(v, f.mode);
    lines.push({ key: f.key, label: f.label, used, limit: f.limit, over: used > f.limit, mode: f.mode });
  }
  const tagCount = new Set([...(opts.hashtags ?? []).map((t) => normalizeTag(t).toLowerCase()), ...extractHashtags(text).map((t) => t.toLowerCase())].filter(Boolean)).size;
  if (rule.hashtagCap) lines.push({ key: "hashtags", label: "Hashtags", used: tagCount, limit: rule.hashtagCap, over: tagCount > rule.hashtagCap, mode: "chars" });
  else if (rule.hashtagRecommended) lines.push({ key: "hashtags", label: "Hashtags (recommended)", used: tagCount, limit: rule.hashtagRecommended, over: false, mode: "chars" });
  return lines;
}

/** Split long text into X/Threads-sized segments on sentence boundaries. */
export function splitIntoSegments(text: string, platform: string): string[] {
  const rule = ruleFor(platform);
  if (!rule) return [text];
  const limit = rule.textLimit - 6;
  const sentences = text.replace(/\n+/g, " \n").split(/(?<=[.!?])\s+/);
  const out: string[] = [];
  let cur = "";
  for (const s of sentences) {
    const next = cur ? `${cur} ${s}` : s;
    if (countText(next, rule.mode) <= limit) cur = next;
    else {
      if (cur) out.push(cur.trim());
      cur = s;
      while (countText(cur, rule.mode) > limit) { out.push(cur.slice(0, limit)); cur = cur.slice(limit); }
    }
  }
  if (cur.trim()) out.push(cur.trim());
  return out.length > 1 ? out.map((s, i) => `${s} ${i + 1}/${out.length}`) : out;
}

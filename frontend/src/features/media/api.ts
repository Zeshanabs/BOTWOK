/** Media Library API (doc 00 §14 MEDIA, doc 10). */
import { api, qs } from "@/lib/api";
import type { ListResponse } from "@/features/common/types";
import type { RunAccepted } from "@/features/studio/api";

export interface MediaUsage { content_item_id: string; title?: string | null; platform?: string | null; variant_id?: string | null; role?: string | null }
export interface MediaAsset {
  id: string;
  brand_id?: string | null;
  kind: "image" | "video" | "audio" | "document" | string;
  source: "upload" | "uploaded" | "generated" | "derived" | "import" | "url" | string;
  mime: string;
  bytes: number;
  filename?: string | null;
  width?: number | null;
  height?: number | null;
  duration_ms?: number | null;
  alt_text?: string | null;
  alt_text_source?: string | null;
  caption?: string | null;
  labels?: string[];
  ai_generated?: boolean;
  provider?: string | null;
  model?: string | null;
  prompt?: string | null;
  seed?: number | null;
  generation_params?: Record<string, unknown> | null;
  derived_from_id?: string | null;
  transform?: Record<string, unknown> | null;
  platform_target?: string | null;
  status?: "ready" | "processing" | "failed" | string;
  object_key?: string | null;
  derived_from_id_label?: string | null;
  error?: string | null;
  url?: string | null;
  thumbnail_url?: string | null;
  usage?: MediaUsage[];
  usage_count?: number | null;
  derived?: MediaAsset[];
  cost_usd?: number | null;
  ai_run_id?: string | null;
  created_at?: string;
}
export interface MediaFilters { kind?: string; source?: string; brand_id?: string | null; q?: string; cursor?: string; derived_from_id?: string; platform?: string }
/** POST /media/upload-url → {upload_url, key, bucket, method: "PUT", headers, expires_in}. */
export interface UploadTicket { upload_url: string; key?: string; object_key?: string; method?: "PUT" | "POST"; headers?: Record<string, string>; fields?: Record<string, string>; bucket?: string; expires_in?: number }
/** 201 {items} when generated synchronously; 202 {status:"queued", job_id} when backgrounded; RunAccepted if routed through an AI run. */
export type GenerateResult = RunAccepted | MediaAsset | { items: MediaAsset[] } | MediaAsset[] | { status: "queued"; job_id?: number | null; detail?: string | null };
export interface GenerateBody { prompt: string; brand_id: string | null; provider?: string; size: string; n?: number; negative_prompt?: string; style?: string; alt_text?: string; reference_asset_ids?: string[] }

export const mediaApi = {
  list: (f: MediaFilters) => api.get<ListResponse<MediaAsset>>(`/media${qs({ ...f })}`),
  get: (id: string) => api.get<MediaAsset>(`/media/${id}`),
  url: (id: string) => api.get<{ url: string; expires_in?: number | null; public?: boolean; thumbnail_url?: string }>(`/media/${id}/url`),
  uploadUrl: (b: { filename: string; content_type: string; size_bytes?: number }) => api.post<UploadTicket>("/media/upload-url", b),
  /** Register an uploaded object; the server probes mime/size/dimensions/hash. */
  create: (b: { key: string; filename: string; brand_id?: string | null; alt_text?: string; caption?: string }) => api.post<MediaAsset>("/media", b),
  generate: (b: GenerateBody) => api.post<GenerateResult>("/media/generate", b),
  /** format is a content format (image, story, short_video…); aspect overrides the platform default (e.g. "4:5"). */
  transform: (id: string, b: { platform: string; format: string; aspect?: string }) => api.post<MediaAsset | { status: "queued"; job_id?: number | null }>(`/media/${id}/transform`, b),
  removeBackground: (id: string) => api.post<MediaAsset>(`/media/${id}/remove-background`),
  patch: (id: string, b: { alt_text?: string | null; caption?: string | null; labels?: string[] }) => api.patch<MediaAsset>(`/media/${id}`, b),
  remove: (id: string) => api.delete<void>(`/media/${id}`),
};

export function kindFromMime(mime: string): string {
  if (mime.startsWith("image/")) return "image";
  if (mime.startsWith("video/")) return "video";
  if (mime.startsWith("audio/")) return "audio";
  return "document";
}

export function fmtBytes(n: number | null | undefined): string {
  if (n == null) return "—";
  if (n < 1024) return `${n} B`;
  if (n < 1024 ** 2) return `${(n / 1024).toFixed(0)} KB`;
  if (n < 1024 ** 3) return `${(n / 1024 ** 2).toFixed(1)} MB`;
  return `${(n / 1024 ** 3).toFixed(2)} GB`;
}

export function aspectLabel(w?: number | null, h?: number | null): string | null {
  if (!w || !h) return null;
  const r = w / h;
  const known: [number, string][] = [[1, "1:1"], [0.8, "4:5"], [0.5625, "9:16"], [1.7778, "16:9"], [1.91, "1.91:1"], [0.6667, "2:3"], [1.3333, "4:3"]];
  const hit = known.find(([k]) => Math.abs(k - r) < 0.02);
  return hit ? hit[1] : r.toFixed(2);
}

/** Pull media assets / ids out of a generate response or a finished run's deliverables. */
export function extractAssets(v: unknown): { assets: MediaAsset[]; ids: string[] } {
  const assets: MediaAsset[] = [];
  const ids = new Set<string>();
  const visit = (x: unknown, keyHint = "", depth = 0) => {
    if (depth > 4 || x == null) return;
    if (Array.isArray(x)) { x.forEach((y) => visit(y, keyHint, depth + 1)); return; }
    if (typeof x === "string") { if (/media|asset|image/i.test(keyHint) && /^[0-9a-f-]{32,36}$/i.test(x)) ids.add(x); return; }
    if (typeof x === "object") {
      const o = x as Record<string, unknown>;
      if (typeof o.id === "string" && typeof o.mime === "string") { assets.push(o as unknown as MediaAsset); return; }
      for (const [k, val] of Object.entries(o)) visit(val, k, depth + 1);
    }
  };
  visit(v);
  assets.forEach((a) => ids.delete(a.id));
  return { assets, ids: Array.from(ids) };
}

export const SIZE_PRESETS: { id: string; label: string; size: string; platforms: string }[] = [
  { id: "square", label: "Square 1:1", size: "1024x1024", platforms: "ig, fb, li, x" },
  { id: "portrait", label: "Portrait 4:5", size: "1080x1350", platforms: "ig feed" },
  { id: "story", label: "Vertical 9:16", size: "1080x1920", platforms: "stories, reels, tt" },
  { id: "landscape", label: "Landscape 16:9", size: "1920x1080", platforms: "yt, x" },
  { id: "link", label: "Link 1.91:1", size: "1200x628", platforms: "li, fb" },
  { id: "pin", label: "Pin 2:3", size: "1000x1500", platforms: "pinterest" },
];

export const TRANSFORM_PRESETS: { platform: string; format: string; aspect?: string; label: string }[] = [
  { platform: "instagram", format: "image", aspect: "4:5", label: "Instagram feed 4:5 (1080×1350)" },
  { platform: "instagram", format: "story", aspect: "9:16", label: "Instagram story/reel 9:16" },
  { platform: "linkedin", format: "image", aspect: "1.91:1", label: "LinkedIn link 1.91:1 (1200×627)" },
  { platform: "pinterest", format: "image", aspect: "2:3", label: "Pinterest 2:3 (1000×1500)" },
  { platform: "youtube", format: "image", aspect: "16:9", label: "YouTube 16:9 (1920×1080)" },
  { platform: "x", format: "image", aspect: "16:9", label: "X 16:9" },
  { platform: "tiktok", format: "image", aspect: "9:16", label: "TikTok 9:16" },
];

/** Display name: filename if the API sends one, else the object key's basename. */
export function assetName(a: { filename?: string | null; object_key?: string | null; kind?: string; id: string }): string {
  return a.filename ?? a.object_key?.split("/").pop() ?? `${a.kind ?? "asset"} ${a.id.slice(0, 6)}`;
}

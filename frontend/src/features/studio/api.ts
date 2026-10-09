/** Content Studio API (doc 00 §14 CONTENT, doc 17 §17.2, doc 09 §9.3). */
import { api, qs } from "@/lib/api";
import type { Platform } from "@/lib/platforms";
import type { ContentFormat, ContentStatus, GenerationMetadata, ListResponse, Validation } from "@/features/common/types";

export interface MediaRef {
  id: string;
  kind?: string;
  mime?: string;
  width?: number | null;
  height?: number | null;
  url?: string | null;
  thumbnail_url?: string | null;
  alt_text?: string | null;
  ai_generated?: boolean;
  duration_ms?: number | null;
}
export interface ContentAsset {
  id?: string;
  media_asset_id: string;
  variant_id?: string | null;
  role: "primary" | "carousel_slide" | "thumbnail" | "cover" | string;
  position: number;
  alt_text?: string | null;
  media?: MediaRef | null;
}
/** Critic agent output (backend agents/schemas/critic.py): scores 0–1, issues {severity, kind, span, suggestion}, string suggestions/flags. */
export interface CritiqueIssue { severity?: "low" | "medium" | "high" | "blocker" | "error" | "warning" | "info" | string; kind?: string; span?: string | null; suggestion?: string | null; message?: string; field?: string | null; code?: string }
export interface CritiqueSuggestion { text?: string; message?: string; rationale?: string; replacement?: string | null; field?: string | null }
export interface PolicyFlag { code?: string; message: string; severity?: string }
export interface Critique {
  overall?: number | null;
  scores?: Record<string, number | null>;
  issues?: CritiqueIssue[];
  suggestions?: (string | CritiqueSuggestion)[];
  rewrite_suggestions?: (string | CritiqueSuggestion)[];
  policy_flags?: (string | PolicyFlag)[];
  recommend?: "approve" | "revise" | "reject" | string;
  risk_level?: string | null;
  model?: string | null;
  agent?: string | null;
  same_model?: boolean;
  run_id?: string | null;
  cost_usd?: number | null;
  created_at?: string | null;
}
export type Verdict = "supported" | "contradicted" | "unverifiable" | "unverified" | "opinion" | string;
export interface ClaimVerdict {
  claim?: string;
  text?: string;
  verdict: Verdict;
  evidence?: string | { source_id?: string; quote?: string | null }[] | null;
  source_ids?: string[];
  sources?: { id?: string; title?: string | null; url?: string | null; domain?: string | null }[];
  confidence?: number | null;
  regulated_domain?: string | null;
}
export interface FactCheck { claims?: ClaimVerdict[]; overall_risk?: string | null; requires_human?: boolean; model?: string | null; run_id?: string | null; checked_at?: string | null; cost_usd?: number | null }

export function policyFlags(c: Critique | null | undefined): PolicyFlag[] {
  return (c?.policy_flags ?? []).map((f) => (typeof f === "string" ? { code: f, message: f.replace(/[_.]/g, " ") } : f)).filter((f) => !!f.message);
}
export function critiqueSuggestions(c: Critique | null | undefined): CritiqueSuggestion[] {
  return [...(c?.suggestions ?? []), ...(c?.rewrite_suggestions ?? [])].map((x) => (typeof x === "string" ? { text: x } : x));
}
export function issueText(i: CritiqueIssue): string {
  return i.message ?? [i.kind?.replace(/_/g, " "), i.span ? `“${i.span}”` : null].filter(Boolean).join(": ");
}
/** Claims that still need attention (opinions don't). */
export const isUnsupported = (c: ClaimVerdict) => c.verdict !== "supported" && c.verdict !== "opinion";

export interface ContentSourceRef {
  source_id: string;
  claim_text?: string | null;
  used_for?: "claim" | "inspiration" | "data" | string;
  title?: string | null;
  url?: string | null;
  canonical_url?: string | null;
  domain?: string | null;
  citation?: string | null;
  credibility_score?: number | null;
  credibility?: number | null;
  published_at?: string | null;
  retrieved_at?: string | null;
  verdict?: Verdict | null;
  source?: {
    id?: string; title?: string | null; canonical_url?: string | null; domain?: string | null; citation?: string | null;
    credibility_score?: number | null; published_at?: string | null; retrieved_at?: string | null;
  } | null;
}

export interface ContentBody {
  hook?: string;
  body_md?: string;
  cta?: string;
  hashtags?: string[];
  keywords?: string[];
  visual_concept?: string;
  alt_text?: string;
  notes?: string;
}

export interface ScheduledPostRef { id: string; status: string; scheduled_at: string; social_account_id?: string; timezone?: string }

export interface ContentVariant {
  id: string;
  content_item_id: string;
  platform: Platform;
  format: ContentFormat;
  social_account_id?: string | null;
  text?: string | null;
  segments?: unknown[];
  hashtags?: string[];
  media_plan?: Record<string, unknown>;
  platform_metadata?: Record<string, unknown>;
  status: ContentStatus;
  validation?: Validation | null;
  critique?: Critique | null;
  factcheck?: FactCheck | null;
  changes_made?: string[];
  current_version?: number;
  ai_generated?: boolean;
  generation_metadata?: GenerationMetadata | null;
  assets?: ContentAsset[];
  scheduled_posts?: ScheduledPostRef[];
  updated_at?: string;
}

export interface ContentItem {
  id: string;
  brand_id: string;
  campaign_id?: string | null;
  pillar_id?: string | null;
  idea_id?: string | null;
  title: string;
  content_type?: string | null;
  master_format: ContentFormat;
  status: ContentStatus;
  body: ContentBody;
  language?: string;
  current_version: number;
  ai_generated?: boolean;
  generation_metadata?: GenerationMetadata | null;
  risk_level?: "low" | "medium" | "high";
  approval_required?: boolean;
  critique?: Critique | null;
  factcheck?: FactCheck | null;
  /** List items carry platforms + variant_count instead of variants. */
  platforms?: string[];
  variant_count?: number;
  variants?: ContentVariant[];
  sources?: ContentSourceRef[];
  assets?: ContentAsset[];
  pillar?: { id: string; name: string; color?: string | null } | null;
  campaign?: { id: string; name: string } | null;
  planned_at?: string | null;
  created_by?: string | { id: string; name?: string; full_name?: string };
  assigned_to?: string | null;
  created_at?: string;
  updated_at?: string;
}

export interface ContentVersion {
  id: string;
  target_type: "content_item" | "content_variant" | "item" | "variant" | string;
  target_id: string;
  version: number;
  snapshot: Record<string, unknown>;
  author_type: "user" | "agent" | string;
  author_id: string;
  author_name?: string | null;
  diff_summary?: string | null;
  created_at: string;
}

export interface ContentFilters { status?: string; pillar_id?: string; platform?: string; q?: string; brand_id?: string | null; campaign_id?: string; cursor?: string }

export interface GenerateBody { mode: "write" | "rewrite" | "shorten" | "expand" | "change_tone" | "regenerate" | "hashtags"; instructions?: string; platform?: string; format?: string; source_ids?: string[]; length?: string | number; variant_id?: string; confirm?: boolean }
export interface RunAccepted { run_id: string; run_ids?: string[]; status?: string; status_url?: string }

export const contentApi = {
  list: (f: ContentFilters) => api.get<ListResponse<ContentItem>>(`/content${qs({ ...f })}`),
  create: (body: { brand_id: string; title: string; master_format: ContentFormat; content_type?: string; pillar_id?: string; campaign_id?: string; idea_id?: string; body?: ContentBody & Record<string, unknown> }) =>
    api.post<ContentItem>("/content", body),
  get: (id: string) => api.get<ContentItem>(`/content/${id}`),
  patch: (id: string, body: Partial<Pick<ContentItem, "title" | "body" | "pillar_id" | "campaign_id" | "content_type" | "planned_at">> & { expected_version?: number; sources?: { source_id: string; used_for?: string; claim_text?: string | null }[] }) =>
    api.patch<ContentItem>(`/content/${id}`, body),
  remove: (id: string) => api.delete<void>(`/content/${id}`),
  createVariant: (id: string, body: { platform: string; format: string; text?: string; hashtags?: string[]; social_account_id?: string }) =>
    api.post<ContentVariant>(`/content/${id}/variants`, body),
  patchVariant: (id: string, vid: string, body: { text?: string; segments?: unknown[]; hashtags?: string[]; platform_metadata?: Record<string, unknown>; media_plan?: Record<string, unknown>; social_account_id?: string | null; expected_version?: number }) =>
    api.patch<ContentVariant>(`/content/${id}/variants/${vid}`, body),
  versions: (id: string) => api.get<ListResponse<ContentVersion>>(`/content/${id}/versions`),
  /** Variant versions restore with ?variant_id=. */
  restore: (id: string, v: number | string, variantId?: string | null) => api.post<ContentItem>(`/content/${id}/versions/${v}/restore${qs({ variant_id: variantId ?? undefined })}`),
  generate: (id: string, body: GenerateBody) => api.post<RunAccepted>(`/content/${id}/generate`, body),
  repurpose: (id: string, body: { targets: { platform: string; format: string; social_account_id?: string }[]; source?: "master" | string; keep_sources?: boolean; keep_cta?: boolean; keep_media?: boolean; tone?: string; confirm?: boolean }) =>
    api.post<RunAccepted>(`/content/${id}/repurpose`, body),
  critique: (id: string, body: { variant_id?: string }) => api.post<RunAccepted | ContentItem>(`/content/${id}/critique`, body),
  factCheck: (id: string, body: { variant_id?: string }) => api.post<RunAccepted | ContentItem>(`/content/${id}/fact-check`, body),
  transition: (id: string, body: { to: string; comment?: string }) => api.post<ContentItem>(`/content/${id}/transition`, body),
  requestApproval: (id: string, body: { comment?: string; expires_in_hours?: number }) => api.post<{ id: string; status: string }>(`/content/${id}/request-approval`, body),
  attachAsset: (id: string, body: { media_asset_id: string; variant_id?: string | null; role?: string; position?: number; alt_text?: string | null }) =>
    api.post<ContentAsset>(`/content/${id}/assets`, body),
  detachAsset: (id: string, assetId: string) => api.delete<void>(`/content/${id}/assets/${assetId}`),
};

export function isRunAccepted(v: unknown): v is RunAccepted {
  return typeof v === "object" && v !== null && "run_id" in v && typeof (v as RunAccepted).run_id === "string";
}

/** Normalize a source ref whether the API embeds `source` or flattens fields. */
export function sourceView(s: ContentSourceRef) {
  const inner = s.source ?? {};
  return {
    id: s.source_id,
    title: s.title ?? inner.title ?? null,
    url: s.url ?? s.canonical_url ?? inner.canonical_url ?? null,
    domain: s.domain ?? inner.domain ?? null,
    citation: s.citation ?? inner.citation ?? null,
    credibility: s.credibility ?? s.credibility_score ?? inner.credibility_score ?? null,
    publishedAt: s.published_at ?? inner.published_at ?? null,
    retrievedAt: s.retrieved_at ?? inner.retrieved_at ?? null,
    claim: s.claim_text ?? null,
    usedFor: s.used_for ?? "claim",
    verdict: s.verdict ?? null,
  };
}

/** Cross-feature API shapes (doc 17). Fields beyond the docs are optional so the UI tolerates partial backends. */
import type { Platform } from "@/lib/platforms";

export interface Paged<T> { items: T[]; next_cursor?: string | null; total?: number }
export type ListResponse<T> = Paged<T> | T[];

export type ContentStatus = "idea" | "draft" | "ai_generated" | "needs_review" | "approved" | "rejected" | "archived";
export type ScheduleStatus = "scheduled" | "queued" | "publishing" | "published" | "failed" | "cancelled" | "paused";
export type RunStatus = "queued" | "planning" | "running" | "awaiting_approval" | "paused" | "completed" | "failed" | "cancelled";
export type ContentFormat = "text" | "image" | "carousel" | "video" | "short_video" | "story" | "article" | "poll" | "document" | "link";

export const CONTENT_FORMATS: ContentFormat[] = ["text", "image", "carousel", "video", "short_video", "story", "article", "poll", "document", "link"];
export const CONTENT_STATUSES: ContentStatus[] = ["idea", "draft", "ai_generated", "needs_review", "approved", "rejected", "archived"];

export interface Brand { id: string; name: string; timezone?: string; slug?: string }
export interface Pillar { id: string; name: string; color?: string | null; share_target?: number | null }
export interface Campaign { id: string; name: string; color?: string | null; status?: string }

export interface SocialAccount {
  id: string;
  brand_id?: string;
  platform: Platform;
  display_name: string;
  handle?: string | null;
  avatar_url?: string | null;
  account_type?: string | null;
  status: "active" | "expired" | "revoked" | "error" | "disconnected";
  health?: {
    token_valid?: boolean;
    rate_limited_until?: string | null;
    expires_at?: string | null;
    last_error?: string | null;
    audit_pending?: boolean;
    limits_remaining?: Record<string, number>;
  } | null;
  last_probe_at?: string | null;
  token_expires_at?: string | null;
}

export interface RunTask {
  key: string;
  label: string;
  agent?: string;
  status: string;
  duration_ms?: number | null;
  cost_usd?: number | null;
  sources_count?: number | null;
  model?: string | null;
  error?: string | null;
}
export interface RunSource { id?: string; title?: string | null; url?: string | null; domain?: string | null; credibility?: number | null; relevance?: number | null }
export interface RunAction { approval_id?: string; description: string; status: string }
export interface AiRun {
  id: string;
  status: RunStatus | string;
  /** RunView returns a dict (router output); older shapes used a string. */
  intent?: string | Record<string, unknown> | null;
  message?: string | null;
  title?: string | null;
  agent?: string | null;
  mode?: string | null;
  plan?: { tasks: RunTask[] } | null;
  result?: {
    reasoning_summary?: string | null;
    deliverables?: unknown;
    sources?: RunSource[];
    actions?: RunAction[];
  } | null;
  cost_usd?: number | null;
  tokens?: number | Record<string, number> | null;
  reasoning_summary?: string | null;
  error?: string | null;
  created_at?: string;
  finished_at?: string | null;
}

export interface ValidationIssue { code?: string; message: string; field?: string | null; severity?: "error" | "warning" | "info" | string }
export interface Validation { ok?: boolean; issues?: ValidationIssue[]; errors?: ValidationIssue[]; warnings?: ValidationIssue[] }

export interface GenerationMetadata {
  model?: string | null;
  provider?: string | null;
  agent?: string | null;
  prompt_version?: string | null;
  temperature?: number | null;
  ai_call_id?: string | null;
  run_id?: string | null;
  cost_usd?: number | null;
  tier?: string | null;
}

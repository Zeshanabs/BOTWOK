/** Scheduling + publishing API (doc 00 §14, doc 12, doc 17 §17.2). */
import { api, qs } from "@/lib/api";
import type { Platform } from "@/lib/platforms";
import type { ListResponse, ScheduleStatus, Validation } from "@/features/common/types";

export interface AccountRef { id: string; platform: Platform; display_name: string; handle?: string | null; status?: string }
export type PersonRef = string | { id: string; name?: string | null; full_name?: string | null };
export const personName = (p: PersonRef | null | undefined): string | null => (p == null ? null : typeof p === "string" ? p : p.name ?? p.full_name ?? null);

export interface PublishAttempt {
  id: string;
  scheduled_post_id?: string;
  attempt_no: number;
  segments_done?: number;
  status: "running" | "succeeded" | "failed" | "ambiguous" | "reconciled" | string;
  error_category?: string | null;
  error_code?: string | null;
  error_message?: string | null;
  platform_response?: Record<string, unknown> | null;
  idempotency_key?: string | null;
  state?: Record<string, unknown> | null;
  started_at: string;
  finished_at?: string | null;
}

export interface ScheduledPost {
  id: string;
  content_variant_id: string;
  content_item_id?: string | null;
  social_account_id?: string | null;
  social_account?: AccountRef | null;
  platform?: Platform | null;
  title?: string | null;
  content?: { id: string; title: string } | null;
  variant?: { id: string; platform: Platform; format?: string; text?: string | null } | null;
  scheduled_at: string;
  timezone: string;
  status: ScheduleStatus;
  priority?: number;
  attempt_count?: number;
  max_attempts?: number;
  next_attempt_at?: string | null;
  last_error?: string | null;
  last_error_category?: string | null;
  pause_reason?: string | null;
  dead_letter?: boolean;
  attempts?: PublishAttempt[];
  last_attempt_id?: string | null;
  validation?: Validation | null;
  created_by?: PersonRef | null;
  approved_by?: PersonRef | null;
  created_at?: string;
  partially_published_segments?: number;
}

export interface PublishedPost {
  id: string;
  platform: Platform;
  external_id: string;
  external_url?: string | null;
  published_at: string;
  deleted_at?: string | null;
  title?: string | null;
  content_item_id?: string | null;
  social_account_id?: string;
  social_account?: AccountRef | null;
  scheduled_post_id?: string | null;
  approved_by?: PersonRef | null;
}

export interface BestTimeSlot { at: string; local?: string; weekday?: number; hour?: number; score?: number | null; basis?: string | null; n?: number | null; lift?: number | null }
export interface BestTimesResult { slots: BestTimeSlot[]; timezone?: string; evidence?: string; n_posts?: number; min_gap_minutes?: number; token_expires_at?: string | null }

export const schedulingApi = {
  create: (b: { content_variant_id: string; social_account_id: string; scheduled_at: string; timezone: string; priority?: number; first_comment?: string }) =>
    api.post<ScheduledPost>("/scheduling/posts", b),
  get: (id: string) => api.get<ScheduledPost>(`/scheduling/posts/${id}`),
  list: (f: { status?: string; from?: string; to?: string; content_variant_id?: string }) => api.get<ListResponse<ScheduledPost>>(`/scheduling/posts${qs(f)}`),
  patch: (id: string, b: { scheduled_at?: string; timezone?: string; priority?: number }) => api.patch<ScheduledPost>(`/scheduling/posts/${id}`, b),
  cancel: (id: string) => api.post<ScheduledPost>(`/scheduling/posts/${id}/cancel`),
  pause: (id: string) => api.post<ScheduledPost>(`/scheduling/posts/${id}/pause`),
  resume: (id: string) => api.post<ScheduledPost>(`/scheduling/posts/${id}/resume`),
  bestTimes: (b: { brand_id: string | null; platform: string; social_account_id?: string; from: string; to: string; count: number }) =>
    api.post<BestTimesResult>("/scheduling/best-times", b),
};

export const publishingApi = {
  publishNow: (b: { content_variant_id: string; social_account_id: string }) => api.post<{ scheduled_post_id: string }>("/publishing/publish-now", b),
  /** Queue rows carry no title; titles are joined client-side from the calendar for the same window. */
  queue: (f: { status?: string | string[]; brand_id?: string | null }) => api.get<ListResponse<ScheduledPost>>(`/publishing/queue${qs(f)}`),
  published: (f: { platform?: string; brand_id?: string | null; include_deleted?: boolean }) => api.get<ListResponse<PublishedPost>>(`/publishing/published${qs(f)}`),
  attempt: (id: string) => api.get<PublishAttempt>(`/publishing/attempts/${id}`),
  retry: (attemptId: string) => api.post<{ status?: string }>(`/publishing/attempts/${attemptId}/retry`),
  deletePublished: (id: string) => api.delete<{ deleted_at: string }>(`/publishing/published/${id}`),
};

/** POST /publishing/attempts/{attempt_id}/retry takes the last attempt id (falls back to the post id). */
export function retryTarget(p: ScheduledPost): string {
  const attempts = [...(p.attempts ?? [])].sort((a, b) => a.attempt_no - b.attempt_no);
  return p.last_attempt_id ?? attempts[attempts.length - 1]?.id ?? p.id;
}

export function isDeadLetter(p: ScheduledPost): boolean {
  if (p.dead_letter) return true;
  return p.status === "failed" && (p.attempt_count ?? 0) >= (p.max_attempts ?? 5);
}

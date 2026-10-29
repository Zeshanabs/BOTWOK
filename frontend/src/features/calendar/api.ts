/** Calendar aggregation (doc 12 §12.8, doc 24 §14). */
import { api, qs } from "@/lib/api";
import type { Platform } from "@/lib/platforms";
import type { ValidationIssue } from "@/features/common/types";
import { isRecord, str } from "@/features/common/utils";
import type { AccountRef } from "@/features/publishing/api";

export type CalendarView = "month" | "week" | "day" | "list" | "board";
export const VIEWS: CalendarView[] = ["month", "week", "day", "list", "board"];

export interface CalendarCard {
  id: string;
  kind?: "scheduled_post" | "content" | "variant" | string;
  scheduled_post_id?: string | null;
  content_item_id: string;
  content_variant_id?: string | null;
  title: string;
  platform?: Platform | null;
  format?: string | null;
  status: string;
  content_status?: string | null;
  schedule_status?: string | null;
  scheduled_at?: string | null;
  planned_at?: string | null;
  timezone?: string | null;
  thumbnail_url?: string | null;
  thumbnail_media_id?: string | null;
  social_account_id?: string | null;
  social_account?: AccountRef | null;
  ai_generated?: boolean;
  campaign?: { id: string; name: string; color?: string | null } | null;
  pillar?: { id: string; name: string; color?: string | null } | null;
  warnings?: ValidationIssue[];
  paused?: boolean;
  last_error?: string | null;
  published_url?: string | null;
  created_by_name?: string | null;
}
export interface LimitWarning extends ValidationIssue { date?: string | null; account?: string | null; social_account_id?: string | null; platform?: string | null; source?: string | null }
/** Backend (SchedulingService.calendar): {from, to, cards:[scheduled_post card], tray:[unscheduled approved variant]}; cards nest content_item/variant/account. */
export interface CalendarResponse { items?: unknown[]; cards?: unknown[]; tray?: unknown[]; warnings?: LimitWarning[]; timezone?: string; from?: string; to?: string }
export interface CalendarQuery { from: string; to: string; view: CalendarView; brand_id?: string | null; platform?: string; status?: string; campaign?: string; pillar?: string; tz?: string; tray?: boolean }

export const calendarApi = {
  get: (q: CalendarQuery) => api.get<CalendarResponse | unknown[]>(`/calendar${qs({ ...q })}`),
};

/** Map a raw calendar/tray card (nested or flat) to CalendarCard. */
export function normalizeCard(raw: unknown): CalendarCard | null {
  if (!isRecord(raw)) return null;
  const item = isRecord(raw.content_item) ? raw.content_item : {};
  const variant = isRecord(raw.variant) ? raw.variant : {};
  const account = isRecord(raw.social_account) ? raw.social_account : isRecord(raw.account) ? raw.account : null;
  const kind = str(raw.kind) ?? undefined;
  const isPost = kind === "scheduled_post" || !!raw.scheduled_post_id;
  const id = str(raw.id) ?? "";
  const validation = isRecord(raw.validation) ? raw.validation : null;
  const warnings = Array.isArray(raw.warnings) ? raw.warnings : validation && Array.isArray(validation.warnings) ? validation.warnings
    : validation && Array.isArray(validation.issues) ? validation.issues.filter((i) => isRecord(i) && i.severity === "warning") : [];
  return {
    id,
    kind,
    scheduled_post_id: str(raw.scheduled_post_id) ?? (kind === "scheduled_post" ? id : null),
    content_item_id: str(raw.content_item_id) ?? str(item.id) ?? "",
    content_variant_id: str(raw.content_variant_id) ?? str(variant.id) ?? (kind === "unscheduled" || kind === "variant" ? id : null),
    title: str(raw.title) ?? str(item.title) ?? str(variant.text_preview) ?? "Untitled",
    platform: (str(raw.platform) ?? str(account?.platform) ?? null) as Platform | null,
    format: str(raw.format) ?? str(variant.format),
    status: str(raw.status) ?? "draft",
    content_status: str(item.status) ?? str(raw.content_status),
    schedule_status: isPost ? str(raw.schedule_status) ?? str(raw.status) : null,
    scheduled_at: str(raw.scheduled_at),
    planned_at: str(raw.planned_at),
    timezone: str(raw.timezone),
    thumbnail_url: str(raw.thumbnail_url),
    thumbnail_media_id: str(raw.thumbnail_media_id),
    social_account_id: str(raw.social_account_id) ?? str(account?.id) ?? str(variant.social_account_id),
    social_account: account ? { id: str(account.id) ?? "", platform: (str(account.platform) ?? "x") as Platform, display_name: str(account.display_name) ?? "", handle: str(account.handle), status: str(account.status) ?? undefined } : null,
    ai_generated: raw.ai_generated === true || item.ai_generated === true,
    warnings: warnings.filter(isRecord).map((w) => ({ code: str(w.code) ?? undefined, message: str(w.message) ?? "", severity: str(w.severity) ?? undefined })),
    paused: str(raw.status) === "paused",
    last_error: str(raw.last_error),
    published_url: str(raw.published_url),
    created_by_name: isRecord(raw.created_by) ? str(raw.created_by.name) : null,
  };
}

export function normalizeCalendar(r: CalendarResponse | unknown[] | undefined): { cards: CalendarCard[]; tray: CalendarCard[] | null; warnings: LimitWarning[] } {
  const map = (list: unknown[] | undefined) => (list ?? []).map(normalizeCard).filter((c): c is CalendarCard => c != null);
  if (!r) return { cards: [], tray: null, warnings: [] };
  if (Array.isArray(r)) return { cards: map(r), tray: null, warnings: [] };
  return { cards: map(r.cards ?? r.items), tray: r.tray ? map(r.tray) : null, warnings: r.warnings ?? [] };
}

export const cardTime = (c: CalendarCard): string | null => c.scheduled_at ?? c.planned_at ?? null;
export const cardKey = (c: CalendarCard): string => c.scheduled_post_id ?? c.id;
export const scheduleStatusOf = (c: CalendarCard): string | null => c.schedule_status ?? (c.scheduled_post_id ? c.status : null);

/** Drag rules (doc 24 §14 table). */
export function dragMode(c: CalendarCard): "move" | "confirm" | "planned" | "locked" {
  const s = scheduleStatusOf(c);
  if (c.scheduled_post_id || s) {
    if (s === "scheduled" || s === "paused") return "move";
    if (s === "queued") return "confirm";
    return "locked";
  }
  return cardTime(c) ? "planned" : "locked";
}

/** Replace a card's time inside the cached raw response (flat or nested cards). */
export function patchCardTime(r: CalendarResponse | unknown[] | undefined, key: string, iso: string): CalendarResponse | unknown[] | undefined {
  const fix = (list: unknown[] | undefined) => list?.map((raw) => {
    const c = normalizeCard(raw);
    if (!c || cardKey(c) !== key || !isRecord(raw)) return raw;
    return c.scheduled_post_id || raw.scheduled_at ? { ...raw, scheduled_at: iso } : { ...raw, planned_at: iso };
  });
  if (!r) return r;
  if (Array.isArray(r)) return fix(r);
  return { ...r, cards: fix(r.cards), items: fix(r.items) };
}

export const BOARD_COLUMNS = ["idea", "draft", "ai_generated", "needs_review", "approved", "scheduled", "publishing", "published", "failed"];

export const STATUS_BORDER: Record<string, string> = {
  idea: "border-l-slate-400", draft: "border-l-gray-400", ai_generated: "border-l-violet-500", needs_review: "border-l-amber-500",
  approved: "border-l-emerald-500", scheduled: "border-l-sky-500", queued: "border-l-sky-500", paused: "border-l-zinc-400",
  publishing: "border-l-blue-500", published: "border-l-green-600", failed: "border-l-red-500", cancelled: "border-l-zinc-300", rejected: "border-l-zinc-300",
};

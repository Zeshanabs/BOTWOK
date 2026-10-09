/** Analytics + insights API (doc 13, doc 17 §17.2, flows N/O) with tolerant normalizers. */
import { api, qs } from "@/lib/api";
import type { ListResponse } from "@/features/common/types";
import { isRecord, num, str } from "@/features/common/utils";

export interface SeriesPoint { date: string; value: number | null; previous?: number | null }
export interface Kpi {
  key: string;
  label: string;
  value: number | null;
  previous: number | null;
  deltaPct: number | null;
  basis: string | null;
  coverage: string | null;
  series: SeriesPoint[];
  unit: "count" | "rate";
}
export interface OverviewRaw {
  period?: { from?: string; to?: string };
  compare?: { from?: string; to?: string } | null;
  previous_period?: { from?: string; to?: string } | null;
  metrics?: Record<string, unknown>;
  /** Backend: dict {metric: {value, coverage, basis, median, previous, delta_pct (fraction)}}; older/alt: array. */
  kpis?: unknown[] | Record<string, unknown>;
  accounts?: Record<string, unknown>[];
  last_synced_at?: string | null;
  platforms_included?: string[];
  platforms_excluded?: string[];
  [k: string]: unknown;
}
export interface BreakdownGroup { key: string; label?: string | null; n?: number | null; value: number | null; previous?: number | null; ci?: [number, number] | { low: number; high: number } | null; weekday?: number | null; hour?: number | null; availability?: string | null }
export interface BreakdownRaw { groups?: BreakdownGroup[]; items?: BreakdownGroup[]; coverage?: unknown; basis?: unknown; metric?: string; overall?: number | null }
export interface PostPerf {
  id?: string; published_post_id?: string; content_item_id?: string | null; title?: string | null; platform: string; published_at?: string | null; external_url?: string | null;
  impressions?: number | null; reach?: number | null; views?: number | null; engagements?: number | null; likes?: number | null; comments?: number | null; shares?: number | null;
  saves?: number | null; clicks?: number | null; engagement_rate?: number | null; availability?: Record<string, string>; why?: string | null; pillar?: string | null; format?: string | null;
}
export interface AccountPerf {
  id?: string; social_account_id?: string; platform: string; display_name?: string | null; handle?: string | null;
  followers?: number | null; followers_delta?: number | null; impressions?: number | null; reach?: number | null; engagement_total?: number | null;
  last_synced_at?: string | null; series?: { date: string; followers?: number | null; value?: number | null }[]; availability?: Record<string, string>; error?: string | null;
}
export interface Recommendation {
  id: string; insight_id?: string | null; action: string; rationale?: string | null; expected_impact?: string | null; priority?: string | null;
  target?: Record<string, unknown>; status: string; created_at?: string | null; title?: string | null;
}
export interface Insight {
  id: string; statement: string; kind?: string; metric?: string | null; effect_size?: number | null; n?: number | null; confidence?: string | number | null;
  evidence?: Record<string, unknown>; ai_run_id?: string | null; period_start?: string | null; period_end?: string | null; status?: string;
  directional?: boolean; coverage?: unknown; excluded_platforms?: string[]; recommendations?: Recommendation[];
}
export type PostsRaw = ListResponse<PostPerf & { metrics?: Record<string, number | null> }> & { coverage?: Record<string, number> } | (PostPerf & { metrics?: Record<string, number | null> })[];
export type AccountsRaw = { accounts?: Record<string, unknown>[]; days?: number } | ListResponse<AccountPerf>;
export type InsightsRaw = ListResponse<Insight> | { insights?: Insight[]; recommendations?: Recommendation[]; items?: Insight[] };

export interface AnalyticsFilter { brand_id: string | null; from: string; to: string; platform?: string; compare?: "previous" }

export const analyticsApi = {
  overview: (f: AnalyticsFilter) => api.get<OverviewRaw>(`/analytics/overview${qs({ ...f })}`),
  breakdown: (f: AnalyticsFilter & { by: string; metric?: string }) => api.get<BreakdownRaw>(`/analytics/breakdown${qs({ ...f })}`),
  /** Backend sorts descending by a metric name (no "-" prefix): sort=engagement_rate. */
  posts: (f: AnalyticsFilter & { sort?: string; limit?: number }) => api.get<PostsRaw>(`/analytics/posts${qs({ ...f })}`),
  accounts: (f: { brand_id: string | null; days?: number }) => api.get<AccountsRaw>(`/analytics/accounts${qs({ ...f })}`),
  sync: (b: { brand_id: string | null; social_account_id?: string; force?: boolean }) => api.post<{ enqueued?: number; account_ids?: string[]; next_allowed_at?: string }>("/analytics/sync", b),
  insights: (f: { brand_id: string | null }) => api.get<InsightsRaw>(`/insights${qs(f)}`),
  recommendations: (f: { brand_id: string | null; status?: string }) => api.get<ListResponse<Recommendation>>(`/insights/recommendations${qs(f)}`),
  decide: (id: string, b: { status: "accepted" | "rejected"; reason?: string }) => api.patch<Recommendation>(`/insights/recommendations/${id}`, b),
  analyze: (b: { brand_id: string | null; period: string; compare_to?: string }) => api.post<{ run_id: string }>("/insights/analyze", b),
};

const LABELS: Record<string, string> = {
  impressions: "Impressions", reach: "Reach", views: "Views", engagement: "Engagements", engagements: "Engagements", engagement_rate: "Eng. rate",
  followers: "Followers (net)", followers_delta: "Followers (net)", posts: "Published", posts_published: "Published", clicks: "Clicks", saves: "Saves",
};
const label = (k: string) => LABELS[k] ?? k.replace(/_/g, " ").replace(/\b\w/g, (c) => c.toUpperCase());

export function coverageText(c: unknown, total?: number | null): string | null {
  if (c == null) return null;
  if (typeof c === "string") return c;
  if (typeof c === "number") return total != null ? `${c} of ${total} posts` : c <= 1 ? `${Math.round(c * 100)}% coverage` : `${c} posts with data`;
  if (isRecord(c)) {
    const n = num(c.n ?? c.covered ?? c.with_metric ?? c.with_metrics ?? c.posts_with_metric);
    const of = num(c.of ?? c.total ?? c.posts ?? c.posts_total);
    if (n != null && of != null) return `${n} of ${of} ${str(c.unit) ?? "posts"} have this metric`;
    if (typeof c.text === "string") return c.text;
  }
  return null;
}

/** basis may be a label ("sum", "count") or a histogram of rate bases ({impressions: 10, reach: 4}). */
export function basisText(b: unknown): string | null {
  if (b == null) return null;
  if (typeof b === "string") return b;
  if (isRecord(b)) {
    const parts = Object.entries(b).filter(([, v]) => typeof v === "number" && v > 0).map(([k, v]) => `${k.replace(/_/g, " ")} ${v}`);
    return parts.length ? `rate basis: ${parts.join(" · ")}` : null;
  }
  return null;
}

function toSeries(v: unknown): SeriesPoint[] {
  if (!Array.isArray(v)) return [];
  return v.flatMap((p) => {
    if (!isRecord(p)) return [];
    const date = str(p.date ?? p.day ?? p.t ?? p.period);
    return date ? [{ date, value: num(p.value ?? p.v), previous: num(p.previous ?? p.prev) }] : [];
  });
}

function kpiFrom(key: string, raw: unknown, opts: { fractionDelta?: boolean; total?: number | null } = {}): Kpi {
  const unit = /rate/.test(key) ? "rate" : "count";
  if (!isRecord(raw)) return { key, label: label(key), value: num(raw), previous: null, deltaPct: null, basis: null, coverage: null, series: [], unit };
  const k = str(raw.key) ?? key;
  const value = num(raw.value ?? raw.current ?? raw.total);
  const previous = num(raw.previous ?? raw.prev ?? raw.compare);
  let deltaPct = num(raw.delta_pct ?? raw.change_pct ?? raw.delta_percent);
  if (deltaPct != null && opts.fractionDelta) deltaPct *= 100;
  if (deltaPct == null && value != null && previous != null && previous !== 0) deltaPct = ((value - previous) / Math.abs(previous)) * 100;
  const isTotalKey = k === "posts_published" || k === "posts";
  return {
    key: k, label: str(raw.label) ?? label(k), value, previous, deltaPct,
    basis: basisText(raw.basis), coverage: isTotalKey ? null : coverageText(raw.coverage, opts.total), series: toSeries(raw.series ?? raw.sparkline), unit: /rate/.test(k) ? "rate" : unit,
  };
}

/** Accepts the backend `{kpis: {metric: {...}}}` dict, `{kpis: [...]}`, `{metrics: {...}}` or flat numbers. Adds a followers KPI from `accounts`. */
export function normalizeOverview(r: OverviewRaw | undefined): Kpi[] {
  if (!r) return [];
  let out: Kpi[];
  if (Array.isArray(r.kpis)) out = r.kpis.filter(isRecord).map((k) => kpiFrom(str(k.key) ?? "metric", k));
  else if (isRecord(r.kpis)) {
    const dict = r.kpis;
    const total = isRecord(dict.posts_published) ? num(dict.posts_published.value) : null;
    out = Object.entries(dict).map(([k, v]) => kpiFrom(k, v, { fractionDelta: true, total }));
  } else if (isRecord(r.metrics)) out = Object.entries(r.metrics).map(([k, v]) => kpiFrom(k, v));
  else out = Object.entries(r).filter(([k, v]) => typeof v === "number" && !k.endsWith("_prev")).map(([k, v]) => kpiFrom(k, { value: v, previous: r[`${k}_prev`] }));
  if (!out.some((k) => k.key.startsWith("followers")) && Array.isArray(r.accounts) && r.accounts.length) {
    const deltas = r.accounts.map((a) => num(a.followers_delta)).filter((x): x is number => x != null);
    out.push({ key: "followers_delta", label: "Followers (net)", value: deltas.length ? deltas.reduce((a, b) => a + b, 0) : null, previous: null, deltaPct: null,
      basis: "sum of daily account snapshots", coverage: `${deltas.length} of ${r.accounts.length} accounts report followers`, series: [], unit: "count" });
  }
  return out;
}

const ENG_KEYS = ["likes", "comments", "shares", "saves", "clicks"];
/** Flatten `{items:[{metrics:{…}, availability, engagement_rate, …}]}` into PostPerf rows (+ engagements total). */
export function normalizePosts(r: PostsRaw | undefined): { rows: PostPerf[]; coverage: string | null } {
  if (!r) return { rows: [], coverage: null };
  const list = Array.isArray(r) ? r : r.items ?? [];
  const rows = list.map((p) => {
    const m = (p.metrics ?? {}) as Record<string, number | null>;
    const flat: PostPerf = { ...p, ...m, id: p.id ?? p.published_post_id };
    const engVals = ENG_KEYS.map((k) => m[k]).filter((v): v is number => typeof v === "number");
    flat.engagements = p.engagements ?? (engVals.length ? engVals.reduce((a, b) => a + b, 0) : null);
    return flat;
  });
  return { rows, coverage: Array.isArray(r) ? null : coverageText(r.coverage) };
}

export function normalizeAccounts(r: AccountsRaw | undefined): AccountPerf[] {
  if (!r) return [];
  const list: unknown[] = Array.isArray(r) ? r : "accounts" in r && Array.isArray(r.accounts) ? r.accounts : "items" in r && Array.isArray(r.items) ? r.items : [];
  return list.filter(isRecord).map((a) => {
    const latest = isRecord(a.latest) ? a.latest : {};
    return {
      id: str(a.account_id ?? a.id ?? a.social_account_id) ?? undefined, platform: str(a.platform) ?? "", display_name: str(a.display_name), handle: str(a.handle),
      followers: num(a.followers ?? latest.followers), followers_delta: num(a.followers_delta), impressions: num(a.impressions ?? latest.impressions), reach: num(a.reach ?? latest.reach),
      last_synced_at: str(a.last_synced_at ?? a.last_synced), error: str(a.error) ?? (a.status && a.status !== "active" ? `Account ${String(a.status)}` : null),
      series: Array.isArray(a.series) ? (a.series as { date: string; followers?: number | null }[]) : [],
    };
  });
}

/** Daily engagement totals by publish date from post rows (client-side series). */
export function seriesFromPosts(rows: PostPerf[]): SeriesPoint[] {
  const byDay = new Map<string, number | null>();
  for (const p of rows) {
    if (!p.published_at) continue;
    const d = p.published_at.slice(0, 10);
    const cur = byDay.get(d) ?? null;
    byDay.set(d, p.engagements == null ? cur : (cur ?? 0) + p.engagements);
  }
  return Array.from(byDay.entries()).sort((a, b) => (a[0] < b[0] ? -1 : 1)).map(([date, value]) => ({ date, value }));
}

export function pickKpis(kpis: Kpi[], keys: string[][]): (Kpi | null)[] {
  return keys.map((alts) => kpis.find((k) => alts.includes(k.key)) ?? null);
}

export function normalizeBreakdown(r: BreakdownRaw | undefined): { groups: BreakdownGroup[]; coverage: string | null; basis: string | null } {
  if (!r) return { groups: [], coverage: null, basis: null };
  const groups = (r.groups ?? r.items ?? []).map((g) => ({ ...g, value: num(g.value), n: num(g.n) }));
  return { groups, coverage: coverageText(r.coverage), basis: basisText(r.basis) };
}

const WD: Record<string, number> = { mon: 0, tue: 1, wed: 2, thu: 3, fri: 4, sat: 5, sun: 6 };
/** Heatmap cell (Mon=0) from a by=hour group: explicit fields, "d:hh"/"d-hh" or "Mon 09"; hour-only keys → weekday -1. */
export function hourCell(g: BreakdownGroup): { weekday: number; hour: number } | null {
  if (g.hour != null) return { weekday: g.weekday != null ? (g.weekday + 6) % 7 : -1, hour: g.hour };
  const k = String(g.key).trim().toLowerCase();
  let m = /^(\d)[:\-_ ](\d{1,2})$/.exec(k);
  if (m) return { weekday: (Number(m[1]) + 6) % 7, hour: Number(m[2]) };
  m = /^([a-z]{3})[a-z]*[:\-_ ]+(\d{1,2})/.exec(k);
  if (m && m[1] in WD) return { weekday: WD[m[1]], hour: Number(m[2]) };
  if (/^\d{1,2}$/.test(k)) return { weekday: -1, hour: Number(k) };
  return null;
}

export function normalizeInsights(r: InsightsRaw | undefined): { insights: Insight[]; recommendations: Recommendation[] } {
  if (!r) return { insights: [], recommendations: [] };
  if (Array.isArray(r)) return { insights: r, recommendations: r.flatMap((i) => i.recommendations ?? []) };
  const insights = ("insights" in r && Array.isArray(r.insights) ? r.insights : null) ?? (Array.isArray(r.items) ? r.items : []);
  const recs = "recommendations" in r && Array.isArray(r.recommendations) ? r.recommendations : insights.flatMap((i) => i.recommendations ?? []);
  return { insights, recommendations: recs };
}

export const PERIODS = [{ id: "7d", days: 7, label: "Last 7 days" }, { id: "14d", days: 14, label: "Last 14 days" }, { id: "30d", days: 30, label: "Last 30 days" }, { id: "90d", days: 90, label: "Last 90 days" }];
/** Day-aligned ISO datetimes (stable within a day, so query keys don't churn). */
export function periodRange(days: number, now: Date): { from: string; to: string } {
  const from = new Date(now.getTime() - days * 86_400_000);
  return { from: `${from.toISOString().slice(0, 10)}T00:00:00Z`, to: `${now.toISOString().slice(0, 10)}T23:59:59Z` };
}

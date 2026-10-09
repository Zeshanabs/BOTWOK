/** Reports API (doc 00 §14 REPORTS, doc 24 §18). */
import { api, qs } from "@/lib/api";
import type { ListResponse } from "@/features/common/types";

export type ReportKind = "weekly_performance" | "competitor" | "campaign" | "custom";
export const REPORT_KINDS: { id: ReportKind; label: string; description: string }[] = [
  { id: "weekly_performance", label: "Weekly performance", description: "KPIs, top posts, what worked and what to do next." },
  { id: "competitor", label: "Competitor", description: "Cadence, formats and engagement vs selected competitors (allowed sources only)." },
  { id: "campaign", label: "Campaign", description: "Results of one campaign across platforms." },
  { id: "custom", label: "Custom", description: "Pick sections and give the report agent a brief." },
];
export const CUSTOM_SECTIONS = ["summary", "kpis", "top_posts", "platform_breakdown", "pillar_breakdown", "competitors", "trends", "recommendations"];

export interface ReportSection {
  key?: string; title: string; markdown?: string | null; body_md?: string | null; body?: string | null; ai_generated?: boolean;
  table?: { columns: string[]; rows: (string | number | null)[][] } | null; data_snapshot_at?: string | null; status?: string | null; error?: string | null;
}
export interface ReportSource { n?: number; id?: string; title?: string | null; url?: string | null; domain?: string | null; kind?: string | null; description?: string | null }
export interface Recipient { type: "email" | "slack" | "user" | string; value: string; status?: string | null }
export interface Report {
  id: string; brand_id?: string | null; kind: ReportKind | string; title: string; period_start?: string | null; period_end?: string | null;
  status?: "queued" | "running" | "completed" | "failed" | string; error?: string | null;
  content?: { sections?: ReportSection[]; sources?: ReportSource[]; summary?: string | null; markdown?: string | null; data_freshness?: string | null } | null;
  sections?: ReportSection[]; sources?: ReportSource[]; recipients?: Recipient[]; ai_run_id?: string | null; cost_usd?: number | null;
  created_at: string; schedule?: { rrule?: string; timezone?: string; next_run_at?: string | null } | null; format?: string | null;
}
export interface CreateReportBody {
  kind: ReportKind; brand_id: string | null; title?: string; period_start: string; period_end: string; platforms?: string[]; campaign_id?: string; competitor_ids?: string[];
  sections?: string[]; brief?: string; recipients: Recipient[]; format: "pdf" | "markdown" | "link"; schedule?: { rrule: string; timezone: string } | null;
}

export const reportsApi = {
  list: (f: { kind?: string; brand_id?: string | null; status?: string }) => api.get<ListResponse<Report>>(`/reports${qs(f)}`),
  create: (b: CreateReportBody) => api.post<Report | { report_id?: string; id?: string; run_id?: string }>("/reports", b),
  get: (id: string) => api.get<Report>(`/reports/${id}`),
};

export function reportSections(r: Report): ReportSection[] {
  const raw = (r.content?.sections ?? r.sections ?? []) as (ReportSection & { heading?: string; origin?: string })[];
  // The API (doc 13/16) emits {heading, markdown, charts, sources, origin}; normalize to the viewer's shape.
  return raw.map((s, i) => ({
    ...s,
    key: s.key ?? `s${i}`,
    title: s.title ?? s.heading ?? `Section ${i + 1}`,
    ai_generated: s.ai_generated ?? (s.origin ? s.origin === "ai" || s.origin === "agent" : false),
  }));
}
export function reportSources(r: Report): ReportSource[] {
  return r.content?.sources ?? r.sources ?? [];
}
export const kindLabel = (k: string) => REPORT_KINDS.find((x) => x.id === k)?.label ?? k.replace(/_/g, " ");

/** Trend types (doc 17 §Trends; backend/app/models/research.py Trend/TrendSignal). */

export interface TrendPoint { t?: string; at?: string; observed_at?: string; v?: number; value?: number }

export interface Trend {
  id: string;
  brand_id?: string;
  label: string;
  summary?: string | null;
  score: number | string;
  velocity?: number | string | null;
  status: string;
  state?: string | null;
  platforms?: string[];
  keywords?: string[];
  first_seen?: string;
  last_seen?: string;
  example_source_ids?: string[];
  sparkline?: number[] | null;
  series?: TrendPoint[] | null;
  source_counts?: Record<string, number> | null;
  sources_count?: number | null;
  fit?: { level?: string; pillar?: string | null; reason?: string | null } | string | null;
  ideas_count?: number | null;
  ai_run_id?: string | null;
}

export interface TrendSignal {
  id: string;
  kind: string;
  term: string;
  platform?: string | null;
  observed_at: string;
  value: number | string;
  source_id?: string | null;
  url?: string | null;
  title?: string | null;
}

export interface TrendDetail extends Trend {
  signals?: TrendSignal[];
  score_breakdown?: Record<string, number | string> | null;
  ideas?: { id: string; title: string; status?: string }[];
}

export const TREND_STATES = ["emerging", "rising", "peaking", "declining", "active", "dismissed"];

export function trendState(t: Trend): string {
  return t.state ?? t.status;
}

/** Sparkline values from whichever series shape the API returns. */
export function sparkValues(t: Trend | TrendDetail): number[] {
  if (Array.isArray(t.sparkline) && t.sparkline.length) return t.sparkline.map(Number);
  if (Array.isArray(t.series) && t.series.length) return t.series.map((p) => Number(p.v ?? p.value ?? 0));
  const signals = (t as TrendDetail).signals;
  if (Array.isArray(signals) && signals.length) {
    const byDay = new Map<string, number>();
    for (const s of signals) { const d = s.observed_at.slice(0, 10); byDay.set(d, (byDay.get(d) ?? 0) + Number(s.value || 0)); }
    return Array.from(byDay.entries()).sort((a, b) => a[0].localeCompare(b[0])).map(([, v]) => v);
  }
  return [];
}

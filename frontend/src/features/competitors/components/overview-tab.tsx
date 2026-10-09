"use client";
import { Bar, BarChart, CartesianGrid, Legend, Line, LineChart, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";
import { BarChart3 } from "lucide-react";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { EmptyState } from "@/components/data/empty-state";
import { ListSkeleton, QueryError } from "@/components/data/async-states";
import { fmtDate, toNumber } from "@/lib/formatters";
import { platformMeta } from "@/lib/platforms";
import { useCompetitorSnapshots } from "../hooks";
import type { CompetitorProfile, CompetitorSnapshot } from "../types";

const CHART = ["var(--chart-1)", "var(--chart-2)", "var(--chart-3)", "var(--chart-4)", "var(--chart-5)"];
const tooltipStyle = { background: "var(--popover)", border: "1px solid var(--border)", borderRadius: 8, color: "var(--popover-foreground)", fontSize: 12 };

function platformOf(s: CompetitorSnapshot, profiles: CompetitorProfile[]): string {
  return s.platform ?? profiles.find((p) => p.id === s.profile_id)?.platform ?? "other";
}

export function latestByProfile(snaps: CompetitorSnapshot[]): CompetitorSnapshot[] {
  const m = new Map<string, CompetitorSnapshot>();
  for (const s of snaps) {
    const k = s.profile_id ?? s.platform ?? "x";
    const cur = m.get(k);
    if (!cur || cur.captured_at < s.captured_at) m.set(k, s);
  }
  return Array.from(m.values());
}

export function OverviewTab({ competitorId, profiles }: { competitorId: string; profiles: CompetitorProfile[] }) {
  const q = useCompetitorSnapshots(competitorId);
  if (q.isLoading) return <ListSkeleton rows={3} rowClassName="h-56" />;
  if (q.error) return <QueryError error={q.error} onRetry={() => q.refetch()} title="Couldn't load snapshots" />;
  const snaps = [...(q.data ?? [])].sort((a, b) => a.captured_at.localeCompare(b.captured_at));
  if (!snaps.length) return <EmptyState icon={BarChart3} title="No snapshots yet" description="Snapshots appear after the first successful sync of an Official API or Public web profile." />;

  const platforms = Array.from(new Set(snaps.map((s) => platformOf(s, profiles))));
  const byDate = new Map<string, Record<string, number | string>>();
  for (const s of snaps) {
    const d = s.captured_at.slice(0, 10);
    const row = byDate.get(d) ?? { date: d };
    const v = toNumber(s.posts_last_7d);
    if (v !== null) row[platformOf(s, profiles)] = v;
    byDate.set(d, row);
  }
  const cadence = Array.from(byDate.values());

  const latest = latestByProfile(snaps);
  const mix: Record<string, number> = {};
  for (const s of latest) for (const [k, v] of Object.entries(s.format_mix ?? {})) mix[k] = (mix[k] ?? 0) + (toNumber(v) ?? 0);
  const mixTotal = Object.values(mix).reduce((a, b) => a + b, 0);
  const mixData = Object.entries(mix).map(([format, v]) => ({ format: format.replace(/_/g, " "), share: mixTotal ? Math.round((v / mixTotal) * 100) : 0 })).sort((a, b) => b.share - a.share);

  const hours: Record<string, number> = {};
  for (const s of latest) for (const [k, v] of Object.entries(s.posting_hours ?? {})) hours[k] = (hours[k] ?? 0) + (toNumber(v) ?? 0);
  const bestHours = Object.entries(hours).sort((a, b) => b[1] - a[1]).slice(0, 3);
  const lastAt = snaps[snaps.length - 1]?.captured_at;

  return (
    <div className="grid gap-4 lg:grid-cols-2">
      <Card className="lg:col-span-2">
        <CardHeader><CardTitle className="text-sm">Posting frequency (posts in last 7 days, per snapshot)</CardTitle></CardHeader>
        <CardContent className="h-64">
          <ResponsiveContainer width="100%" height="100%">
            <LineChart data={cadence} margin={{ left: -16, right: 8 }}>
              <CartesianGrid strokeDasharray="3 3" stroke="var(--border)" />
              <XAxis dataKey="date" tickFormatter={(d: string) => fmtDate(d, "MMM d")} fontSize={11} stroke="var(--muted-foreground)" />
              <YAxis allowDecimals={false} fontSize={11} stroke="var(--muted-foreground)" />
              <Tooltip contentStyle={tooltipStyle} />
              <Legend wrapperStyle={{ fontSize: 12 }} />
              {platforms.map((p, i) => <Line key={p} type="monotone" dataKey={p} name={platformMeta(p).label} stroke={CHART[i % CHART.length]} strokeWidth={2} dot={false} connectNulls />)}
            </LineChart>
          </ResponsiveContainer>
        </CardContent>
      </Card>
      <Card>
        <CardHeader><CardTitle className="text-sm">Format mix (latest snapshots)</CardTitle></CardHeader>
        <CardContent className="h-56">
          {mixData.length ? (
            <ResponsiveContainer width="100%" height="100%">
              <BarChart data={mixData} layout="vertical" margin={{ left: 16, right: 16 }}>
                <XAxis type="number" unit="%" fontSize={11} stroke="var(--muted-foreground)" />
                <YAxis type="category" dataKey="format" width={90} fontSize={11} stroke="var(--muted-foreground)" />
                <Tooltip contentStyle={tooltipStyle} formatter={(v) => [`${v}%`, "Share"]} />
                <Bar dataKey="share" fill="var(--chart-2)" radius={[0, 4, 4, 0]} />
              </BarChart>
            </ResponsiveContainer>
          ) : <p className="text-sm text-muted-foreground">No format data collected.</p>}
        </CardContent>
      </Card>
      <Card>
        <CardHeader><CardTitle className="text-sm">Latest numbers</CardTitle></CardHeader>
        <CardContent className="space-y-2 text-sm">
          {latest.map((s) => {
            const p = platformOf(s, profiles);
            return (
              <div key={s.id} className="flex justify-between gap-2">
                <span>{platformMeta(p).label}</span>
                <span className="tabular-nums text-muted-foreground">
                  {s.followers_count != null ? `${Number(s.followers_count).toLocaleString()} followers · ` : ""}{s.posts_last_30d != null ? `${s.posts_last_30d} posts/30d` : ""}
                  {s.avg_engagement != null ? ` · eng ${Number(s.avg_engagement).toFixed(2)}` : ""}
                </span>
              </div>
            );
          })}
          {bestHours.length > 0 && <p className="pt-2 text-xs text-muted-foreground">Most active hours (UTC): {bestHours.map(([h]) => `${h}:00`).join(", ")}</p>}
          <p className="pt-2 text-xs text-muted-foreground">Snapshot {fmtDate(lastAt)} · figures shown only where collected; nothing is imputed.</p>
        </CardContent>
      </Card>
    </div>
  );
}

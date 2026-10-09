"use client";
import Link from "next/link";
import { CartesianGrid, Line, LineChart, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";
import { ExternalLink, Lightbulb } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Sheet, SheetContent, SheetDescription, SheetHeader, SheetTitle } from "@/components/ui/sheet";
import { Skeleton } from "@/components/ui/skeleton";
import { StatusChip } from "@/components/data/status-chip";
import { PlatformIcon } from "@/components/data/platform-icon";
import { QueryError } from "@/components/data/async-states";
import { fmtDate, humanize, score100 } from "@/lib/formatters";
import { useSession } from "@/stores/session";
import { useTrend } from "../hooks";
import { trendState } from "../types";

export function TrendDrawer({ trendId, onOpenChange, onCreateIdeas, creating }: { trendId: string | null; onOpenChange: (o: boolean) => void; onCreateIdeas: (id: string) => void; creating?: boolean }) {
  const slug = useSession((s) => s.workspaceSlug);
  const q = useTrend(trendId);
  const t = q.data;
  const signals = [...(t?.signals ?? [])].sort((a, b) => a.observed_at.localeCompare(b.observed_at));
  const timeline = (() => {
    const m = new Map<string, number>();
    for (const s of signals) { const d = s.observed_at.slice(0, 10); m.set(d, (m.get(d) ?? 0) + Number(s.value || 0)); }
    return Array.from(m.entries()).map(([date, value]) => ({ date, value }));
  })();
  const breakdown = Object.entries(t?.score_breakdown ?? {});

  return (
    <Sheet open={!!trendId} onOpenChange={onOpenChange}>
      <SheetContent className="w-full overflow-y-auto sm:max-w-xl">
        <SheetHeader>
          <SheetTitle>{t?.label ?? "Trend"}</SheetTitle>
          <SheetDescription>{t ? `Score ${score100(t.score) ?? "—"} · first seen ${fmtDate(t.first_seen)} · last seen ${fmtDate(t.last_seen)}` : "Loading…"}</SheetDescription>
        </SheetHeader>
        <div className="space-y-5 px-4 pb-6 text-sm">
          {q.isLoading && <div className="space-y-2"><Skeleton className="h-20" /><Skeleton className="h-40" /></div>}
          {q.error != null && <QueryError error={q.error} onRetry={() => q.refetch()} title="Couldn't load trend" notFoundText="This trend no longer exists." />}
          {t && (
            <>
              <div className="flex flex-wrap items-center gap-2">
                <StatusChip status={trendState(t)} />
                {(t.platforms ?? []).map((p) => <PlatformIcon key={p} platform={p} size={18} />)}
                <Button size="sm" className="ml-auto" disabled={creating} onClick={() => onCreateIdeas(t.id)}><Lightbulb className="h-3 w-3" /> Create ideas from trend</Button>
              </div>
              {t.summary && <p><span className="text-ai">✦</span> {t.summary}</p>}
              {breakdown.length > 0 && (
                <section>
                  <h3 className="mb-2 text-xs font-semibold uppercase tracking-wide text-muted-foreground">Score breakdown</h3>
                  <div className="space-y-2">
                    {breakdown.map(([k, v]) => {
                      const s = score100(v) ?? 0;
                      return (
                        <div key={k}>
                          <div className="flex justify-between text-xs"><span>{humanize(k)}</span><span className="tabular-nums">{s}</span></div>
                          <div className="mt-1 h-1.5 rounded-full bg-muted"><div className="h-1.5 rounded-full bg-primary" style={{ width: `${Math.min(100, s)}%` }} /></div>
                        </div>
                      );
                    })}
                  </div>
                </section>
              )}
              {timeline.length > 1 && (
                <section>
                  <h3 className="mb-2 text-xs font-semibold uppercase tracking-wide text-muted-foreground">Signal timeline</h3>
                  <div className="h-40">
                    <ResponsiveContainer width="100%" height="100%">
                      <LineChart data={timeline} margin={{ left: -20, right: 8 }}>
                        <CartesianGrid strokeDasharray="3 3" stroke="var(--border)" />
                        <XAxis dataKey="date" tickFormatter={(d: string) => fmtDate(d, "MMM d")} fontSize={11} stroke="var(--muted-foreground)" />
                        <YAxis fontSize={11} stroke="var(--muted-foreground)" />
                        <Tooltip contentStyle={{ background: "var(--popover)", border: "1px solid var(--border)", borderRadius: 8, fontSize: 12 }} />
                        <Line type="monotone" dataKey="value" stroke="var(--chart-2)" strokeWidth={2} dot={false} />
                      </LineChart>
                    </ResponsiveContainer>
                  </div>
                </section>
              )}
              {(t.keywords?.length ?? 0) > 0 && (
                <section><h3 className="mb-1 text-xs font-semibold uppercase tracking-wide text-muted-foreground">Keywords</h3>
                  <div className="flex flex-wrap gap-1">{t.keywords?.map((k) => <span key={k} className="rounded-full bg-secondary px-2 py-0.5 text-xs">{k}</span>)}</div></section>
              )}
              <section>
                <h3 className="mb-1 text-xs font-semibold uppercase tracking-wide text-muted-foreground">Signals ({signals.length})</h3>
                {signals.length ? (
                  <ul className="divide-y rounded-lg border text-xs">
                    {[...signals].reverse().slice(0, 50).map((s) => (
                      <li key={s.id} className="flex items-center gap-2 p-2">
                        {s.platform && <PlatformIcon platform={s.platform} size={16} />}
                        <span className="w-16 shrink-0 text-muted-foreground">{s.kind}</span>
                        <span className="min-w-0 flex-1 truncate">{s.title ?? s.term}</span>
                        <span className="tabular-nums text-muted-foreground">{Number(s.value).toLocaleString()}</span>
                        <span className="text-muted-foreground">{fmtDate(s.observed_at, "MMM d")}</span>
                        {s.url && <a href={s.url} target="_blank" rel="noreferrer noopener" aria-label="Open signal source"><ExternalLink className="h-3 w-3" /></a>}
                      </li>
                    ))}
                  </ul>
                ) : <p className="text-xs text-muted-foreground">No signals returned for this trend.</p>}
              </section>
              {(t.ideas?.length ?? 0) > 0 && (
                <section><h3 className="mb-1 text-xs font-semibold uppercase tracking-wide text-muted-foreground">Ideas created</h3>
                  <ul className="space-y-1">{t.ideas?.map((i) => <li key={i.id}><Link href={`/w/${slug}/ideas`} className="text-primary hover:underline">{i.title}</Link></li>)}</ul></section>
              )}
            </>
          )}
        </div>
      </SheetContent>
    </Sheet>
  );
}

"use client";
import { useState } from "react";
import { usePathname, useRouter, useSearchParams } from "next/navigation";
import { useQueryClient } from "@tanstack/react-query";
import { toast } from "sonner";
import { Lightbulb, RefreshCw, TrendingDown, TrendingUp, X } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { PageHeader } from "@/components/data/page-header";
import { PlatformIcon } from "@/components/data/platform-icon";
import { StatusChip } from "@/components/data/status-chip";
import { Sparkline } from "@/components/data/sparkline";
import { EmptyState } from "@/components/data/empty-state";
import { CardGridSkeleton, QueryError, errorMessage, isNotAvailable } from "@/components/data/async-states";
import { fmtRelative, score100, toNumber } from "@/lib/formatters";
import { PLATFORMS } from "@/lib/platforms";
import { useCan } from "@/lib/permissions";
import { useSession } from "@/stores/session";
import { useActiveBrandId, useBrands } from "@/features/brand/hooks";
import { useGenerateIdeas } from "@/features/ideas/hooks";
import { RunProgress } from "@/features/ai/components/run-progress";
import { useScanTrends, useTrends } from "../hooks";
import { TREND_STATES, sparkValues, trendState, type Trend } from "../types";
import { TrendDrawer } from "./trend-drawer";

const ALL = "all";

function FitLine({ fit }: { fit: Trend["fit"] }) {
  if (!fit) return null;
  if (typeof fit === "string") return <p className="text-xs"><span className="text-ai">✦</span> Fit {fit}</p>;
  return <p className="text-xs"><span className="text-ai">✦</span> Fit {fit.level ?? "—"}{fit.pillar ? ` — pillar “${fit.pillar}”` : fit.reason ? ` — ${fit.reason}` : " — no matching pillar"}</p>;
}

export function TrendsView() {
  const router = useRouter();
  const pathname = usePathname();
  const sp = useSearchParams();
  const qc = useQueryClient();
  const slug = useSession((s) => s.workspaceSlug);
  const can = useCan();
  const brandId = useActiveBrandId();
  const brandName = useBrands().data?.find((b) => b.id === brandId)?.name;
  const [state, setState] = useState(ALL);
  const [minScore, setMinScore] = useState("0");
  const [platform, setPlatform] = useState(ALL);
  const [search, setSearch] = useState("");
  const [scanRun, setScanRun] = useState<string | null>(null);
  const trends = useTrends(brandId, state);
  const scan = useScanTrends();
  const generate = useGenerateIdeas();
  const openId = sp.get("trend");
  const setOpen = (id: string | null) => router.replace(id ? `${pathname}?trend=${id}` : pathname);

  function startScan() {
    if (!brandId) return;
    scan.mutate(brandId, {
      onSuccess: (d) => { if (d?.run_id) setScanRun(d.run_id); else toast.success("Scan started — new trends will appear as they're detected"); },
      onError: (e) => toast.error(isNotAvailable(e) ? "Trend scanning isn't available on this install yet." : errorMessage(e)),
    });
  }
  function createIdeas(id: string) {
    if (!brandId) return;
    generate.mutate({ brand_id: brandId, count: 5, from: { trend_ids: [id] } }, {
      onSuccess: (d) => router.push(`/w/${slug}/ideas?run=${d.run_id}`),
      onError: (e) => toast.error(isNotAvailable(e) ? "Idea generation isn't available yet." : errorMessage(e)),
    });
  }

  const list = (trends.data ?? [])
    .filter((t) => (score100(t.score) ?? 0) >= Number(minScore))
    .filter((t) => platform === ALL || (t.platforms ?? []).includes(platform))
    .filter((t) => !search || `${t.label} ${(t.keywords ?? []).join(" ")}`.toLowerCase().includes(search.toLowerCase()))
    .sort((a, b) => (score100(b.score) ?? 0) - (score100(a.score) ?? 0));
  const lastScan = (trends.data ?? []).map((t) => t.last_seen).filter(Boolean).sort().pop();

  return (
    <div>
      <PageHeader title={`Trends${brandName ? ` · ${brandName}` : ""}`} description="Signals from news, web and permitted social sources, scored for this brand."
                  actions={can.create ? <Button onClick={startScan} disabled={!brandId || scan.isPending}><RefreshCw className="h-4 w-4" /> {scan.isPending ? "Starting…" : "Scan now"}</Button> : undefined} />

      <div className="mb-4 flex flex-wrap items-center gap-2">
        <Select value={state} onValueChange={setState}>
          <SelectTrigger size="sm" aria-label="State"><SelectValue /></SelectTrigger>
          <SelectContent><SelectItem value={ALL}>All states</SelectItem>{TREND_STATES.map((s) => <SelectItem key={s} value={s}>{s}</SelectItem>)}</SelectContent>
        </Select>
        <Select value={minScore} onValueChange={setMinScore}>
          <SelectTrigger size="sm" aria-label="Minimum score"><SelectValue /></SelectTrigger>
          <SelectContent>{["0", "40", "60", "80"].map((s) => <SelectItem key={s} value={s}>{s === "0" ? "Any score" : `Score ≥ ${s}`}</SelectItem>)}</SelectContent>
        </Select>
        <Select value={platform} onValueChange={setPlatform}>
          <SelectTrigger size="sm" aria-label="Platform"><SelectValue /></SelectTrigger>
          <SelectContent><SelectItem value={ALL}>All platforms</SelectItem>{PLATFORMS.map((p) => <SelectItem key={p.id} value={p.id}>{p.label}</SelectItem>)}</SelectContent>
        </Select>
        <Input value={search} onChange={(e) => setSearch(e.target.value)} placeholder="Search trends…" className="h-8 w-full sm:w-56" aria-label="Search trends" />
      </div>

      {scanRun && (
        <Card className="mb-4">
          <CardHeader className="flex flex-row items-center justify-between"><CardTitle className="text-sm">Trend scan</CardTitle>
            <Button variant="ghost" size="icon-sm" aria-label="Dismiss" onClick={() => setScanRun(null)}><X className="h-4 w-4" /></Button></CardHeader>
          <CardContent><RunProgress runId={scanRun} compact onFinished={() => qc.invalidateQueries({ queryKey: ["trends"] })} /></CardContent>
        </Card>
      )}

      {!brandId ? <EmptyState icon={TrendingUp} title="Select a brand" description="Trends are scored per brand. Pick one in the header." /> :
       trends.isLoading ? <CardGridSkeleton count={4} className="xl:grid-cols-2" /> : trends.error ? (
        <QueryError error={trends.error} onRetry={() => trends.refetch()} title="Couldn't load trends" />
      ) : !list.length ? (
        <div className="rounded-xl border border-dashed p-10 text-center">
          <TrendingUp className="mx-auto mb-3 h-8 w-8 text-muted-foreground" />
          <p className="font-medium">{(trends.data ?? []).length ? "No trends match these filters." : "No trends detected yet."}</p>
          <div className="mt-4 flex justify-center gap-2">
            {(trends.data ?? []).length > 0 && <Button variant="outline" onClick={() => { setMinScore("0"); setPlatform(ALL); setState(ALL); setSearch(""); }}>Clear filters</Button>}
            {can.create && <Button onClick={startScan} disabled={scan.isPending}>Scan now</Button>}
          </div>
        </div>
      ) : (
        <div className="grid gap-4 xl:grid-cols-2">
          {list.map((t) => {
            const vel = toNumber(t.velocity);
            return (
              <Card key={t.id} className="gap-3">
                <CardHeader className="flex flex-row items-start justify-between gap-2">
                  <CardTitle className="text-base">
                    <button type="button" className="text-left hover:underline" onClick={() => setOpen(t.id)}>
                      {vel !== null && vel < 0 ? <TrendingDown className="mr-1 inline h-4 w-4 text-red-600" /> : <TrendingUp className="mr-1 inline h-4 w-4 text-green-600" />}{t.label}
                    </button>
                  </CardTitle>
                  <span className="shrink-0 text-sm font-semibold tabular-nums">Score {score100(t.score) ?? "—"}</span>
                </CardHeader>
                <CardContent className="space-y-2 text-sm">
                  <div className="flex flex-wrap items-center gap-3">
                    <Sparkline values={sparkValues(t)} />
                    {vel !== null && <span className={vel >= 0 ? "text-xs text-green-700 dark:text-green-300" : "text-xs text-red-700 dark:text-red-300"}>{vel >= 0 ? "+" : ""}{(Math.abs(vel) <= 1 ? vel * 100 : vel).toFixed(0)}%/wk</span>}
                    <StatusChip status={trendState(t)} />
                  </div>
                  {(t.source_counts || t.sources_count != null) && (
                    <p className="text-xs text-muted-foreground">
                      {t.sources_count ?? Object.values(t.source_counts ?? {}).reduce((a, b) => a + b, 0)} sources
                      {t.source_counts && ` · ${Object.entries(t.source_counts).map(([k, v]) => `${k} ${v}`).join(" · ")}`}
                    </p>
                  )}
                  {(t.platforms?.length ?? 0) > 0 && <div className="flex items-center gap-1 text-xs text-muted-foreground">Platforms {t.platforms?.map((p) => <PlatformIcon key={p} platform={p} size={16} />)}</div>}
                  {(t.keywords?.length ?? 0) > 0 && <div className="flex flex-wrap gap-1">{t.keywords?.slice(0, 6).map((k) => <span key={k} className="rounded-full bg-secondary px-2 py-0.5 text-xs">{k}</span>)}</div>}
                  <FitLine fit={t.fit} />
                  <div className="flex flex-wrap gap-2 pt-1">
                    {can.create && <Button size="sm" disabled={generate.isPending} onClick={() => createIdeas(t.id)}><Lightbulb className="h-3 w-3" /> Create ideas from trend</Button>}
                    <Button size="sm" variant="outline" onClick={() => setOpen(t.id)}>Details</Button>
                  </div>
                </CardContent>
              </Card>
            );
          })}
        </div>
      )}
      {(trends.data ?? []).length > 0 && <p className="mt-4 text-xs text-muted-foreground">Last signal {fmtRelative(lastScan)} · showing {list.length} of {trends.data?.length}</p>}
      <TrendDrawer trendId={openId} onOpenChange={(o) => { if (!o) setOpen(null); }} onCreateIdeas={createIdeas} creating={generate.isPending} />
    </div>
  );
}

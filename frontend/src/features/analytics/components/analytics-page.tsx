"use client";
import { useState } from "react";
import Link from "next/link";
import { useMutation, useQuery } from "@tanstack/react-query";
import { ArrowUpDown, BarChart3, Download, ExternalLink, FileText, Info, Loader2, RefreshCw, Sparkles } from "lucide-react";
import { toast } from "sonner";
import { Alert, AlertDescription } from "@/components/ui/alert";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { DropdownMenu, DropdownMenuContent, DropdownMenuItem, DropdownMenuSeparator, DropdownMenuTrigger } from "@/components/ui/dropdown-menu";
import { Label } from "@/components/ui/label";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { Skeleton } from "@/components/ui/skeleton";
import { Switch } from "@/components/ui/switch";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { Tabs, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { EmptyState } from "@/components/shared/empty-state";
import { PlatformIcon } from "@/components/shared/platform-icon";
import { QueryError } from "@/features/common/components/query-state";
import { RunCard } from "@/features/common/components/run-card";
import { useActiveBrand, usePermissions, useWorkspacePath } from "@/features/common/hooks";
import { downloadText, errorMessage, errorStatus, fmtCompact, fmtDate, fmtInt, fmtPct, isNotAvailable, relTime, toCsv } from "@/features/common/utils";
import { PLATFORMS, platformMeta } from "@/lib/platforms";
import { cn } from "@/lib/utils";
import { analyticsApi, normalizeAccounts, normalizeBreakdown, normalizeInsights, normalizeOverview, normalizePosts, PERIODS, periodRange, pickKpis, seriesFromPosts, type AnalyticsFilter, type PostPerf, type SeriesPoint } from "../api";
import { BarBreakdown, Heatmap, TimeSeriesChart, WeekdayStrip } from "./charts";
import { KpiCard, KpiSkeleton } from "./kpi-card";
import { RecommendationList } from "./recommendations";

const ALL = "all";
type SortKey = "engagement_rate" | "impressions" | "engagements" | "saves" | "clicks" | "published_at";

function weekly(points: SeriesPoint[]): SeriesPoint[] {
  const out = new Map<string, SeriesPoint>();
  for (const p of points) {
    const d = new Date(`${p.date.slice(0, 10)}T00:00:00Z`);
    const monday = new Date(d.getTime() - ((d.getUTCDay() + 6) % 7) * 86_400_000).toISOString().slice(0, 10);
    const cur = out.get(monday) ?? { date: monday, value: null, previous: null };
    cur.value = p.value == null ? cur.value : (cur.value ?? 0) + p.value;
    cur.previous = p.previous == null ? cur.previous : (cur.previous ?? 0) + p.previous;
    out.set(monday, cur);
  }
  return Array.from(out.values());
}

/** Analytics (doc 24 §17): normalized KPIs with basis/coverage, charts, heatmap, top posts, growth, insights, sync, CSV export. */
export function AnalyticsPage() {
  const ws = useWorkspacePath();
  const { brandId, brand } = useActiveBrand();
  const { canCreate } = usePermissions();
  const [period, setPeriod] = useState("30d");
  const [compare, setCompare] = useState(true);
  const [platform, setPlatform] = useState(ALL);
  const [byTab, setByTab] = useState<"pillar" | "format">("pillar");
  const [grain, setGrain] = useState<"day" | "week">("day");
  const [postPlatform, setPostPlatform] = useState<string | null>(null);
  const [sort, setSort] = useState<{ key: SortKey; desc: boolean }>({ key: "engagement_rate", desc: true });
  const [analyzeRun, setAnalyzeRun] = useState<string | null>(null);
  const days = PERIODS.find((p) => p.id === period)?.days ?? 30;
  const range = periodRange(days, new Date());
  const f: AnalyticsFilter = { brand_id: brandId, ...range, platform: platform === ALL ? undefined : platform, compare: compare ? "previous" : undefined };
  const enabled = !!brandId;

  const overview = useQuery({ queryKey: ["analytics", "overview", f], queryFn: () => analyticsApi.overview(f), enabled });
  const byPlatform = useQuery({ queryKey: ["analytics", "breakdown", "platform", f], queryFn: () => analyticsApi.breakdown({ ...f, by: "platform", metric: "engagement_rate" }), enabled });
  const byOther = useQuery({ queryKey: ["analytics", "breakdown", byTab, f], queryFn: () => analyticsApi.breakdown({ ...f, by: byTab, metric: "engagement_rate" }), enabled });
  const byHour = useQuery({ queryKey: ["analytics", "breakdown", "hour", f], queryFn: () => analyticsApi.breakdown({ ...f, by: "hour", metric: "engagement_rate" }), enabled });
  const byWeekday = useQuery({ queryKey: ["analytics", "breakdown", "weekday", f], queryFn: () => analyticsApi.breakdown({ ...f, by: "weekday", metric: "engagement_rate" }), enabled });
  const posts = useQuery({ queryKey: ["analytics", "posts", f], queryFn: () => analyticsApi.posts({ ...f, sort: "engagement_rate", limit: 200 }), enabled });
  const accounts = useQuery({ queryKey: ["analytics", "accounts", brandId, days], queryFn: () => analyticsApi.accounts({ brand_id: brandId, days }), enabled });
  const insights = useQuery({ queryKey: ["insights", "list", brandId], queryFn: () => analyticsApi.insights({ brand_id: brandId }), enabled, retry: false });

  const kpis = normalizeOverview(overview.data);
  const [impr, eng, rate, foll] = pickKpis(kpis, [["impressions", "reach", "views"], ["engagements", "engagement"], ["engagement_rate"], ["followers", "followers_delta", "followers_net"]]);
  const postData = normalizePosts(posts.data);
  const seriesSource = eng?.series.length ? eng : impr?.series.length ? impr : null;
  // No time-series endpoint: derive daily engagement totals from the period's posts (by publish date).
  const rawSeries: SeriesPoint[] = seriesSource?.series ?? seriesFromPosts(postData.rows);
  const series = grain === "week" ? weekly(rawSeries) : rawSeries;
  const accountRows = normalizeAccounts(accounts.data);
  const weekdayB = normalizeBreakdown(byWeekday.data);
  const platformB = normalizeBreakdown(byPlatform.data);
  const otherB = normalizeBreakdown(byOther.data);
  const hourB = normalizeBreakdown(byHour.data);
  const { insights: insightList, recommendations } = normalizeInsights(insights.data);
  const postRows = postData.rows.filter((p) => !postPlatform || p.platform === postPlatform);
  const sortedPosts = [...postRows].sort((a, b) => {
    const va = sort.key === "published_at" ? new Date(a.published_at ?? 0).getTime() : (a[sort.key] as number | null | undefined) ?? -Infinity;
    const vb = sort.key === "published_at" ? new Date(b.published_at ?? 0).getTime() : (b[sort.key] as number | null | undefined) ?? -Infinity;
    return sort.desc ? vb - va : va - vb;
  });
  const lastSynced = overview.data?.last_synced_at ?? null;

  const sync = useMutation({
    mutationFn: () => analyticsApi.sync({ brand_id: brandId }),
    onSuccess: (r) => toast.success(r.enqueued === 0 ? "No active accounts to sync" : `Sync queued for ${r.enqueued ?? "your"} account${r.enqueued === 1 ? "" : "s"} — charts refresh as metrics arrive`, { description: r.next_allowed_at ? `Next manual sync ${relTime(r.next_allowed_at)}` : undefined }),
    onError: (e) => toast.error(errorStatus(e) === 429 ? `Synced recently: ${errorMessage(e)}` : isNotAvailable(e) ? "Analytics sync isn't available on this backend yet" : errorMessage(e)),
  });
  const analyze = useMutation({
    mutationFn: () => analyticsApi.analyze({ brand_id: brandId, period: `${days}d`, compare_to: "previous" }),
    onSuccess: (r) => setAnalyzeRun(r.run_id),
    onError: (e) => toast.error(isNotAvailable(e) ? "AI analysis isn't available on this backend yet" : errorMessage(e)),
  });
  const exportCsv = (what: "posts" | "breakdowns" | "accounts" | "kpis") => {
    const stamp = `${range.from.slice(0, 10)}_${range.to.slice(0, 10)}`;
    if (what === "posts") downloadText(toCsv(sortedPosts.map((p) => ({ title: p.title, platform: p.platform, published_at: p.published_at, impressions: p.impressions, reach: p.reach, engagements: p.engagements, engagement_rate: p.engagement_rate, saves: p.saves, clicks: p.clicks, url: p.external_url }))), `top-posts_${stamp}.csv`);
    if (what === "breakdowns") downloadText(toCsv([...platformB.groups.map((g) => ({ by: "platform", key: g.key, n: g.n, engagement_rate: g.value })), ...otherB.groups.map((g) => ({ by: byTab, key: g.key, n: g.n, engagement_rate: g.value })), ...hourB.groups.map((g) => ({ by: "hour", key: g.key, n: g.n, engagement_rate: g.value }))]), `breakdowns_${stamp}.csv`);
    if (what === "accounts") downloadText(toCsv(accountRows.map((a) => ({ platform: a.platform, account: a.display_name, followers: a.followers, followers_delta: a.followers_delta, impressions: a.impressions, reach: a.reach, last_synced_at: a.last_synced_at }))), `accounts_${stamp}.csv`);
    if (what === "kpis") downloadText(toCsv(kpis.map((k) => ({ metric: k.key, value: k.value, previous: k.previous, delta_pct: k.deltaPct, basis: k.basis, coverage: k.coverage }))), `kpis_${stamp}.csv`);
  };
  const sortHead = (key: SortKey, label: string) => (
    <TableHead className="text-right"><button type="button" className="inline-flex items-center gap-1 hover:text-foreground" onClick={() => setSort((s) => ({ key, desc: s.key === key ? !s.desc : true }))} aria-label={`Sort by ${label}`}>{label}<ArrowUpDown className={cn("h-3 w-3", sort.key === key ? "opacity-100" : "opacity-30")} /></button></TableHead>
  );
  const metricCell = (p: PostPerf, k: keyof PostPerf, rateCol?: boolean) => {
    const v = p[k] as number | null | undefined;
    const why = p.availability?.[k as string];
    if (v == null) return <TableCell className="text-right text-muted-foreground" title={why ? `n/a — ${why.replace(/_/g, " ")}` : "Not provided by this platform for this format"}>n/a</TableCell>;
    return <TableCell className="text-right tabular-nums">{rateCol ? fmtPct(v) : fmtCompact(v)}</TableCell>;
  };

  if (!brandId) return <EmptyState icon={BarChart3} title="Select a brand to see analytics" />;
  return (
    <div className="space-y-6">
      <div className="flex flex-col gap-3 lg:flex-row lg:items-center">
        <div className="flex-1"><h1 className="text-2xl font-semibold tracking-tight">Analytics{brand ? ` · ${brand.name}` : ""}</h1>
          <p className="text-sm text-muted-foreground">Normalized cross-platform performance{lastSynced ? ` · last synced ${relTime(lastSynced)}` : ""}</p></div>
        <div className="flex flex-wrap items-center gap-2">
          <Select value={period} onValueChange={setPeriod}><SelectTrigger size="sm" className="w-36" aria-label="Period"><SelectValue /></SelectTrigger>
            <SelectContent>{PERIODS.map((p) => <SelectItem key={p.id} value={p.id}>{p.label}</SelectItem>)}</SelectContent></Select>
          <div className="flex items-center gap-1.5"><Switch id="cmp" checked={compare} onCheckedChange={setCompare} /><Label htmlFor="cmp" className="text-xs">vs prev</Label></div>
          <Select value={platform} onValueChange={setPlatform}><SelectTrigger size="sm" className="w-36" aria-label="Platform"><SelectValue /></SelectTrigger>
            <SelectContent><SelectItem value={ALL}>All platforms</SelectItem>{PLATFORMS.map((p) => <SelectItem key={p.id} value={p.id}>{p.label}</SelectItem>)}</SelectContent></Select>
          {canCreate && <Button size="sm" variant="outline" onClick={() => sync.mutate()} disabled={sync.isPending}>{sync.isPending ? <Loader2 className="animate-spin" /> : <RefreshCw />} Sync now</Button>}
          {canCreate && <Button size="sm" variant="outline" onClick={() => analyze.mutate()} disabled={analyze.isPending}>{analyze.isPending ? <Loader2 className="animate-spin" /> : <Sparkles className="text-ai" />} Analyze</Button>}
          <DropdownMenu>
            <DropdownMenuTrigger asChild><Button size="sm" variant="outline"><Download /> Export</Button></DropdownMenuTrigger>
            <DropdownMenuContent align="end">
              <DropdownMenuItem onClick={() => exportCsv("kpis")}>KPIs (CSV)</DropdownMenuItem>
              <DropdownMenuItem onClick={() => exportCsv("posts")} disabled={!sortedPosts.length}>Top posts (CSV)</DropdownMenuItem>
              <DropdownMenuItem onClick={() => exportCsv("breakdowns")}>Breakdowns (CSV)</DropdownMenuItem>
              <DropdownMenuItem onClick={() => exportCsv("accounts")}>Account growth (CSV)</DropdownMenuItem>
              <DropdownMenuSeparator />
              <DropdownMenuItem asChild><Link href={ws("reports?new=weekly_performance")}><FileText /> Create report</Link></DropdownMenuItem>
            </DropdownMenuContent>
          </DropdownMenu>
        </div>
      </div>

      {analyzeRun && <RunCard runId={analyzeRun} title="✦ performance_analyst · analysis" onDone={() => void insights.refetch()} />}

      {overview.error ? <QueryError error={overview.error} onRetry={() => overview.refetch()} title="Couldn't load KPIs" notAvailableText="Analytics isn't available on this backend yet. Connect accounts and sync to collect metrics." /> : (
        <div className="grid grid-cols-2 gap-3 lg:grid-cols-4">
          {overview.isLoading ? Array.from({ length: 4 }).map((_, i) => <KpiSkeleton key={i} />) : (
            <>
              <KpiCard kpi={impr} label={impr?.label ?? "Impressions"} showDelta={compare} />
              <KpiCard kpi={eng} label="Engagements" showDelta={compare} />
              <KpiCard kpi={rate} label="Eng. rate" showDelta={compare} />
              <KpiCard kpi={foll} label="Followers (net)" showDelta={compare} />
            </>
          )}
        </div>
      )}

      <div className="grid gap-4 lg:grid-cols-2">
        <Card className="gap-2">
          <CardHeader className="flex flex-row items-center justify-between"><CardTitle className="text-sm">Engagement over time</CardTitle>
            <div className="flex rounded-md border p-0.5 text-xs" role="radiogroup" aria-label="Granularity">{(["day", "week"] as const).map((g) => <button key={g} type="button" role="radio" aria-checked={grain === g} onClick={() => setGrain(g)} className={cn("rounded px-2 py-0.5", grain === g && "bg-secondary")}>{g}</button>)}</div>
          </CardHeader>
          <CardContent>{overview.isLoading || posts.isLoading ? <Skeleton className="h-56" /> : series.length ? <TimeSeriesChart data={series} unit={seriesSource?.unit ?? "count"} showPrevious={compare && series.some((p) => p.previous != null)} /> : <p className="py-16 text-center text-sm text-muted-foreground">No engagement data for this period yet.</p>}
            {!seriesSource && series.length > 0 && <p className="mt-1 text-[11px] text-muted-foreground">Engagements (likes + comments + shares + saves + clicks where provided) summed by publish date.</p>}</CardContent>
        </Card>
        <Card className="gap-2">
          <CardHeader><CardTitle className="text-sm">By platform · eng. rate {postPlatform && <button type="button" className="ml-2 text-xs font-normal text-primary hover:underline" onClick={() => setPostPlatform(null)}>clear filter ({platformMeta(postPlatform).label})</button>}</CardTitle></CardHeader>
          <CardContent>{byPlatform.isLoading ? <Skeleton className="h-48" /> : byPlatform.error ? <QueryError error={byPlatform.error} onRetry={() => byPlatform.refetch()} notAvailableText="Breakdowns aren't available yet." /> : <BarBreakdown groups={platformB.groups} platformKeys onSelect={setPostPlatform} selected={postPlatform} />}
            {platformB.coverage && <p className="mt-1 text-[11px] text-muted-foreground">{platformB.coverage}</p>}</CardContent>
        </Card>
        <Card className="gap-2">
          <CardHeader className="flex flex-row items-center justify-between"><CardTitle className="text-sm">By {byTab}</CardTitle>
            <Tabs value={byTab} onValueChange={(v) => setByTab(v as"pillar" | "format")}><TabsList className="h-7"><TabsTrigger value="pillar" className="text-xs">Pillar</TabsTrigger><TabsTrigger value="format" className="text-xs">Format</TabsTrigger></TabsList></Tabs>
          </CardHeader>
          <CardContent>{byOther.isLoading ? <Skeleton className="h-48" /> : byOther.error ? <QueryError error={byOther.error} onRetry={() => byOther.refetch()} notAvailableText="Breakdowns aren't available yet." /> : <BarBreakdown groups={otherB.groups} />}
            {otherB.basis && <p className="mt-1 text-[11px] text-muted-foreground">{otherB.basis}</p>}</CardContent>
        </Card>
        <Card className="gap-2">
          <CardHeader><CardTitle className="text-sm">Best hours · eng. rate</CardTitle></CardHeader>
          <CardContent className="space-y-3">{byHour.isLoading ? <Skeleton className="h-48" /> : byHour.error ? <QueryError error={byHour.error} onRetry={() => byHour.refetch()} notAvailableText="Hour breakdown isn't available yet." /> : <Heatmap groups={hourB.groups} />}
            {!byWeekday.error && weekdayB.groups.length > 0 && <WeekdayStrip groups={weekdayB.groups} />}</CardContent>
        </Card>
      </div>

      <Alert><Info /><AlertDescription>Normalized metrics: not all platforms expose all metrics. <strong>n/a</strong> means not provided, not zero; averages exclude n/a and state their coverage. Cross-platform totals sum only comparable metrics.</AlertDescription></Alert>

      <section aria-labelledby="top-h" className="space-y-2">
        <h2 id="top-h" className="text-lg font-semibold">Top posts{postPlatform ? ` · ${platformMeta(postPlatform).label}` : ""}{postData.coverage && <span className="ml-2 text-xs font-normal text-muted-foreground">{postData.coverage}</span>}</h2>
        {posts.isLoading ? <Skeleton className="h-40" /> : posts.error ? <QueryError error={posts.error} onRetry={() => posts.refetch()} notAvailableText="Post analytics aren't available yet." />
          : sortedPosts.length === 0 ? <EmptyState icon={BarChart3} title="No metrics yet." description="Metrics arrive after posts publish and analytics sync." action={canCreate ? { label: "Sync now", onClick: () => sync.mutate() } : undefined} />
          : (
            <div className="overflow-x-auto rounded-lg border">
              <Table>
                <TableHeader><TableRow><TableHead>Post</TableHead>{sortHead("published_at", "Published")}{sortHead("impressions", "Impr.")}{sortHead("engagements", "Eng.")}{sortHead("engagement_rate", "Eng. rate")}{sortHead("saves", "Saves")}{sortHead("clicks", "Clicks")}<TableHead>✦ Why</TableHead></TableRow></TableHeader>
                <TableBody>
                  {sortedPosts.map((p, i) => (
                    <TableRow key={p.id ?? p.published_post_id ?? i}>
                      <TableCell className="max-w-[260px]"><span className="flex items-center gap-1.5"><PlatformIcon platform={p.platform} size={16} />
                        {p.content_item_id ? <Link className="truncate hover:underline" href={ws(`studio/${p.content_item_id}`)}>{p.title ?? "Untitled"}</Link> : <span className="truncate">{p.title ?? "Untitled"}</span>}
                        {p.external_url && <a href={p.external_url} target="_blank" rel="noreferrer" aria-label="Open on platform"><ExternalLink className="h-3 w-3 text-muted-foreground" /></a>}</span></TableCell>
                      <TableCell className="whitespace-nowrap text-right text-sm text-muted-foreground">{fmtDate(p.published_at)}</TableCell>
                      {metricCell(p, "impressions")}{metricCell(p, "engagements")}{metricCell(p, "engagement_rate", true)}{metricCell(p, "saves")}{metricCell(p, "clicks")}
                      <TableCell className="max-w-[220px] text-xs text-muted-foreground">{p.why ?? "—"}</TableCell>
                    </TableRow>
                  ))}
                </TableBody>
              </Table>
            </div>
          )}
      </section>

      <section aria-labelledby="acc-h" className="space-y-2">
        <h2 id="acc-h" className="text-lg font-semibold">Account growth</h2>
        {accounts.isLoading ? <Skeleton className="h-24" /> : accounts.error ? <QueryError error={accounts.error} onRetry={() => accounts.refetch()} notAvailableText="Account analytics aren't available yet." />
          : accountRows.length === 0 ? <p className="text-sm text-muted-foreground">No account metrics yet.</p> : (
            <div className="overflow-x-auto rounded-lg border">
              <Table>
                <TableHeader><TableRow><TableHead>Account</TableHead><TableHead className="text-right">Followers</TableHead><TableHead className="text-right">Net change</TableHead><TableHead className="text-right">Impressions</TableHead><TableHead className="text-right">Reach</TableHead><TableHead>Last synced</TableHead></TableRow></TableHeader>
                <TableBody>
                  {accountRows.map((a, i) => (
                    <TableRow key={a.id ?? a.social_account_id ?? i}>
                      <TableCell><span className="flex items-center gap-1.5"><PlatformIcon platform={a.platform} size={16} />{a.display_name ?? platformMeta(a.platform).label}</span>{a.error && <span className="block text-[11px] text-destructive">{a.error} <Link className="underline" href={ws("settings/social-accounts")}>Fix</Link></span>}</TableCell>
                      <TableCell className="text-right tabular-nums">{fmtInt(a.followers)}</TableCell>
                      <TableCell className={cn("text-right tabular-nums", (a.followers_delta ?? 0) > 0 ? "text-success" : (a.followers_delta ?? 0) < 0 ? "text-destructive" : "")}>{a.followers_delta == null ? "n/a" : `${a.followers_delta > 0 ? "+" : ""}${fmtInt(a.followers_delta)}`}</TableCell>
                      <TableCell className="text-right tabular-nums">{fmtCompact(a.impressions)}</TableCell>
                      <TableCell className="text-right tabular-nums">{fmtCompact(a.reach)}</TableCell>
                      <TableCell className="text-sm text-muted-foreground">{relTime(a.last_synced_at)}</TableCell>
                    </TableRow>
                  ))}
                </TableBody>
              </Table>
            </div>
          )}
      </section>

      <section aria-labelledby="ins-h" className="space-y-2">
        <h2 id="ins-h" className="flex items-center gap-2 text-lg font-semibold"><Sparkles className="h-4 w-4 text-ai" /> Insights</h2>
        {insights.isLoading ? <Skeleton className="h-24" /> : insights.error ? <QueryError error={insights.error} onRetry={() => insights.refetch()} notAvailableText="Insights appear after the performance analyst runs (weekly, or press Analyze)." /> : (
          <div className="grid gap-4 lg:grid-cols-2">
            <div className="space-y-2">
              {insightList.length === 0 && <p className="text-sm text-muted-foreground">No insights yet.</p>}
              {insightList.map((i) => (
                <Card key={i.id} className="gap-1 py-3"><CardContent className="px-4 text-sm">
                  <p className="font-medium">{i.statement}</p>
                  <p className="mt-1 text-[11px] text-muted-foreground">{i.kind}{i.n != null ? ` · n=${i.n}` : ""}{i.confidence != null ? ` · ${i.confidence} confidence` : ""}{i.directional ? " · early signal" : ""}{i.period_start ? ` · ${fmtDate(i.period_start)}–${fmtDate(i.period_end)}` : ""}{(i.excluded_platforms ?? []).length ? ` · excludes ${i.excluded_platforms?.join(", ")}` : ""}
                    {i.ai_run_id && <> · <Link className="hover:underline" href={ws(`command-center/${i.ai_run_id}`)}>run ↗</Link></>}</p>
                </CardContent></Card>
              ))}
            </div>
            <div><h3 className="mb-2 text-sm font-medium">Recommendations</h3><RecommendationList brandId={brandId} recommendations={recommendations} insights={insightList} /></div>
          </div>
        )}
      </section>
    </div>
  );
}

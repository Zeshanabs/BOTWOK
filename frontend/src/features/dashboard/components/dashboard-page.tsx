"use client";
import { useState } from "react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { useQuery } from "@tanstack/react-query";
import { AlertTriangle, ArrowRight, Bot, CalendarDays, CheckSquare, Lightbulb, PauseCircle, PenSquare, Search, Sparkles, XCircle } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Card, CardAction, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { Skeleton } from "@/components/ui/skeleton";
import { PlatformIcon } from "@/components/data/platform-icon";
import { StatusChip } from "@/components/data/status-chip";
import { CostPill } from "@/features/common/components/ai-badge";
import { runTitle } from "@/features/common/components/run-card";
import { QueryError, SkeletonRows } from "@/features/common/components/query-state";
import { useActiveBrand, usePermissions, useSocialAccounts, useWorkspacePath } from "@/features/common/hooks";
import type { AiRun, ListResponse } from "@/features/common/types";
import { addDays, dayKey, dayStartIso, keyLabel, timeLabel } from "@/features/common/tz";
import { isNotAvailable, relTime, toItems, truncate } from "@/features/common/utils";
import { analyticsApi, normalizeOverview, periodRange, pickKpis } from "@/features/analytics/api";
import { KpiCard, KpiSkeleton } from "@/features/analytics/components/kpi-card";
import { RecommendationsWidget } from "@/features/analytics/components/recommendations";
import { approvalsApi, approvalTitle } from "@/features/approvals/api";
import { calendarApi, cardTime, normalizeCalendar } from "@/features/calendar/api";
import { publishingApi } from "@/features/publishing/api";
import { accountHealth, AccountHealthStrip } from "@/features/publishing/components/account-health";
import { api, qs } from "@/lib/api";
import { cn } from "@/lib/utils";

/** GET /ai/usage: {totals:{cost_usd}, budgets:[{kind, period, limit, spent, hard, ratio}]}. */
interface Usage { totals?: { cost_usd?: number | null } | null; budgets?: { kind?: string; period?: string; limit?: number | null; spent?: number | null; ratio?: number | null; hard?: boolean }[] }

/** Dashboard (doc 24 §5): KPIs, what to do next, next 7 days, approvals, AI runs, account health, quick actions — each widget loads independently. */
export function DashboardPage() {
  const router = useRouter();
  const ws = useWorkspacePath();
  const { brandId, brand, timezone } = useActiveBrand();
  const { canCreate, canApprove } = usePermissions();
  const [days, setDays] = useState("7");
  const range = periodRange(Number(days), new Date());
  const today = dayKey(new Date(), timezone);

  const overview = useQuery({ queryKey: ["analytics", "overview", { brand_id: brandId, ...range, compare: "previous", dash: true }], queryFn: () => analyticsApi.overview({ brand_id: brandId, ...range, compare: "previous" }), enabled: !!brandId, retry: false });
  const accounts = useSocialAccounts(brandId);
  const calQuery = { from: dayStartIso(today, timezone), to: dayStartIso(addDays(today, 7), timezone), view: "list" as const, brand_id: brandId, tz: timezone, tray: false };
  const upcoming = useQuery({ queryKey: ["calendar", calQuery], queryFn: () => calendarApi.get(calQuery), enabled: !!brandId, retry: false });
  const approvals = useQuery({ queryKey: ["approvals", "list", "pending", "dash", brandId], queryFn: () => approvalsApi.list({ status: "pending", brand_id: brandId }), retry: false });
  const failed = useQuery({ queryKey: ["publishing", "queue", { status: "failed", brand_id: brandId }], queryFn: () => publishingApi.queue({ status: "failed", brand_id: brandId }), retry: false });
  const runs = useQuery({ queryKey: ["ai", "runs", "recent"], queryFn: () => api.get<ListResponse<AiRun>>(`/ai/runs${qs({ limit: 5 })}`), retry: false, refetchInterval: 15_000 });
  const usage = useQuery({ queryKey: ["ai", "usage", "month"], queryFn: () => api.get<Usage>("/ai/usage"), retry: false, staleTime: 60_000 });

  const kpis = normalizeOverview(overview.data);
  const [impr, eng, foll, posts] = pickKpis(kpis, [["impressions", "reach", "views"], ["engagement", "engagements", "engagement_rate"], ["followers_delta", "followers", "followers_net"], ["posts_published", "posts", "published"]]);
  const accountList = toItems(accounts.data);
  const noAccounts = accounts.isSuccess && accountList.length === 0;
  const pendingCount = toItems(approvals.data).length;
  const failedCount = toItems(failed.data).length;
  const broken = accountList.filter((a) => { const h = accountHealth(a); return h.tone === "bad" || (h.tone === "warn" && /expire/.test(h.label)); });
  const topBudget = [...(usage.data?.budgets ?? [])].filter((b) => b.limit).sort((a, b) => (b.ratio ?? 0) - (a.ratio ?? 0))[0];
  const spent = topBudget?.spent ?? usage.data?.totals?.cost_usd ?? null;
  const limit = topBudget?.limit ?? null;
  const budgetPct = topBudget?.ratio != null ? topBudget.ratio * 100 : spent != null && limit ? (spent / limit) * 100 : null;
  const { cards } = normalizeCalendar(upcoming.data);
  const agenda = [...cards].filter((c) => cardTime(c)).sort((a, b) => ((cardTime(a) ?? "") < (cardTime(b) ?? "") ? -1 : 1));
  const attentionLoading = approvals.isLoading || failed.isLoading || accounts.isLoading;
  const attention: { icon: typeof PauseCircle; tone: string; text: string; action: string; href: string }[] = [];
  if (pendingCount) attention.push({ icon: PauseCircle, tone: "text-amber-600", text: `${pendingCount} item${pendingCount === 1 ? "" : "s"} awaiting ${canApprove ? "your" : ""} approval`, action: "Review", href: ws("approvals") });
  if (failedCount) attention.push({ icon: XCircle, tone: "text-red-600", text: `${failedCount} post${failedCount === 1 ? "" : "s"} failed to publish`, action: "Fix", href: ws("publishing?status=failed") });
  broken.forEach((a) => attention.push({ icon: AlertTriangle, tone: "text-amber-600", text: `${a.display_name}: ${accountHealth(a).label}`, action: "Reconnect", href: ws("settings/social-accounts") }));
  if (budgetPct != null && budgetPct >= 80) attention.push({ icon: AlertTriangle, tone: budgetPct >= 100 ? "text-red-600" : "text-amber-600", text: `AI budget at ${Math.round(budgetPct)}% this month`, action: "View", href: ws("settings/ai") });

  return (
    <div className="space-y-6">
      <div className="flex flex-col gap-3 sm:flex-row sm:items-center">
        <div className="flex-1">
          <h1 className="text-2xl font-semibold tracking-tight">Dashboard{brand ? ` · ${brand.name}` : ""}</h1>
          <p className="text-sm text-muted-foreground">What needs action, what goes out next, how content performs.</p>
        </div>
        <Select value={days} onValueChange={setDays}><SelectTrigger size="sm" className="w-40" aria-label="Period"><SelectValue /></SelectTrigger>
          <SelectContent><SelectItem value="7">Last 7 days</SelectItem><SelectItem value="30">Last 30 days</SelectItem><SelectItem value="90">Last 90 days</SelectItem></SelectContent></Select>
      </div>

      {/* Quick actions */}
      <div className="flex flex-wrap gap-2">
        {canCreate && <Button size="sm" onClick={() => router.push(ws("studio?new=1"))}><PenSquare /> New post</Button>}
        {canCreate && <Button size="sm" variant="outline" onClick={() => router.push(ws(`command-center?prompt=${encodeURIComponent(`Research what's new this week in ${brand?.name ? `${brand.name}'s industry` : "our industry"} and summarize with sources`)}`))}><Search /> Run research</Button>}
        {canCreate && <Button size="sm" variant="outline" onClick={() => router.push(ws("ideas"))}><Lightbulb /> Generate ideas</Button>}
        <Button size="sm" variant="ghost" onClick={() => router.push(ws("calendar"))}><CalendarDays /> Calendar</Button>
      </div>

      <div className="grid gap-4 lg:grid-cols-3">
        {/* KPIs */}
        <section aria-label="Key metrics" className="order-3 lg:order-1 lg:col-span-3">
          {!brandId ? <p className="text-sm text-muted-foreground">Select a brand to see metrics.</p>
            : overview.error && !isNotAvailable(overview.error) ? <QueryError error={overview.error} onRetry={() => overview.refetch()} title="Couldn't load metrics" />
            : (
              <div className="grid grid-cols-2 gap-3 lg:grid-cols-4">
                {overview.isLoading ? Array.from({ length: 4 }).map((_, i) => <KpiSkeleton key={i} />) : (
                  <>
                    <KpiCard kpi={noAccounts ? null : impr} label={impr?.label ?? "Impressions"} emptyAction={noAccounts ? { href: ws("settings/social-accounts"), label: "Connect" } : undefined} />
                    <KpiCard kpi={noAccounts ? null : eng} label={eng?.label ?? "Engagement"} />
                    <KpiCard kpi={noAccounts ? null : foll} label="Followers (net)" />
                    <KpiCard kpi={noAccounts ? null : posts} label="Published" />
                  </>
                )}
              </div>
            )}
          {isNotAvailable(overview.error) && <p className="mt-2 text-xs text-muted-foreground">Analytics isn’t available yet — KPIs appear after accounts sync.</p>}
          {overview.data?.last_synced_at && <p className="mt-1 text-[11px] text-muted-foreground">Metrics last synced {relTime(overview.data.last_synced_at)} · n/a = not provided by the platform, never zero.</p>}
        </section>

        {/* What to do next */}
        <Card className="order-1 gap-3 lg:order-2 lg:col-span-2">
          <CardHeader><CardTitle className="text-base">What to do next</CardTitle></CardHeader>
          <CardContent className="space-y-4">
            {attentionLoading ? <SkeletonRows rows={2} /> : attention.length === 0 ? <p className="text-sm text-muted-foreground">Nothing urgent right now.</p> : (
              <ul className="space-y-2" aria-label="Needs your attention">
                {attention.map((a, i) => (
                  <li key={i} className="flex items-center gap-2 text-sm"><a.icon className={cn("h-4 w-4 shrink-0", a.tone)} aria-hidden /><span className="flex-1">{a.text}</span><Button asChild size="xs" variant="outline"><Link href={a.href}>{a.action}</Link></Button></li>
                ))}
              </ul>
            )}
            <div>
              <p className="mb-2 flex items-center gap-1 text-xs font-semibold uppercase tracking-wide text-muted-foreground"><Sparkles className="h-3.5 w-3.5 text-ai" /> AI recommendations · performance_analyst</p>
              <RecommendationsWidget brandId={brandId} limit={3} />
            </div>
          </CardContent>
        </Card>

        {/* Next 7 days */}
        <Card className="order-2 gap-3 lg:order-3">
          <CardHeader><CardTitle className="text-base">Next 7 days</CardTitle><CardAction><Link className="text-xs text-primary hover:underline" href={ws("calendar")}>Calendar <ArrowRight className="inline h-3 w-3" /></Link></CardAction></CardHeader>
          <CardContent>
            {!brandId ? <p className="text-sm text-muted-foreground">Select a brand.</p>
              : upcoming.isLoading ? <SkeletonRows rows={4} />
              : upcoming.error ? <QueryError error={upcoming.error} onRetry={() => upcoming.refetch()} notAvailableText="The calendar isn't available yet." />
              : agenda.length === 0 ? <div className="text-sm text-muted-foreground">Nothing planned.{canCreate && <> <Link className="text-primary hover:underline" href={ws("calendar")}>Plan something</Link></>}</div>
              : (
                <ul className="space-y-1.5">
                  {agenda.slice(0, 6).map((c) => {
                    const t = cardTime(c) as string;
                    const k = dayKey(new Date(t), timezone);
                    return (
                      <li key={c.scheduled_post_id ?? c.id}>
                        <Link href={ws(`studio/${c.content_item_id}`)} className="flex items-center gap-2 rounded px-1 py-0.5 text-sm hover:bg-accent">
                          <span className="w-16 shrink-0 text-xs text-muted-foreground">{k === today ? "Today" : keyLabel(k, { weekday: "short" })} {timeLabel(t, timezone)}</span>
                          {c.platform && <PlatformIcon platform={c.platform} size={16} />}
                          <span className="min-w-0 flex-1 truncate">{truncate(c.title, 40)}</span>
                          <StatusChip status={c.status} className="shrink-0" />
                        </Link>
                      </li>
                    );
                  })}
                  {agenda.length > 6 && <li><Link className="text-xs text-muted-foreground hover:underline" href={ws("calendar?view=list")}>+ {agenda.length - 6} more</Link></li>}
                </ul>
              )}
          </CardContent>
        </Card>

        {/* Approvals */}
        <Card className="order-4 gap-3">
          <CardHeader><CardTitle className="flex items-center gap-2 text-base"><CheckSquare className="h-4 w-4" /> Pending approvals</CardTitle>{pendingCount > 0 && <CardAction><span className="rounded-full bg-amber-100 px-2 py-0.5 text-xs font-semibold text-amber-800 dark:bg-amber-900/50 dark:text-amber-200">{pendingCount}</span></CardAction>}</CardHeader>
          <CardContent>
            {approvals.isLoading ? <SkeletonRows rows={3} /> : approvals.error ? <QueryError error={approvals.error} onRetry={() => approvals.refetch()} notAvailableText="Approvals aren't available yet." />
              : pendingCount === 0 ? <p className="text-sm text-muted-foreground">Nothing waiting.</p> : (
                <>
                  <ul className="space-y-1 text-sm">{toItems(approvals.data).slice(0, 3).map((a) => <li key={a.id} className="truncate">• {approvalTitle(a)} <span className="text-xs text-muted-foreground">{relTime(a.created_at)}</span></li>)}</ul>
                  <Button asChild size="sm" className="mt-3" variant={canApprove ? "default" : "outline"}><Link href={ws("approvals")}>{canApprove ? "Review" : "View"}</Link></Button>
                </>
              )}
          </CardContent>
        </Card>

        {/* Recent AI runs */}
        <Card className="order-5 gap-3">
          <CardHeader><CardTitle className="flex items-center gap-2 text-base"><Bot className="h-4 w-4 text-ai" /> Recent AI runs</CardTitle><CardAction><Link className="text-xs text-primary hover:underline" href={ws("command-center")}>All <ArrowRight className="inline h-3 w-3" /></Link></CardAction></CardHeader>
          <CardContent>
            {runs.isLoading ? <SkeletonRows rows={3} /> : runs.error ? <QueryError error={runs.error} onRetry={() => runs.refetch()} notAvailableText="The AI run log isn't available yet." />
              : toItems(runs.data).length === 0 ? <p className="text-sm text-muted-foreground">No runs yet.</p> : (
                <ul className="space-y-1.5">
                  {toItems(runs.data).slice(0, 5).map((r) => (
                    <li key={r.id}><Link href={ws(`command-center/${r.id}`)} className="flex items-center gap-2 rounded px-1 py-0.5 text-sm hover:bg-accent">
                      <span className="min-w-0 flex-1 truncate">{runTitle(r)}</span>
                      <StatusChip status={String(r.status)} className="shrink-0" /><CostPill usd={r.cost_usd} />
                    </Link></li>
                  ))}
                </ul>
              )}
            {budgetPct != null && <p className="mt-2 text-[11px] text-muted-foreground">This month ${Number(spent).toFixed(2)} of ${Number(limit).toFixed(2)} ({Math.round(budgetPct)}%)</p>}
          </CardContent>
        </Card>

        {/* Accounts */}
        <Card className="order-6 gap-3">
          <CardHeader><CardTitle className="text-base">Connected accounts</CardTitle><CardAction><Link className="text-xs text-primary hover:underline" href={ws("settings/social-accounts")}>Manage</Link></CardAction></CardHeader>
          <CardContent>{accounts.isLoading ? <Skeleton className="h-16" /> : <AccountHealthStrip brandId={brandId} compact />}</CardContent>
        </Card>
      </div>
    </div>
  );
}

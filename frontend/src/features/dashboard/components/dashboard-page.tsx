"use client";
import { useState } from "react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { useQuery } from "@tanstack/react-query";
import { AlertTriangle, ArrowRight, Bot, CalendarDays, CheckCircle2, CheckSquare, ChevronRight, Lightbulb, Palette, PauseCircle, PenSquare, Search, Share2, Sparkles, XCircle } from "lucide-react";
import type { LucideIcon } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Card, CardAction, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { Skeleton } from "@/components/ui/skeleton";
import { PlatformIcon } from "@/components/shared/platform-icon";
import { StatusChip } from "@/components/shared/status-chip";
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
import { useSession } from "@/stores/session";

/** GET /ai/usage: {totals:{cost_usd}, budgets:[{kind, period, limit, spent, hard, ratio}]}. */
interface Usage { totals?: { cost_usd?: number | null } | null; budgets?: { kind?: string; period?: string; limit?: number | null; spent?: number | null; ratio?: number | null; hard?: boolean }[] }

function greeting(): string {
  const h = new Date().getHours();
  return h < 5 ? "Working late" : h < 12 ? "Good morning" : h < 18 ? "Good afternoon" : "Good evening";
}

/** Big, inviting entry points for the most common jobs. */
function ActionTile({ icon: Icon, title, hint, onClick, tone = "primary" }: { icon: LucideIcon; title: string; hint: string; onClick: () => void; tone?: "primary" | "ai" }) {
  return (
    <button
      type="button"
      onClick={onClick}
      className="card-interactive group flex items-center gap-3 rounded-xl border bg-card px-3.5 py-3 text-left shadow-card focus-visible:outline-none focus-visible:ring-[3px] focus-visible:ring-ring/50"
    >
      <span className={cn("flex h-9 w-9 shrink-0 items-center justify-center rounded-lg", tone === "ai" ? "bg-ai/12 text-ai" : "bg-primary/10 text-primary")}><Icon className="h-4 w-4" /></span>
      <span className="min-w-0 flex-1">
        <span className="block truncate text-sm font-semibold">{title}</span>
        <span className="block truncate text-xs text-muted-foreground">{hint}</span>
      </span>
      <ChevronRight className="h-4 w-4 shrink-0 text-muted-foreground/50 transition-transform group-hover:translate-x-0.5 group-hover:text-foreground" aria-hidden />
    </button>
  );
}

function SectionTitle({ icon: Icon, children, tone }: { icon?: LucideIcon; children: React.ReactNode; tone?: "ai" }) {
  return (
    <CardTitle className="flex items-center gap-2 text-[15px] font-semibold">
      {Icon && <span className={cn("flex h-6 w-6 items-center justify-center rounded-md", tone === "ai" ? "bg-ai/12 text-ai" : "bg-muted text-muted-foreground")}><Icon className="h-3.5 w-3.5" /></span>}
      {children}
    </CardTitle>
  );
}

/** Dashboard (doc 24 §5): KPIs, what to do next, next 7 days, approvals, AI runs, account health, quick actions — each widget loads independently. */
export function DashboardPage() {
  const router = useRouter();
  const ws = useWorkspacePath();
  const user = useSession((s) => s.user);
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
  const attention: { icon: typeof PauseCircle; tone: "warning" | "danger"; text: string; action: string; href: string }[] = [];
  if (pendingCount) attention.push({ icon: PauseCircle, tone: "warning", text: `${pendingCount} item${pendingCount === 1 ? "" : "s"} awaiting ${canApprove ? "your " : ""}approval`, action: "Review", href: ws("approvals") });
  if (failedCount) attention.push({ icon: XCircle, tone: "danger", text: `${failedCount} post${failedCount === 1 ? "" : "s"} failed to publish`, action: "Fix", href: ws("publishing?status=failed") });
  broken.forEach((a) => attention.push({ icon: AlertTriangle, tone: "warning", text: `${a.display_name}: ${accountHealth(a).label}`, action: "Reconnect", href: ws("settings/social-accounts") }));
  if (budgetPct != null && budgetPct >= 80) attention.push({ icon: AlertTriangle, tone: budgetPct >= 100 ? "danger" : "warning", text: `AI budget at ${Math.round(budgetPct)}% this month`, action: "View", href: ws("settings/ai") });
  const firstName = user?.full_name?.split(/\s+/)[0];
  const runCount = toItems(runs.data).length;

  return (
    <div className="space-y-6">
      <header className="flex flex-col gap-3 sm:flex-row sm:items-end sm:justify-between">
        <div className="min-w-0">
          <p className="text-[11px] font-semibold uppercase tracking-[0.12em] text-muted-foreground">{brand ? brand.name : "Dashboard"} · {keyLabel(today, { weekday: "long", month: "long", day: "numeric" })}</p>
          <h1 className="mt-1 font-display text-2xl font-bold tracking-tight sm:text-[28px]">{greeting()}{firstName ? `, ${firstName}` : ""}.</h1>
          <p className="mt-1 text-sm text-muted-foreground">What needs action, what goes out next, how content performs.</p>
        </div>
        <Select value={days} onValueChange={setDays}>
          <SelectTrigger size="sm" className="w-40 bg-card" aria-label="Period"><SelectValue /></SelectTrigger>
          <SelectContent><SelectItem value="7">Last 7 days</SelectItem><SelectItem value="30">Last 30 days</SelectItem><SelectItem value="90">Last 90 days</SelectItem></SelectContent>
        </Select>
      </header>

      {/* Quick actions */}
      {canCreate && (
        <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-4" aria-label="Quick actions">
          <ActionTile icon={PenSquare} title="New post" hint="Draft from scratch or a prompt" onClick={() => router.push(ws("studio?new=1"))} />
          <ActionTile icon={Search} title="Run research" hint="Web and news with sources" tone="ai" onClick={() => router.push(ws(`command-center?prompt=${encodeURIComponent(`Research what's new this week in ${brand?.name ? `${brand.name}'s industry` : "our industry"} and summarize with sources`)}`))} />
          <ActionTile icon={Lightbulb} title="Generate ideas" hint="Angles from strategy and trends" tone="ai" onClick={() => router.push(ws("ideas"))} />
          <ActionTile icon={CalendarDays} title="Open calendar" hint="Plan and schedule the week" onClick={() => router.push(ws("calendar"))} />
        </div>
      )}

      {/* Setup checklist for a fresh brand */}
      {noAccounts && (
        <Card className="gap-3 border-primary/20 bg-primary/[0.04] py-5 shadow-none">
          <CardHeader><SectionTitle icon={CheckCircle2}>Finish setting up {brand?.name ?? "this brand"}</SectionTitle></CardHeader>
          <CardContent className="grid gap-2 sm:grid-cols-3">
            {[
              { icon: Share2, title: "Connect a social account", hint: "Metrics and publishing need one", href: ws("settings/social-accounts") },
              { icon: Palette, title: "Describe the brand voice", hint: "Pillars, tone and audience guide every draft", href: ws("settings/brand") },
              { icon: Bot, title: "Run your first AI job", hint: "Research the industry with sources", href: ws("command-center") },
            ].map((s) => (
              <Link key={s.title} href={s.href} className="card-interactive flex items-start gap-3 rounded-lg border bg-card p-3 text-sm">
                <s.icon className="mt-0.5 h-4 w-4 shrink-0 text-primary" aria-hidden />
                <span><span className="block font-medium">{s.title}</span><span className="block text-xs text-muted-foreground">{s.hint}</span></span>
              </Link>
            ))}
          </CardContent>
        </Card>
      )}

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
          {overview.data?.last_synced_at && <p className="mt-1.5 text-[11px] text-muted-foreground">Metrics last synced {relTime(overview.data.last_synced_at)} · n/a = not provided by the platform, never zero.</p>}
        </section>

        {/* What to do next */}
        <Card className="order-1 gap-3 lg:order-2 lg:col-span-2">
          <CardHeader><SectionTitle icon={Sparkles} tone="ai">What to do next</SectionTitle></CardHeader>
          <CardContent className="space-y-5">
            {attentionLoading ? <SkeletonRows rows={2} /> : attention.length === 0 ? (
              <p className="flex items-center gap-2 text-sm text-muted-foreground"><CheckCircle2 className="h-4 w-4 text-success" aria-hidden /> Nothing urgent right now.</p>
            ) : (
              <ul className="space-y-1.5" aria-label="Needs your attention">
                {attention.map((a, i) => (
                  <li key={i} className={cn("flex items-center gap-3 rounded-lg border px-3 py-2 text-sm", a.tone === "danger" ? "border-destructive/25 bg-destructive/[0.04]" : "border-warning/30 bg-warning/[0.06]")}>
                    <a.icon className={cn("h-4 w-4 shrink-0", a.tone === "danger" ? "text-destructive" : "text-warning")} aria-hidden />
                    <span className="flex-1">{a.text}</span>
                    <Button asChild size="xs" variant="outline" className="bg-card"><Link href={a.href}>{a.action}</Link></Button>
                  </li>
                ))}
              </ul>
            )}
            <div>
              <p className="mb-2 flex items-center gap-1.5 text-[11px] font-semibold uppercase tracking-[0.12em] text-muted-foreground"><Sparkles className="h-3 w-3 text-ai" /> AI recommendations <span className="font-mono normal-case tracking-normal text-muted-foreground/70">performance_analyst</span></p>
              <RecommendationsWidget brandId={brandId} limit={3} />
            </div>
          </CardContent>
        </Card>

        {/* Next 7 days */}
        <Card className="order-2 gap-3 lg:order-3">
          <CardHeader><SectionTitle icon={CalendarDays}>Next 7 days</SectionTitle><CardAction><Link className="inline-flex items-center gap-1 text-xs font-medium text-primary hover:underline" href={ws("calendar")}>Calendar <ArrowRight className="h-3 w-3" /></Link></CardAction></CardHeader>
          <CardContent>
            {!brandId ? <p className="text-sm text-muted-foreground">Select a brand.</p>
              : upcoming.isLoading ? <SkeletonRows rows={4} />
              : upcoming.error ? <QueryError error={upcoming.error} onRetry={() => upcoming.refetch()} notAvailableText="The calendar isn't available yet." />
              : agenda.length === 0 ? <div className="text-sm text-muted-foreground">Nothing planned.{canCreate && <> <Link className="font-medium text-primary hover:underline" href={ws("calendar")}>Plan something</Link></>}</div>
              : (
                <ul className="-mx-2 space-y-0.5">
                  {agenda.slice(0, 6).map((c) => {
                    const t = cardTime(c) as string;
                    const k = dayKey(new Date(t), timezone);
                    return (
                      <li key={c.scheduled_post_id ?? c.id}>
                        <Link href={ws(`studio/${c.content_item_id}`)} className="flex items-center gap-2.5 rounded-lg px-2 py-1.5 text-sm hover:bg-accent">
                          <span className="w-[4.5rem] shrink-0 text-xs tabular-nums text-muted-foreground">{k === today ? "Today" : keyLabel(k, { weekday: "short" })} {timeLabel(t, timezone)}</span>
                          {c.platform && <PlatformIcon platform={c.platform} size={16} />}
                          <span className="min-w-0 flex-1 truncate">{truncate(c.title, 40)}</span>
                          <StatusChip status={c.status} className="shrink-0" />
                        </Link>
                      </li>
                    );
                  })}
                  {agenda.length > 6 && <li className="px-2"><Link className="text-xs text-muted-foreground hover:underline" href={ws("calendar?view=list")}>+ {agenda.length - 6} more</Link></li>}
                </ul>
              )}
          </CardContent>
        </Card>

        {/* Approvals */}
        <Card className="order-4 gap-3">
          <CardHeader><SectionTitle icon={CheckSquare}>Pending approvals</SectionTitle>{pendingCount > 0 && <CardAction><span className="rounded-full bg-warning/15 px-2 py-0.5 text-xs font-semibold tabular-nums text-warning">{pendingCount}</span></CardAction>}</CardHeader>
          <CardContent>
            {approvals.isLoading ? <SkeletonRows rows={3} /> : approvals.error ? <QueryError error={approvals.error} onRetry={() => approvals.refetch()} notAvailableText="Approvals aren't available yet." />
              : pendingCount === 0 ? <p className="text-sm text-muted-foreground">Nothing waiting.</p> : (
                <>
                  <ul className="space-y-1.5 text-sm">{toItems(approvals.data).slice(0, 3).map((a) => <li key={a.id} className="flex items-baseline gap-2"><span className="h-1.5 w-1.5 shrink-0 translate-y-[-2px] rounded-full bg-warning" aria-hidden /><span className="min-w-0 flex-1 truncate">{approvalTitle(a)}</span><span className="shrink-0 text-xs text-muted-foreground">{relTime(a.created_at)}</span></li>)}</ul>
                  <Button asChild size="sm" className="mt-3" variant={canApprove ? "default" : "outline"}><Link href={ws("approvals")}>{canApprove ? "Review" : "View"} <ArrowRight /></Link></Button>
                </>
              )}
          </CardContent>
        </Card>

        {/* Recent AI runs */}
        <Card className="order-5 gap-3">
          <CardHeader><SectionTitle icon={Bot} tone="ai">Recent AI runs</SectionTitle><CardAction><Link className="inline-flex items-center gap-1 text-xs font-medium text-primary hover:underline" href={ws("command-center")}>All <ArrowRight className="h-3 w-3" /></Link></CardAction></CardHeader>
          <CardContent>
            {runs.isLoading ? <SkeletonRows rows={3} /> : runs.error ? <QueryError error={runs.error} onRetry={() => runs.refetch()} notAvailableText="The AI run log isn't available yet." />
              : runCount === 0 ? <p className="text-sm text-muted-foreground">No runs yet. <Link className="font-medium text-primary hover:underline" href={ws("command-center")}>Start one</Link></p> : (
                <ul className="-mx-2 space-y-0.5">
                  {toItems(runs.data).slice(0, 5).map((r) => (
                    <li key={r.id}><Link href={ws(`command-center/${r.id}`)} className="flex items-center gap-2 rounded-lg px-2 py-1.5 text-sm hover:bg-accent">
                      <span className="min-w-0 flex-1 truncate">{runTitle(r)}</span>
                      <StatusChip status={String(r.status)} className="shrink-0" /><CostPill usd={r.cost_usd} />
                    </Link></li>
                  ))}
                </ul>
              )}
            {budgetPct != null && (
              <div className="mt-3">
                <div className="flex items-center justify-between text-[11px] text-muted-foreground"><span>AI budget this month</span><span className="tabular-nums">${Number(spent).toFixed(2)} / ${Number(limit).toFixed(2)}</span></div>
                <div className="mt-1 h-1.5 overflow-hidden rounded-full bg-muted" role="progressbar" aria-valuenow={Math.round(budgetPct)} aria-valuemin={0} aria-valuemax={100}>
                  <div className={cn("h-full rounded-full", budgetPct >= 100 ? "bg-destructive" : budgetPct >= 80 ? "bg-warning" : "bg-primary")} style={{ width: `${Math.min(100, budgetPct)}%` }} />
                </div>
              </div>
            )}
          </CardContent>
        </Card>

        {/* Accounts */}
        <Card className="order-6 gap-3">
          <CardHeader><SectionTitle icon={Share2}>Connected accounts</SectionTitle><CardAction><Link className="text-xs font-medium text-primary hover:underline" href={ws("settings/social-accounts")}>Manage</Link></CardAction></CardHeader>
          <CardContent>{accounts.isLoading ? <Skeleton className="h-16" /> : <AccountHealthStrip brandId={brandId} compact />}</CardContent>
        </Card>
      </div>
    </div>
  );
}

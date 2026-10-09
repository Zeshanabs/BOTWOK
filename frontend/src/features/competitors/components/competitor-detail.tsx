"use client";
import { useState } from "react";
import Link from "next/link";
import { usePathname, useRouter, useSearchParams } from "next/navigation";
import { toast } from "sonner";
import { ArrowLeft, ExternalLink, MoreHorizontal, RefreshCw, Sparkles, Trash2 } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Card, CardContent } from "@/components/ui/card";
import { DropdownMenu, DropdownMenuContent, DropdownMenuItem, DropdownMenuTrigger } from "@/components/ui/dropdown-menu";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { Skeleton } from "@/components/ui/skeleton";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { PlatformIcon } from "@/components/shared/platform-icon";
import { AvailabilityBadge } from "@/components/shared/availability-badge";
import { ConfirmDialog } from "@/components/shared/confirm-dialog";
import { QueryError, errorMessage } from "@/components/shared/async-states";
import { domainOf, fmtCompact, fmtRelative } from "@/lib/formatters";
import { platformMeta } from "@/lib/platforms";
import { useCan } from "@/lib/permissions";
import { useSession } from "@/stores/session";
import { useCompetitor, useCompetitorMutations } from "../hooks";
import { GapsTab, PillarsHooksTab, VisualToneTab } from "./analysis-tabs";
import { OverviewTab } from "./overview-tab";
import { PostsTab } from "./posts-tab";
import { GenerateReportDialog, ReportsTab } from "./reports-tab";
import { CompetitorSourcesTab } from "./sources-tab";
import { SyncBadge } from "./sync-badge";

const TABS = [
  { id: "overview", label: "Overview" }, { id: "posts", label: "Posts" }, { id: "pillars", label: "Pillars & Hooks" }, { id: "visual", label: "Visual & Tone" },
  { id: "website", label: "Website & Blog" }, { id: "news", label: "News" }, { id: "gaps", label: "Gaps & Opportunities" }, { id: "reports", label: "Reports" },
];

export function CompetitorDetail({ id }: { id: string }) {
  const router = useRouter();
  const pathname = usePathname();
  const sp = useSearchParams();
  const slug = useSession((s) => s.workspaceSlug);
  const can = useCan();
  const q = useCompetitor(id);
  const { sync, remove } = useCompetitorMutations();
  const [reportOpen, setReportOpen] = useState(false);
  const [deleting, setDeleting] = useState(false);
  const tab = sp.get("tab") ?? "overview";
  const setTab = (t: string) => router.replace(`${pathname}?tab=${t}`);
  const base = `/w/${slug}/competitors`;

  if (q.isLoading) return <div className="space-y-4"><Skeleton className="h-8 w-64" /><div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">{Array.from({ length: 4 }).map((_, i) => <Skeleton key={i} className="h-28" />)}</div><Skeleton className="h-64" /></div>;
  if (q.error || !q.data) return <QueryError error={q.error} onRetry={() => q.refetch()} title="Couldn't load this competitor" notFoundText="This competitor doesn't exist or was deleted." />;
  const c = q.data;
  const profiles = c.profiles ?? [];
  const openReport = () => { setTab("reports"); setReportOpen(true); };

  return (
    <div className="space-y-6">
      <div className="flex flex-col gap-3 sm:flex-row sm:items-start sm:justify-between">
        <div>
          <Link href={base} className="inline-flex items-center gap-1 text-xs text-muted-foreground hover:text-foreground"><ArrowLeft className="h-3 w-3" /> Competitors</Link>
          <h1 className="text-2xl font-semibold tracking-tight">{c.name}</h1>
          <div className="mt-1 flex flex-wrap items-center gap-3 text-sm text-muted-foreground">
            {c.website && <a href={c.website} target="_blank" rel="noreferrer noopener" className="inline-flex items-center gap-1 hover:underline">{domainOf(c.website)} <ExternalLink className="h-3 w-3" /></a>}
            <SyncBadge competitor={c} />
          </div>
        </div>
        <div className="flex flex-wrap gap-2">
          {can.create && <Button variant="outline" size="sm" disabled={sync.isPending} onClick={() => sync.mutate(c.id, { onSuccess: () => toast.success("Sync started"), onError: (e) => toast.error(errorMessage(e)) })}><RefreshCw className="h-3 w-3" /> Sync now</Button>}
          <Button variant="outline" size="sm" asChild><Link href={`${base}/compare?ids=${c.id}`}>Compare</Link></Button>
          {can.create && <Button size="sm" onClick={openReport}><Sparkles className="h-3 w-3" /> Report</Button>}
          {can.create && (
            <DropdownMenu>
              <DropdownMenuTrigger asChild><Button variant="ghost" size="icon-sm" aria-label="More actions"><MoreHorizontal className="h-4 w-4" /></Button></DropdownMenuTrigger>
              <DropdownMenuContent align="end"><DropdownMenuItem className="text-destructive" onClick={() => setDeleting(true)}><Trash2 className="mr-2 h-4 w-4" /> Delete</DropdownMenuItem></DropdownMenuContent>
            </DropdownMenu>
          )}
        </div>
      </div>

      <div className="-mx-4 flex snap-x gap-3 overflow-x-auto px-4 pb-1 sm:mx-0 sm:grid sm:grid-cols-2 sm:overflow-visible sm:px-0 lg:grid-cols-4">
        {profiles.length ? profiles.map((p) => (
          <Card key={p.id} className="min-w-[220px] snap-start gap-2 py-4">
            <CardContent className="space-y-1.5 px-4 text-sm">
              <div className="flex items-center gap-2">
                <PlatformIcon platform={p.platform ?? "web"} size={20} />
                {p.url ? <a href={p.url} target="_blank" rel="noreferrer noopener" className="truncate font-medium hover:underline">{p.handle ? `@${p.handle}` : platformMeta(p.platform ?? "").label}</a>
                       : <span className="truncate font-medium">{p.handle ? `@${p.handle}` : p.kind ?? "profile"}</span>}
              </div>
              {p.availability === "not_collected" ? <p className="text-xs text-muted-foreground">—</p> : (
                <>
                  <p className="tabular-nums">{p.followers_count != null ? `${fmtCompact(p.followers_count)} followers` : <span className="text-muted-foreground">followers not collected</span>}</p>
                  {p.posts_per_week != null && <p className="text-xs tabular-nums text-muted-foreground">{Number(p.posts_per_week).toFixed(1)} posts/wk</p>}
                </>
              )}
              <AvailabilityBadge availability={p.availability} reason={p.availability_reason ?? p.reason} />
              {p.last_error && <p className="text-xs text-destructive">{p.last_error}</p>}
              {p.last_synced_at && <p className="text-[11px] text-muted-foreground">collected {fmtRelative(p.last_synced_at)}</p>}
            </CardContent>
          </Card>
        )) : <p className="text-sm text-muted-foreground">No profiles added. Edit the competitor to add handles.</p>}
      </div>

      <Tabs value={tab} onValueChange={setTab}>
        <div className="sm:hidden">
          <Select value={tab} onValueChange={setTab}>
            <SelectTrigger className="w-full" aria-label="Section"><SelectValue /></SelectTrigger>
            <SelectContent>{TABS.map((t) => <SelectItem key={t.id} value={t.id}>{t.label}</SelectItem>)}</SelectContent>
          </Select>
        </div>
        <div className="hidden overflow-x-auto sm:block">
          <TabsList>{TABS.map((t) => <TabsTrigger key={t.id} value={t.id}>{t.label}</TabsTrigger>)}</TabsList>
        </div>
        <TabsContent value="overview" className="mt-4"><OverviewTab competitorId={c.id} profiles={profiles} /></TabsContent>
        <TabsContent value="posts" className="mt-4"><PostsTab competitorId={c.id} /></TabsContent>
        <TabsContent value="pillars" className="mt-4"><PillarsHooksTab competitorId={c.id} onGenerateReport={openReport} /></TabsContent>
        <TabsContent value="visual" className="mt-4"><VisualToneTab competitorId={c.id} onGenerateReport={openReport} /></TabsContent>
        <TabsContent value="website" className="mt-4"><CompetitorSourcesTab competitorId={c.id} kind="website" /></TabsContent>
        <TabsContent value="news" className="mt-4"><CompetitorSourcesTab competitorId={c.id} kind="news" /></TabsContent>
        <TabsContent value="gaps" className="mt-4"><GapsTab competitorId={c.id} onGenerateReport={openReport} /></TabsContent>
        <TabsContent value="reports" className="mt-4"><ReportsTab competitorId={c.id} onGenerate={() => setReportOpen(true)} /></TabsContent>
      </Tabs>

      <GenerateReportDialog open={reportOpen} onOpenChange={setReportOpen} competitorId={c.id} />
      <ConfirmDialog open={deleting} onOpenChange={setDeleting} title={`Delete ${c.name}?`} typeToConfirm={c.name} confirmLabel="Delete" busy={remove.isPending}
                     description="Its profiles, collected posts, snapshots and reports will be removed from Botwok. Nothing changes on any platform."
                     onConfirm={() => remove.mutate(c.id, { onSuccess: () => { toast.success("Competitor deleted"); router.push(base); }, onError: (e) => toast.error(errorMessage(e)) })} />
    </div>
  );
}

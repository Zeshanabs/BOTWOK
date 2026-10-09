"use client";
import { useState } from "react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { toast } from "sonner";
import { ExternalLink, LayoutGrid, List, MoreHorizontal, Plus, RefreshCw, Trash2, Users } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Checkbox } from "@/components/ui/checkbox";
import { DropdownMenu, DropdownMenuContent, DropdownMenuItem, DropdownMenuSeparator, DropdownMenuTrigger } from "@/components/ui/dropdown-menu";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { PageHeader } from "@/components/data/page-header";
import { PlatformIcon } from "@/components/data/platform-icon";
import { EmptyState } from "@/components/data/empty-state";
import { AvailabilityBadge } from "@/components/data/availability-badge";
import { ConfirmDialog } from "@/components/data/confirm-dialog";
import { CardGridSkeleton, QueryError, errorMessage } from "@/components/data/async-states";
import { domainOf, fmtCompact, toNumber } from "@/lib/formatters";
import { useCan } from "@/lib/permissions";
import { useSession } from "@/stores/session";
import { useActiveBrandId, useBrands } from "@/features/brand/hooks";
import { useCompetitorMutations, useCompetitors } from "../hooks";
import type { Competitor } from "../types";
import { AddCompetitorDialog } from "./add-competitor-dialog";
import { SyncBadge, syncState } from "./sync-badge";

function followers(c: Competitor): number | null {
  if (c.followers_total != null) return c.followers_total;
  const vals = (c.profiles ?? []).map((p) => toNumber(p.followers_count)).filter((n): n is number => n !== null);
  return vals.length ? vals.reduce((a, b) => a + b, 0) : null;
}

function uniqueAvailability(c: Competitor): string[] {
  return Array.from(new Set((c.profiles ?? []).map((p) => p.availability).filter(Boolean)));
}

export function CompetitorsView() {
  const router = useRouter();
  const slug = useSession((s) => s.workspaceSlug);
  const can = useCan();
  const brandId = useActiveBrandId();
  const brandName = useBrands().data?.find((b) => b.id === brandId)?.name;
  const list = useCompetitors(brandId);
  const { sync, remove } = useCompetitorMutations();
  const [view, setView] = useState<"grid" | "list">("grid");
  const [selected, setSelected] = useState<string[]>([]);
  const [adding, setAdding] = useState(false);
  const [deleting, setDeleting] = useState<Competitor | null>(null);
  const base = `/w/${slug}/competitors`;

  const toggle = (id: string, on: boolean) => setSelected((s) => (on ? [...s, id].slice(-4) : s.filter((x) => x !== id)));
  const doSync = (c: Competitor) => sync.mutate(c.id, { onSuccess: () => toast.success(`Syncing ${c.name}`), onError: (e) => toast.error(errorMessage(e)) });

  const rowMenu = (c: Competitor) => (
    <DropdownMenu>
      <DropdownMenuTrigger asChild><Button variant="ghost" size="icon-sm" aria-label={`Actions for ${c.name}`}><MoreHorizontal className="h-4 w-4" /></Button></DropdownMenuTrigger>
      <DropdownMenuContent align="end">
        <DropdownMenuItem onClick={() => router.push(`${base}/${c.id}`)}>Open</DropdownMenuItem>
        {can.create && <DropdownMenuItem onClick={() => doSync(c)}><RefreshCw className="mr-2 h-4 w-4" /> Sync now</DropdownMenuItem>}
        {can.create && <><DropdownMenuSeparator /><DropdownMenuItem className="text-destructive" onClick={() => setDeleting(c)}><Trash2 className="mr-2 h-4 w-4" /> Delete</DropdownMenuItem></>}
      </DropdownMenuContent>
    </DropdownMenu>
  );

  return (
    <div>
      <PageHeader
        title={`Competitors${brandName ? ` · ${brandName}` : ""}`}
        description="Track competitors from official APIs, their public websites and search — never scraping."
        actions={
          <>
            <div className="hidden rounded-md border p-0.5 sm:flex" role="group" aria-label="View">
              <Button size="icon-sm" variant={view === "grid" ? "secondary" : "ghost"} onClick={() => setView("grid")} aria-label="Grid view" aria-pressed={view === "grid"}><LayoutGrid className="h-4 w-4" /></Button>
              <Button size="icon-sm" variant={view === "list" ? "secondary" : "ghost"} onClick={() => setView("list")} aria-label="List view" aria-pressed={view === "list"}><List className="h-4 w-4" /></Button>
            </div>
            <Button variant="outline" disabled={selected.length < 2} onClick={() => router.push(`${base}/compare?ids=${selected.join(",")}`)}>Compare {selected.length || ""}</Button>
            {can.create && <Button onClick={() => setAdding(true)} disabled={!brandId}><Plus className="h-4 w-4" /> Competitor</Button>}
          </>
        }
      />

      {list.isLoading ? <CardGridSkeleton /> : list.error ? (
        <QueryError error={list.error} onRetry={() => list.refetch()} title="Couldn't load competitors" />
      ) : !list.data?.length ? (
        <EmptyState icon={Users} title="No competitors tracked yet" description="Track up to 10 competitors per brand. Data comes only from official APIs, public websites and search."
                    action={can.create && brandId ? { label: "Add competitor", onClick: () => setAdding(true) } : undefined} />
      ) : view === "grid" ? (
        <div className="grid gap-4 sm:grid-cols-2 xl:grid-cols-3">
          {list.data.map((c) => {
            const st = syncState(c);
            const f = followers(c);
            return (
              <Card key={c.id} className="gap-3">
                <CardHeader className="flex flex-row items-start gap-2">
                  <Checkbox checked={selected.includes(c.id)} onCheckedChange={(v) => toggle(c.id, !!v)} aria-label={`Select ${c.name} to compare`} className="mt-1" />
                  <div className="min-w-0 flex-1">
                    <CardTitle className="truncate text-base"><Link href={`${base}/${c.id}`} className="hover:underline">{c.name}</Link></CardTitle>
                    {c.website && <a href={c.website} target="_blank" rel="noreferrer noopener" className="inline-flex items-center gap-1 text-xs text-muted-foreground hover:underline">{domainOf(c.website)} <ExternalLink className="h-3 w-3" /></a>}
                  </div>
                  {rowMenu(c)}
                </CardHeader>
                <CardContent className="space-y-2 text-sm">
                  <div className="flex flex-wrap items-center gap-1.5">
                    {(c.profiles ?? []).filter((p) => p.platform).map((p) => <PlatformIcon key={p.id} platform={p.platform as string} size={20} />)}
                    <span className="ml-auto"><SyncBadge competitor={c} /></span>
                  </div>
                  <div className="flex gap-4 text-xs text-muted-foreground">
                    <span>Posts/wk <span className="font-medium tabular-nums text-foreground">{c.posts_per_week != null ? Number(c.posts_per_week).toFixed(1) : "—"}</span></span>
                    <span>Followers <span className="font-medium tabular-nums text-foreground">{fmtCompact(f)}</span>{c.followers_delta_30d != null && <span className={Number(c.followers_delta_30d) >= 0 ? "text-green-600" : "text-red-600"}> {Number(c.followers_delta_30d) >= 0 ? "▲" : "▼"}{Math.abs(Number(c.followers_delta_30d)).toFixed(1)}% 30d</span>}</span>
                  </div>
                  <div className="flex flex-wrap gap-1">{uniqueAvailability(c).map((a) => <AvailabilityBadge key={a} availability={a} />)}</div>
                  {st.state === "failed" && st.error && <p className="text-xs text-red-700 dark:text-red-300">{st.error}</p>}
                  <div className="flex gap-2 pt-1">
                    <Button asChild size="sm"><Link href={`${base}/${c.id}`}>Open</Link></Button>
                    {can.create && <Button size="sm" variant="outline" onClick={() => doSync(c)} disabled={st.state === "syncing" || (sync.isPending && sync.variables === c.id)}><RefreshCw className="h-3 w-3" /> {st.state === "failed" ? "Retry sync" : "Sync"}</Button>}
                  </div>
                </CardContent>
              </Card>
            );
          })}
        </div>
      ) : (
        <div className="overflow-x-auto rounded-lg border">
          <Table>
            <TableHeader><TableRow><TableHead className="w-8" /><TableHead>Name</TableHead><TableHead>Platforms</TableHead><TableHead>Last sync</TableHead><TableHead className="text-right">Posts/wk</TableHead><TableHead className="text-right">Followers</TableHead><TableHead>Data sources</TableHead><TableHead /></TableRow></TableHeader>
            <TableBody>
              {list.data.map((c) => (
                <TableRow key={c.id}>
                  <TableCell><Checkbox checked={selected.includes(c.id)} onCheckedChange={(v) => toggle(c.id, !!v)} aria-label={`Select ${c.name}`} /></TableCell>
                  <TableCell className="font-medium"><Link href={`${base}/${c.id}`} className="hover:underline">{c.name}</Link></TableCell>
                  <TableCell><div className="flex gap-1">{(c.profiles ?? []).filter((p) => p.platform).map((p) => <PlatformIcon key={p.id} platform={p.platform as string} size={18} />)}</div></TableCell>
                  <TableCell><SyncBadge competitor={c} /></TableCell>
                  <TableCell className="text-right tabular-nums">{c.posts_per_week != null ? Number(c.posts_per_week).toFixed(1) : "—"}</TableCell>
                  <TableCell className="text-right tabular-nums">{fmtCompact(followers(c))}</TableCell>
                  <TableCell><div className="flex flex-wrap gap-1">{uniqueAvailability(c).map((a) => <AvailabilityBadge key={a} availability={a} short />)}</div></TableCell>
                  <TableCell>{rowMenu(c)}</TableCell>
                </TableRow>
              ))}
            </TableBody>
          </Table>
        </div>
      )}

      <AddCompetitorDialog open={adding} onOpenChange={setAdding} brandId={brandId} onCreated={(id) => router.push(`${base}/${id}`)} />
      <ConfirmDialog open={!!deleting} onOpenChange={(o) => { if (!o) setDeleting(null); }} title={`Delete ${deleting?.name ?? "competitor"}?`}
                     description="Its profiles, collected posts, snapshots and reports will be removed from Botwok. Nothing changes on any platform."
                     confirmLabel="Delete" busy={remove.isPending}
                     onConfirm={() => deleting && remove.mutate(deleting.id, { onSuccess: () => { toast.success("Competitor deleted"); setDeleting(null); setSelected((s) => s.filter((x) => x !== deleting.id)); }, onError: (e) => toast.error(errorMessage(e)) })} />
    </div>
  );
}

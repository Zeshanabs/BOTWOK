"use client";
import { useState } from "react";
import { usePathname, useRouter, useSearchParams } from "next/navigation";
import { useQueryClient } from "@tanstack/react-query";
import { toast } from "sonner";
import { Columns3, Lightbulb, Plus, Sparkles, Table2, X } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Dialog, DialogContent, DialogFooter, DialogHeader, DialogTitle } from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { Sheet, SheetContent, SheetDescription, SheetHeader, SheetTitle } from "@/components/ui/sheet";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { Textarea } from "@/components/ui/textarea";
import { PageHeader } from "@/components/shared/page-header";
import { PlatformIcon } from "@/components/shared/platform-icon";
import { StatusChip } from "@/components/shared/status-chip";
import { EmptyState } from "@/components/shared/empty-state";
import { ConfirmDialog } from "@/components/shared/confirm-dialog";
import { FieldError, FormError, problemFieldErrors } from "@/components/shared/form-errors";
import { CardGridSkeleton, QueryError, errorMessage } from "@/components/shared/async-states";
import { humanize, score100 } from "@/lib/formatters";
import { PLATFORMS } from "@/lib/platforms";
import { useCan } from "@/lib/permissions";
import { useSession } from "@/stores/session";
import { useActiveBrandId, useBrands, usePillars } from "@/features/brand/hooks";
import { RunProgress } from "@/features/ai/components/run-progress";
import { ideaKeys, useCreateIdea, useDeleteIdea, useIdeas, usePromoteIdea, useUpdateIdea } from "../hooks";
import type { Idea } from "../types";
import { evidenceLink, IdeaMenu, type IdeaActions } from "./idea-card";
import { IdeasBoard } from "./ideas-board";
import { GenerateIdeasDialog } from "./generate-ideas-dialog";

const ALL = "all";
const TYPES = ["educational", "authority", "promotional", "engagement", "storytelling", "industry_news", "case_study", "behind_the_scenes", "ugc", "thought_leadership", "announcement"];

function NewIdeaDialog({ open, onOpenChange, brandId }: { open: boolean; onOpenChange: (o: boolean) => void; brandId: string | null }) {
  const create = useCreateIdea(brandId);
  const [title, setTitle] = useState("");
  const [angle, setAngle] = useState("");
  const [type, setType] = useState("educational");
  const errors = problemFieldErrors(create.error);
  return (
    <Dialog open={open} onOpenChange={(o) => { if (!o) create.reset(); onOpenChange(o); }}>
      <DialogContent>
        <DialogHeader><DialogTitle>New idea</DialogTitle></DialogHeader>
        <form id="new-idea" className="space-y-3" onSubmit={(e) => {
          e.preventDefault();
          if (!brandId || !title.trim()) return;
          create.mutate({ brand_id: brandId, title: title.trim(), angle: angle.trim() || null, content_type: type, status: "new" }, { onSuccess: () => { toast.success("Idea added"); setTitle(""); setAngle(""); onOpenChange(false); } });
        }}>
          <div className="space-y-1"><Label htmlFor="ni-title">Title</Label><Input id="ni-title" value={title} onChange={(e) => setTitle(e.target.value)} required /><FieldError errors={errors} name="title" /></div>
          <div className="space-y-1"><Label htmlFor="ni-angle">Angle</Label><Textarea id="ni-angle" rows={2} value={angle} onChange={(e) => setAngle(e.target.value)} /></div>
          <div className="space-y-1"><Label htmlFor="ni-type">Type</Label>
            <Select value={type} onValueChange={setType}><SelectTrigger id="ni-type" className="w-full"><SelectValue /></SelectTrigger>
              <SelectContent>{TYPES.map((t) => <SelectItem key={t} value={t}>{humanize(t)}</SelectItem>)}</SelectContent></Select>
          </div>
          <FormError error={Object.keys(errors).length ? null : create.error} />
        </form>
        <DialogFooter><Button variant="outline" onClick={() => onOpenChange(false)}>Cancel</Button><Button type="submit" form="new-idea" disabled={!title.trim() || create.isPending}>Add idea</Button></DialogFooter>
      </DialogContent>
    </Dialog>
  );
}

export function IdeasView() {
  const router = useRouter();
  const pathname = usePathname();
  const sp = useSearchParams();
  const qc = useQueryClient();
  const slug = useSession((s) => s.workspaceSlug);
  const can = useCan();
  const brandId = useActiveBrandId();
  const brandName = useBrands().data?.find((b) => b.id === brandId)?.name;
  const ideas = useIdeas(brandId);
  const pillars = usePillars(brandId);
  const update = useUpdateIdea(brandId);
  const promote = usePromoteIdea(brandId);
  const del = useDeleteIdea(brandId);
  const [genOpen, setGenOpen] = useState(false);
  const [newOpen, setNewOpen] = useState(false);
  const [detail, setDetail] = useState<Idea | null>(null);
  const [deleting, setDeleting] = useState<Idea | null>(null);
  const [type, setType] = useState(ALL);
  const [platform, setPlatform] = useState(ALL);
  const [pillar, setPillar] = useState(ALL);
  const view = sp.get("view") === "table" ? "table" : "board";
  const runId = sp.get("run");
  const pillarNames = Object.fromEntries((pillars.data ?? []).map((p) => [p.id, p.name]));

  function setParam(k: string, v: string | null) {
    const p = new URLSearchParams(sp.toString());
    if (v === null) p.delete(k); else p.set(k, v);
    const s = p.toString();
    router.replace(s ? `${pathname}?${s}` : pathname);
  }

  const actions: IdeaActions = {
    onStatus: (idea, status) => update.mutate({ id: idea.id, body: { status } }, { onSuccess: () => toast.success(`Moved to ${status}`) }),
    onPromote: (idea) => promote.mutate(idea.id, {
      onSuccess: (d) => {
        const cid = d?.content_id ?? d?.content_item_id ?? d?.id;
        toast.success("Promoted to a Studio draft");
        if (cid) router.push(`/w/${slug}/studio/${cid}`);
      },
      onError: (e) => toast.error(errorMessage(e)),
    }),
    onDelete: (idea) => setDeleting(idea),
    onOpen: (idea) => setDetail(idea),
  };

  const list = (ideas.data ?? [])
    .filter((i) => type === ALL || i.content_type === type)
    .filter((i) => platform === ALL || (i.platforms ?? []).includes(platform))
    .filter((i) => pillar === ALL || i.pillar_id === pillar);
  const filtered = type !== ALL || platform !== ALL || pillar !== ALL;

  return (
    <div>
      <PageHeader
        title={`Ideas${brandName ? ` · ${brandName}` : ""}`}
        description="Collect, generate, triage and promote ideas into Studio."
        actions={
          <>
            <div className="flex rounded-md border p-0.5" role="group" aria-label="View">
              <Button size="icon-sm" variant={view === "board" ? "secondary" : "ghost"} aria-label="Board view" aria-pressed={view === "board"} onClick={() => setParam("view", null)}><Columns3 className="h-4 w-4" /></Button>
              <Button size="icon-sm" variant={view === "table" ? "secondary" : "ghost"} aria-label="Table view" aria-pressed={view === "table"} onClick={() => setParam("view", "table")}><Table2 className="h-4 w-4" /></Button>
            </div>
            {can.create && <Button variant="outline" size="icon" aria-label="New idea" onClick={() => setNewOpen(true)} disabled={!brandId}><Plus className="h-4 w-4" /></Button>}
            {can.create && <Button onClick={() => setGenOpen(true)} disabled={!brandId}><Sparkles className="h-4 w-4" /> Generate</Button>}
          </>
        }
      />

      <div className="mb-4 flex flex-wrap gap-2">
        <Select value={type} onValueChange={setType}>
          <SelectTrigger size="sm" aria-label="Type"><SelectValue /></SelectTrigger>
          <SelectContent><SelectItem value={ALL}>All types</SelectItem>{TYPES.map((t) => <SelectItem key={t} value={t}>{humanize(t)}</SelectItem>)}</SelectContent>
        </Select>
        <Select value={platform} onValueChange={setPlatform}>
          <SelectTrigger size="sm" aria-label="Platform"><SelectValue /></SelectTrigger>
          <SelectContent><SelectItem value={ALL}>All platforms</SelectItem>{PLATFORMS.map((p) => <SelectItem key={p.id} value={p.id}>{p.label}</SelectItem>)}</SelectContent>
        </Select>
        {(pillars.data ?? []).length > 0 && (
          <Select value={pillar} onValueChange={setPillar}>
            <SelectTrigger size="sm" aria-label="Pillar"><SelectValue /></SelectTrigger>
            <SelectContent><SelectItem value={ALL}>All pillars</SelectItem>{pillars.data?.map((p) => <SelectItem key={p.id} value={p.id}>{p.name}</SelectItem>)}</SelectContent>
          </Select>
        )}
        {filtered && <Button size="sm" variant="ghost" onClick={() => { setType(ALL); setPlatform(ALL); setPillar(ALL); }}>Clear filters</Button>}
      </div>

      {runId && (
        <Card className="mb-4">
          <CardHeader className="flex flex-row items-center justify-between"><CardTitle className="text-sm">✦ Generating ideas</CardTitle>
            <Button variant="ghost" size="icon-sm" aria-label="Dismiss" onClick={() => setParam("run", null)}><X className="h-4 w-4" /></Button></CardHeader>
          <CardContent><RunProgress runId={runId} compact onFinished={() => qc.invalidateQueries({ queryKey: ideaKeys.list(brandId) })} /></CardContent>
        </Card>
      )}

      {!brandId ? <EmptyState icon={Lightbulb} title="Select a brand" description="Ideas belong to a brand. Pick one in the header." /> :
       ideas.isLoading ? <CardGridSkeleton count={8} className="md:grid-cols-4 xl:grid-cols-4" cardClassName="h-28" /> : ideas.error ? (
        <QueryError error={ideas.error} onRetry={() => ideas.refetch()} title="Couldn't load ideas" />
      ) : !(ideas.data ?? []).length ? (
        <EmptyState icon={Lightbulb} title="No ideas yet" description="Generate ideas with AI, start from a trend, or add one manually."
                    action={can.create ? { label: "✦ Generate ideas", onClick: () => setGenOpen(true) } : undefined} />
      ) : view === "board" ? (
        <IdeasBoard ideas={list} pillarNames={pillarNames} actions={actions} />
      ) : (
        <div className="overflow-x-auto rounded-lg border">
          <Table>
            <TableHeader><TableRow><TableHead>Idea</TableHead><TableHead>Type</TableHead><TableHead>Format</TableHead><TableHead>Platforms</TableHead><TableHead>Pillar</TableHead><TableHead className="text-right">Score</TableHead><TableHead>Source</TableHead><TableHead>Status</TableHead><TableHead /></TableRow></TableHeader>
            <TableBody>
              {list.map((i) => {
                const ev = evidenceLink(i, slug);
                return (
                  <TableRow key={i.id}>
                    <TableCell className="max-w-xs"><button type="button" className="truncate text-left font-medium hover:underline" onClick={() => setDetail(i)}>{i.ai_run_id && <span className="mr-1 text-ai">✦</span>}{i.title}</button></TableCell>
                    <TableCell className="text-xs">{humanize(i.content_type)}</TableCell>
                    <TableCell className="text-xs">{(i.formats ?? (i.format ? [i.format] : [])).join(", ").replace(/_/g, " ")}</TableCell>
                    <TableCell><div className="flex gap-1">{(i.platforms ?? []).map((p) => <PlatformIcon key={p} platform={p} size={16} />)}</div></TableCell>
                    <TableCell className="text-xs">{i.pillar_id ? pillarNames[i.pillar_id] ?? "—" : i.pillar?.name ?? "—"}</TableCell>
                    <TableCell className="text-right tabular-nums">{score100(i.score) ?? "—"}</TableCell>
                    <TableCell className="text-xs">{ev ? <a href={ev.href} className="text-primary hover:underline">↳ {ev.label}</a> : "manual"}</TableCell>
                    <TableCell><StatusChip status={i.status} /></TableCell>
                    <TableCell className="whitespace-nowrap">
                      {can.create && i.status !== "promoted" && i.status !== "shortlisted" && <Button size="xs" variant="ghost" onClick={() => actions.onStatus(i, "shortlisted")}>Shortlist</Button>}
                      {can.create && i.status !== "promoted" && <Button size="xs" variant="outline" onClick={() => actions.onPromote(i)}>Promote</Button>}
                      <IdeaMenu idea={i} actions={actions} />
                    </TableCell>
                  </TableRow>
                );
              })}
            </TableBody>
          </Table>
          {!list.length && <p className="p-6 text-center text-sm text-muted-foreground">No ideas match these filters.</p>}
        </div>
      )}

      <GenerateIdeasDialog open={genOpen} onOpenChange={setGenOpen} brandId={brandId} onStarted={(id) => setParam("run", id)} />
      <NewIdeaDialog open={newOpen} onOpenChange={setNewOpen} brandId={brandId} />
      <ConfirmDialog open={!!deleting} onOpenChange={(o) => { if (!o) setDeleting(null); }} title="Delete this idea?" description={`“${deleting?.title ?? ""}” will be removed. Promoted content is not affected.`}
                     confirmLabel="Delete" busy={del.isPending}
                     onConfirm={() => deleting && del.mutate(deleting.id, { onSuccess: () => { toast.success("Idea deleted"); setDeleting(null); }, onError: (e) => toast.error(errorMessage(e)) })} />
      <Sheet open={!!detail} onOpenChange={(o) => { if (!o) setDetail(null); }}>
        <SheetContent className="w-full overflow-y-auto sm:max-w-lg">
          {detail && (
            <>
              <SheetHeader>
                <SheetTitle>{detail.ai_run_id && <span className="mr-1 text-ai">✦</span>}{detail.title}</SheetTitle>
                <SheetDescription>{humanize(detail.content_type)} · <StatusChip status={detail.status} /></SheetDescription>
              </SheetHeader>
              <div className="space-y-4 px-4 pb-6 text-sm">
                {detail.angle && <section><h3 className="mb-1 text-xs font-semibold uppercase tracking-wide text-muted-foreground">Angle</h3><p>{detail.angle}</p></section>}
                {(detail.hooks?.length ?? 0) > 0 && (
                  <section><h3 className="mb-1 text-xs font-semibold uppercase tracking-wide text-muted-foreground">Hooks</h3>
                    <ul className="list-disc space-y-1 pl-5">{detail.hooks?.map((h, i) => <li key={i}>{typeof h === "string" ? h : h.text}</li>)}</ul></section>
                )}
                {detail.evidence?.rationale && <section><h3 className="mb-1 text-xs font-semibold uppercase tracking-wide text-muted-foreground">Why this idea</h3><p>{detail.evidence.rationale}</p></section>}
                <section><h3 className="mb-1 text-xs font-semibold uppercase tracking-wide text-muted-foreground">Evidence</h3>
                  {(() => { const ev = evidenceLink(detail, slug); return ev ? <a href={ev.href} className="text-primary hover:underline">↳ {ev.label}</a> : <p className="text-muted-foreground">Added manually.</p>; })()}
                  {detail.ai_run_id && <p className="mt-1"><a className="text-xs text-primary hover:underline" href={`/w/${slug}/command-center/${detail.ai_run_id}`}>Generating run ↗</a></p>}
                </section>
                {can.create && detail.status !== "promoted" && <Button onClick={() => actions.onPromote(detail)} disabled={promote.isPending}>Promote to Studio</Button>}
              </div>
            </>
          )}
        </SheetContent>
      </Sheet>
    </div>
  );
}

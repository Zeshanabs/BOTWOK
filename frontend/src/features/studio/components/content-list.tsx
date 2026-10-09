"use client";
import { useDeferredValue, useState } from "react";
import Link from "next/link";
import { useRouter, useSearchParams } from "next/navigation";
import { useInfiniteQuery, useMutation } from "@tanstack/react-query";
import { FileText, Loader2, Plus, Search, Sparkles } from "lucide-react";
import { toast } from "sonner";
import { Button } from "@/components/ui/button";
import { Checkbox } from "@/components/ui/checkbox";
import { Dialog, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle } from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { Skeleton } from "@/components/ui/skeleton";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { Textarea } from "@/components/ui/textarea";
import { EmptyState } from "@/components/data/empty-state";
import { PageHeader } from "@/components/data/page-header";
import { PlatformIcon } from "@/components/data/platform-icon";
import { StatusChip } from "@/components/data/status-chip";
import { QueryError } from "@/features/common/components/query-state";
import { useActiveBrand, usePermissions, usePillars, useWorkspacePath } from "@/features/common/hooks";
import { CONTENT_FORMATS, CONTENT_STATUSES, type ContentFormat, type ListResponse } from "@/features/common/types";
import { errorMessage, fieldErrors, relTime, toItems } from "@/features/common/utils";
import { PLATFORMS } from "@/lib/platforms";
import { contentApi, type ContentFilters, type ContentItem } from "../api";

/** List rows expose `platforms`; full items expose `variants`. */
const platformsOf = (c: ContentItem) => c.platforms ?? Array.from(new Set((c.variants ?? []).map((v) => v.platform)));
const CONTENT_TYPES = ["educational", "authority", "promotional", "engagement", "storytelling", "industry_news", "case_study", "behind_the_scenes", "ugc", "thought_leadership", "announcement"];
const ALL = "all";

/** Studio list (doc 24 §12): table of content with status, platform variants, pillar, updated; filters live in state. */
export function ContentList() {
  const ws = useWorkspacePath();
  const router = useRouter();
  const { brandId } = useActiveBrand();
  const { canCreate } = usePermissions();
  const pillars = toItems(usePillars(brandId).data);
  const [status, setStatus] = useState(ALL);
  const [pillar, setPillar] = useState(ALL);
  const [platform, setPlatform] = useState(ALL);
  const [q, setQ] = useState("");
  const dq = useDeferredValue(q.trim());
  const params = useSearchParams();
  const [newOpen, setNewOpen] = useState(() => params.get("new") === "1" && canCreate);
  const filters: ContentFilters = { brand_id: brandId, status: status === ALL ? undefined : status, pillar_id: pillar === ALL ? undefined : pillar, platform: platform === ALL ? undefined : platform, q: dq || undefined };
  const list = useInfiniteQuery({
    queryKey: ["content", "list", filters],
    queryFn: ({ pageParam }) => contentApi.list({ ...filters, cursor: pageParam }),
    initialPageParam: undefined as string | undefined,
    getNextPageParam: (last: ListResponse<ContentItem>) => (Array.isArray(last) ? undefined : last.next_cursor ?? undefined),
  });
  const rows = (list.data?.pages ?? []).flatMap((p) => toItems(p));
  const filtered = status !== ALL || pillar !== ALL || platform !== ALL || !!dq;
  const clear = () => { setStatus(ALL); setPillar(ALL); setPlatform(ALL); setQ(""); };
  const pillarName = (id?: string | null) => pillars.find((p) => p.id === id)?.name;

  return (
    <div>
      <PageHeader title="Studio" description="Write, generate, repurpose, check and approve content."
                  actions={canCreate && <Button onClick={() => setNewOpen(true)} disabled={!brandId}><Plus /> New content</Button>} />
      <div className="mb-4 flex flex-wrap items-center gap-2">
        <div className="relative w-full sm:w-64"><Search className="absolute left-2 top-2.5 h-4 w-4 text-muted-foreground" /><Input value={q} onChange={(e) => setQ(e.target.value)} placeholder="Search titles…" className="pl-8" aria-label="Search content" /></div>
        <Select value={status} onValueChange={setStatus}><SelectTrigger className="w-40" aria-label="Status"><SelectValue /></SelectTrigger>
          <SelectContent><SelectItem value={ALL}>All statuses</SelectItem>{CONTENT_STATUSES.map((s) => <SelectItem key={s} value={s}>{s.replace(/_/g, " ")}</SelectItem>)}</SelectContent></Select>
        <Select value={platform} onValueChange={setPlatform}><SelectTrigger className="w-40" aria-label="Platform"><SelectValue /></SelectTrigger>
          <SelectContent><SelectItem value={ALL}>All platforms</SelectItem>{PLATFORMS.map((p) => <SelectItem key={p.id} value={p.id}>{p.label}</SelectItem>)}</SelectContent></Select>
        <Select value={pillar} onValueChange={setPillar}><SelectTrigger className="w-40" aria-label="Pillar"><SelectValue /></SelectTrigger>
          <SelectContent><SelectItem value={ALL}>All pillars</SelectItem>{pillars.map((p) => <SelectItem key={p.id} value={p.id}>{p.name}</SelectItem>)}</SelectContent></Select>
        {filtered && <Button variant="ghost" size="sm" onClick={clear}>Clear filters</Button>}
      </div>
      {!brandId && <p className="mb-4 text-sm text-muted-foreground">Select a brand in the header to see its content.</p>}
      {list.isLoading ? (
        <div className="space-y-2" aria-busy="true">{Array.from({ length: 6 }).map((_, i) => <Skeleton key={i} className="h-12 w-full" />)}</div>
      ) : list.error ? (
        <QueryError error={list.error} onRetry={() => list.refetch()} title="Couldn't load content" notAvailableText="The content API isn't available on this backend yet." />
      ) : rows.length === 0 ? (
        filtered
          ? <EmptyState icon={Search} title="No content matches these filters" action={{ label: "Clear filters", onClick: clear }} />
          : <EmptyState icon={FileText} title="No content yet" description="Start a post from scratch, from an idea, or let the writer draft one from a prompt." action={canCreate ? { label: "New content", onClick: () => setNewOpen(true) } : undefined} />
      ) : (
        <>
          <div className="hidden rounded-lg border md:block">
            <Table>
              <TableHeader><TableRow><TableHead>Title</TableHead><TableHead>Status</TableHead><TableHead>Platforms</TableHead><TableHead>Pillar</TableHead><TableHead>Campaign</TableHead><TableHead className="text-right">Updated</TableHead></TableRow></TableHeader>
              <TableBody>
                {rows.map((c) => (
                  <TableRow key={c.id} className="cursor-pointer" onClick={() => router.push(ws(`studio/${c.id}`))}>
                    <TableCell className="max-w-[360px]"><Link href={ws(`studio/${c.id}`)} className="flex items-center gap-1.5 font-medium hover:underline" onClick={(e) => e.stopPropagation()}>{c.ai_generated && <Sparkles className="h-3.5 w-3.5 shrink-0 text-ai" aria-label="AI-assisted" />}<span className="truncate">{c.title || "Untitled"}</span></Link></TableCell>
                    <TableCell><StatusChip status={c.status} /></TableCell>
                    <TableCell><div className="flex gap-1">{platformsOf(c).map((p) => <PlatformIcon key={p} platform={p} size={18} />)}{!platformsOf(c).length && <span className="text-xs text-muted-foreground">master only</span>}</div></TableCell>
                    <TableCell className="text-sm">{c.pillar?.name ?? pillarName(c.pillar_id) ?? "—"}</TableCell>
                    <TableCell className="text-sm">{c.campaign?.name ?? "—"}</TableCell>
                    <TableCell className="text-right text-sm text-muted-foreground">{relTime(c.updated_at ?? c.created_at)}</TableCell>
                  </TableRow>
                ))}
              </TableBody>
            </Table>
          </div>
          <ul className="space-y-2 md:hidden">
            {rows.map((c) => (
              <li key={c.id}><Link href={ws(`studio/${c.id}`)} className="block rounded-lg border p-3 hover:bg-accent">
                <div className="flex items-center gap-2"><StatusChip status={c.status} /><span className="ml-auto text-xs text-muted-foreground">{relTime(c.updated_at ?? c.created_at)}</span></div>
                <p className="mt-1 font-medium">{c.ai_generated && <Sparkles className="mr-1 inline h-3.5 w-3.5 text-ai" />}{c.title || "Untitled"}</p>
                <div className="mt-1 flex gap-1">{platformsOf(c).map((p) => <PlatformIcon key={p} platform={p} size={16} />)}</div>
              </Link></li>
            ))}
          </ul>
          {list.hasNextPage && <div className="mt-4 text-center"><Button variant="outline" onClick={() => list.fetchNextPage()} disabled={list.isFetchingNextPage}>{list.isFetchingNextPage && <Loader2 className="animate-spin" />} Load more</Button></div>}
        </>
      )}
      {brandId && <NewContentDialog open={newOpen} onOpenChange={setNewOpen} brandId={brandId} onCreated={(id, panel) => router.push(ws(`studio/${id}${panel ? `?panel=${panel}` : ""}`))} />}
    </div>
  );
}

export function NewContentDialog({ open, onOpenChange, brandId, onCreated, defaultTitle = "" }: {
  open: boolean; onOpenChange: (o: boolean) => void; brandId: string; onCreated: (id: string, panel?: string) => void; defaultTitle?: string;
}) {
  const pillars = toItems(usePillars(brandId).data);
  const [title, setTitle] = useState(defaultTitle);
  const [format, setFormat] = useState<ContentFormat>("text");
  const [type, setType] = useState(ALL);
  const [pillar, setPillar] = useState(ALL);
  const [useAi, setUseAi] = useState(false);
  const [prompt, setPrompt] = useState("");
  const create = useMutation({
    mutationFn: async () => {
      const item = await contentApi.create({ brand_id: brandId, title: title.trim(), master_format: format, content_type: type === ALL ? undefined : type, pillar_id: pillar === ALL ? undefined : pillar, body: useAi && prompt.trim() ? { notes: prompt.trim() } : undefined });
      let generated = false;
      if (useAi) {
        try { await contentApi.generate(item.id, { mode: "write", instructions: prompt.trim() || undefined, format }); generated = true; }
        catch (e) { toast.error(`Draft created, but generation didn't start: ${errorMessage(e)}`); }
      }
      return { item, generated };
    },
    onSuccess: ({ item, generated }) => { toast.success(generated ? "Created — the writer is drafting" : "Content created"); onOpenChange(false); onCreated(item.id, generated ? "ai" : undefined); },
  });
  const errs = fieldErrors(create.error);
  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent>
        <DialogHeader><DialogTitle>New content</DialogTitle><DialogDescription>Creates a master post. Platform versions are added from the editor.</DialogDescription></DialogHeader>
        <form id="new-content" className="space-y-3" onSubmit={(e) => { e.preventDefault(); if (title.trim()) create.mutate(); }}>
          <div className="space-y-1.5"><Label htmlFor="nc-title">Title</Label><Input id="nc-title" autoFocus value={title} onChange={(e) => setTitle(e.target.value)} placeholder="Q4 cold brew launch" aria-invalid={!!errs.title} />{errs.title && <p className="text-xs text-red-600">{errs.title}</p>}</div>
          <div className="grid gap-3 sm:grid-cols-3">
            <div className="space-y-1.5"><Label>Format</Label><Select value={format} onValueChange={(v) => setFormat(v as ContentFormat)}><SelectTrigger className="w-full"><SelectValue /></SelectTrigger><SelectContent>{CONTENT_FORMATS.map((f) => <SelectItem key={f} value={f}>{f.replace(/_/g, " ")}</SelectItem>)}</SelectContent></Select></div>
            <div className="space-y-1.5"><Label>Type</Label><Select value={type} onValueChange={setType}><SelectTrigger className="w-full"><SelectValue /></SelectTrigger><SelectContent><SelectItem value={ALL}>—</SelectItem>{CONTENT_TYPES.map((t) => <SelectItem key={t} value={t}>{t.replace(/_/g, " ")}</SelectItem>)}</SelectContent></Select></div>
            <div className="space-y-1.5"><Label>Pillar</Label><Select value={pillar} onValueChange={setPillar}><SelectTrigger className="w-full"><SelectValue /></SelectTrigger><SelectContent><SelectItem value={ALL}>—</SelectItem>{pillars.map((p) => <SelectItem key={p.id} value={p.id}>{p.name}</SelectItem>)}</SelectContent></Select></div>
          </div>
          <label className="flex items-center gap-2 text-sm"><Checkbox checked={useAi} onCheckedChange={(c) => setUseAi(c === true)} /><Sparkles className="h-4 w-4 text-ai" /> Draft it with AI (writer · powerful tier)</label>
          {useAi && <Textarea rows={3} value={prompt} onChange={(e) => setPrompt(e.target.value)} placeholder="What should the post say? Audience, angle, sources to cite…" aria-label="Prompt" />}
          {create.error && !Object.keys(errs).length && <p className="text-sm text-red-600">{errorMessage(create.error)}</p>}
          {errs._ && <p className="text-sm text-red-600">{errs._}</p>}
        </form>
        <DialogFooter>
          <Button variant="outline" onClick={() => onOpenChange(false)}>Cancel</Button>
          <Button type="submit" form="new-content" disabled={!title.trim() || create.isPending}>{create.isPending && <Loader2 className="animate-spin" />} Create</Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}

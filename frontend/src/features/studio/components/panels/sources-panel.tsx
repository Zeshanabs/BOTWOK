"use client";
import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { Copy, ExternalLink, Plus, Search, Sparkles, X } from "lucide-react";
import { toast } from "sonner";
import { Button } from "@/components/ui/button";
import { Dialog, DialogContent, DialogDescription, DialogHeader, DialogTitle } from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { QueryError, SkeletonRows } from "@/features/common/components/query-state";
import { usePermissions } from "@/features/common/hooks";
import type { ListResponse } from "@/features/common/types";
import { fmtDate, toItems } from "@/features/common/utils";
import { api, qs } from "@/lib/api";
import { cn } from "@/lib/utils";
import { isUnsupported, sourceView, type ContentItem } from "../../api";
import { VerdictIcon } from "./critic-panel";

export interface PendingSource { id: string; title: string; usedFor: string }

interface ResearchSource { id: string; title?: string | null; canonical_url: string; domain: string; summary?: string | null; credibility_score?: number | null; published_at?: string | null; retrieved_at?: string | null; citation?: string | null }

function Cred({ v }: { v: number | null | undefined }) {
  if (v == null) return null;
  const n = Number(v) <= 1 ? Number(v) * 100 : Number(v);
  return <span className={cn("rounded px-1.5 py-0.5 text-[10px] font-medium", n >= 70 ? "bg-success/12 text-success" : n >= 40 ? "bg-warning/12 text-warning" : "bg-destructive/10 text-destructive")} title="Credibility">cred {Math.round(n)}</span>;
}

/**
 * Research & Sources tab: cited sources with claim mapping and unsupported claims. Picking a source from the research
 * library queues it as `source_ids` for the next AI generation (the content API links sources when the writer cites them).
 */
export function SourcesPanel({ content, pending, onAdd, onRemove }: { content: ContentItem; pending: PendingSource[]; onAdd: (s: PendingSource) => void; onRemove: (id: string) => void }) {
  const { canCreate } = usePermissions();
  const [open, setOpen] = useState(false);
  const [q, setQ] = useState("");
  const [usedFor, setUsedFor] = useState("claim");
  const sources = (content.sources ?? []).map(sourceView);
  const search = useQuery({
    queryKey: ["research", "sources", "search", q],
    queryFn: () => api.get<ListResponse<ResearchSource>>(`/research/sources${qs({ q, limit: 20 })}`),
    enabled: open && q.trim().length >= 2,
    retry: false,
  });
  const attached = new Set([...(content.sources ?? []).map((x) => x.source_id), ...pending.map((p) => p.id)]);
  const claims = [...(content.factcheck?.claims ?? []), ...(content.variants ?? []).flatMap((v) => v.factcheck?.claims ?? [])];
  const unsupported = claims.filter(isUnsupported);

  return (
    <div className="space-y-4">
      <div className="flex items-center justify-between">
        <p className="text-xs text-muted-foreground">{sources.length} source{sources.length === 1 ? "" : "s"} attached</p>
        {canCreate && <Button size="sm" variant="outline" onClick={() => setOpen(true)}><Plus /> Add source</Button>}
      </div>
      {pending.length > 0 && (
        <div className="rounded-md border border-dashed p-2 text-xs">
          <p className="mb-1 flex items-center gap-1 font-medium"><Sparkles className="h-3.5 w-3.5 text-ai" /> Queued for the next AI run</p>
          <ul className="space-y-1">{pending.map((p) => <li key={p.id} className="flex items-center gap-2"><span className="min-w-0 flex-1 truncate">{p.title}</span><span className="rounded border px-1">{p.usedFor}</span><Button size="icon-xs" variant="ghost" aria-label={`Remove ${p.title}`} onClick={() => onRemove(p.id)}><X /></Button></li>)}</ul>
          <p className="mt-1 text-muted-foreground">Run Write/Rewrite in the AI tab — cited sources then appear below with their claims.</p>
        </div>
      )}
      {sources.length === 0 ? <p className="rounded-md border border-dashed p-3 text-sm text-muted-foreground">No sources linked yet. Add research sources so claims can be cited and fact-checked.</p> : (
        <ol className="space-y-2">
          {sources.map((s, i) => (
            <li key={`${s.id}-${s.usedFor}`} className="rounded-md border p-2 text-xs">
              <div className="flex items-start gap-2">
                <span className="font-mono text-muted-foreground">[{i + 1}]</span>
                <div className="min-w-0 flex-1">
                  <p className="font-medium">{s.url ? <a href={s.url} target="_blank" rel="noreferrer" className="hover:underline">{s.title ?? s.url}<ExternalLink className="ml-1 inline h-3 w-3" /></a> : (s.title ?? "Untitled source")}</p>
                  <p className="mt-0.5 flex flex-wrap items-center gap-1.5 text-muted-foreground">
                    {s.domain && <span>{s.domain}</span>}<Cred v={s.credibility} />
                    {s.publishedAt && <span>published {fmtDate(s.publishedAt)}</span>}{s.retrievedAt && <span>· retrieved {fmtDate(s.retrievedAt)}</span>}
                    <span className="rounded border px-1">{s.usedFor}</span>
                  </p>
                  {s.claim && <p className="mt-1 flex items-start gap-1">{s.verdict && <VerdictIcon verdict={s.verdict} />}<span>Claim: “{s.claim}”</span></p>}
                  {s.citation && <p className="mt-1 italic text-muted-foreground">{s.citation}</p>}
                </div>
                <div className="flex flex-col gap-1">
                  <Button size="icon-xs" variant="ghost" aria-label={`Copy citation [${i + 1}]`} title="Copy [n] marker" onClick={() => { void navigator.clipboard?.writeText(`[${i + 1}]`); toast.success(`[${i + 1}] copied — paste it after the claim`); }}><Copy /></Button>
                </div>
              </div>
            </li>
          ))}
        </ol>
      )}
      {unsupported.length > 0 && (
        <div>
          <p className="mb-1 text-xs font-medium text-destructive">Unsupported claims</p>
          <ul className="space-y-1 text-xs">{unsupported.map((c, i) => <li key={i} className="flex gap-1.5"><VerdictIcon verdict={c.verdict} />“{c.claim ?? c.text}”</li>)}</ul>
        </div>
      )}
      <Dialog open={open} onOpenChange={setOpen}>
        <DialogContent className="sm:max-w-xl">
          <DialogHeader><DialogTitle>Add a source</DialogTitle><DialogDescription>Search sources saved by research runs. Selected sources are passed to the writer on the next AI run.</DialogDescription></DialogHeader>
          <div className="flex gap-2">
            <div className="relative flex-1"><Search className="absolute left-2 top-2.5 h-4 w-4 text-muted-foreground" /><Input autoFocus value={q} onChange={(e) => setQ(e.target.value)} placeholder="Search title, domain, topic…" className="pl-8" aria-label="Search sources" /></div>
            <Select value={usedFor} onValueChange={setUsedFor}><SelectTrigger className="w-32" aria-label="Used for"><SelectValue /></SelectTrigger>
              <SelectContent><SelectItem value="claim">claim</SelectItem><SelectItem value="data">data</SelectItem><SelectItem value="inspiration">inspiration</SelectItem></SelectContent></Select>
          </div>
          <div className="max-h-[50vh] space-y-2 overflow-y-auto">
            {q.trim().length < 2 && <p className="text-sm text-muted-foreground">Type at least two characters.</p>}
            {search.isLoading && <SkeletonRows rows={3} />}
            {search.error && <QueryError error={search.error} onRetry={() => search.refetch()} notAvailableText="The research library isn't available yet." />}
            {search.data && toItems(search.data).length === 0 && <p className="text-sm text-muted-foreground">No sources match “{q}”. Run research from the Research page first.</p>}
            {toItems(search.data).map((s) => (
              <div key={s.id} className="flex items-start gap-2 rounded-md border p-2 text-sm">
                <div className="min-w-0 flex-1">
                  <p className="font-medium">{s.title ?? s.canonical_url}</p>
                  <p className="flex items-center gap-1.5 text-xs text-muted-foreground">{s.domain}<Cred v={s.credibility_score} />{s.published_at && fmtDate(s.published_at)}</p>
                  {s.summary && <p className="mt-1 line-clamp-2 text-xs text-muted-foreground">{s.summary}</p>}
                </div>
                <Button size="sm" variant={attached.has(s.id) ? "secondary" : "default"} disabled={attached.has(s.id)}
                        onClick={() => { onAdd({ id: s.id, title: s.title ?? s.domain, usedFor }); toast.success("Queued for the next AI run"); }}>
                  {attached.has(s.id) ? "Added" : "Use"}
                </Button>
              </div>
            ))}
          </div>
        </DialogContent>
      </Dialog>
    </div>
  );
}

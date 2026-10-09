"use client";
import { useState } from "react";
import { toast } from "sonner";
import { Bookmark, Quote } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { StatusChip } from "@/components/data/status-chip";
import { ListSkeleton, QueryError, errorMessage } from "@/components/data/async-states";
import { domainOf, fmtDate, fmtUsd } from "@/lib/formatters";
import { useCan } from "@/lib/permissions";
import { RunProgress } from "@/features/ai/components/run-progress";
import { useResearchRun, useSaveSource } from "../hooks";
import { ACTIVE_RESEARCH, credibilityOf, relevanceOf, type ResearchSourceRef } from "../types";
import { CredibilityBadge, Favicon, InjectionBadge, RelevanceBadge } from "./source-badges";
import { SourceDrawer, citationFor } from "./source-drawer";

type Sort = "relevance" | "credibility" | "date";

export function ResearchResults({ runId }: { runId: string }) {
  const can = useCan();
  const q = useResearchRun(runId);
  const save = useSaveSource();
  const [sort, setSort] = useState<Sort>("relevance");
  const [minCred, setMinCred] = useState("0");
  const [search, setSearch] = useState("");
  const [openId, setOpenId] = useState<string | null>(null);
  const [limit, setLimit] = useState(20);

  if (q.isLoading) return <ListSkeleton rows={6} rowClassName="h-20" />;
  if (q.error || !q.data) return <QueryError error={q.error} onRetry={() => q.refetch()} title="Couldn't load this research run" notFoundText="This research run doesn't exist in this workspace." />;
  const run = q.data;
  const active = ACTIVE_RESEARCH.includes(run.status);
  const all: ResearchSourceRef[] = run.sources ?? [];
  const num = (v: unknown) => Number(v ?? 0) || 0;
  const filtered = all
    .filter((s) => num(credibilityOf(s)) * (num(credibilityOf(s)) <= 1 ? 100 : 1) >= Number(minCred))
    .filter((s) => !search || `${s.title} ${s.summary} ${s.domain}`.toLowerCase().includes(search.toLowerCase()))
    .sort((a, b) => sort === "date" ? String(b.published_at ?? "").localeCompare(String(a.published_at ?? ""))
      : sort === "credibility" ? num(credibilityOf(b)) - num(credibilityOf(a)) : num(relevanceOf(b)) - num(relevanceOf(a)));
  const indexOf = new Map(all.map((s, i) => [s.id, i + 1]));

  async function cite(s: ResearchSourceRef) {
    try { await navigator.clipboard.writeText(citationFor(s)); toast.success("Citation copied"); } catch { toast.error("Clipboard unavailable"); }
  }

  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-center gap-2 text-sm">
        <span className="font-medium">“{run.query}”</span>
        <StatusChip status={run.status} />
        <span className="text-muted-foreground">{run.source_count ?? all.length} sources · {fmtUsd(run.cost_usd)}</span>
      </div>

      {active && run.ai_run_id && <div className="rounded-lg border p-3"><RunProgress runId={run.ai_run_id} title="Research steps" compact /></div>}
      {active && !run.ai_run_id && <p className="text-sm text-muted-foreground">Searching → fetching → deduping → ranking → summarizing…</p>}
      {run.status === "failed" && <QueryError error={new Error(run.error || "The research run failed.")} title="Research failed" />}
      {(run.result?.partial_failures?.length ?? 0) > 0 && (
        <p className="rounded-md bg-amber-50 p-2 text-xs text-amber-900 dark:bg-amber-950/40 dark:text-amber-200">Partial failures: {run.result?.partial_failures?.join(" · ")}</p>
      )}

      {(run.result?.summary || (run.result?.findings?.length ?? 0) > 0) && (
        <details open className="rounded-lg border p-3 text-sm">
          <summary className="cursor-pointer font-medium"><span className="text-ai">✦</span> Summary of findings</summary>
          {run.result?.summary && <p className="mt-2 whitespace-pre-wrap">{run.result.summary}</p>}
          {(run.result?.findings?.length ?? 0) > 0 && (
            <ul className="mt-2 list-disc space-y-1 pl-5">
              {run.result?.findings?.map((f, i) => (
                <li key={i}>{f.text}{" "}
                  {f.source_ids?.map((sid) => (
                    <button key={sid} type="button" className="text-xs text-primary hover:underline" onClick={() => setOpenId(sid)}>[{indexOf.get(sid) ?? "src"}]</button>
                  ))}
                </li>
              ))}
            </ul>
          )}
        </details>
      )}

      <div className="flex flex-wrap items-center gap-2">
        <Select value={sort} onValueChange={(v) => setSort(v as Sort)}>
          <SelectTrigger size="sm" aria-label="Sort"><SelectValue /></SelectTrigger>
          <SelectContent><SelectItem value="relevance">Sort: relevance</SelectItem><SelectItem value="credibility">Sort: credibility</SelectItem><SelectItem value="date">Sort: date</SelectItem></SelectContent>
        </Select>
        <Select value={minCred} onValueChange={setMinCred}>
          <SelectTrigger size="sm" aria-label="Minimum credibility"><SelectValue /></SelectTrigger>
          <SelectContent><SelectItem value="0">Any credibility</SelectItem><SelectItem value="50">Medium +</SelectItem><SelectItem value="75">High only</SelectItem></SelectContent>
        </Select>
        <Input value={search} onChange={(e) => setSearch(e.target.value)} placeholder="Search results…" className="h-8 max-w-xs" aria-label="Search results" />
      </div>

      {!filtered.length ? (
        <p className="rounded-lg border border-dashed p-6 text-center text-sm text-muted-foreground">
          {active ? "Sources will stream in as they're ranked." : all.length ? "No sources match these filters." : "This run returned no sources."}
        </p>
      ) : (
        <ol className="space-y-2">
          {filtered.slice(0, limit).map((s) => {
            const domain = s.domain || domainOf(s.url ?? s.canonical_url);
            return (
              <li key={s.id} className="rounded-lg border p-3 hover:bg-accent/40">
                <div className="flex items-start gap-3">
                  <span className="w-6 shrink-0 text-right text-xs tabular-nums text-muted-foreground">{indexOf.get(s.id)}</span>
                  <Favicon domain={domain} className="mt-0.5" />
                  <div className="min-w-0 flex-1">
                    <button type="button" className="text-left text-sm font-medium hover:underline" onClick={() => setOpenId(s.id)}>{s.title || s.url || "Untitled"}</button>
                    <p className="text-xs text-muted-foreground">{domain}{s.source_kind ? ` · ${s.source_kind}` : ""} · {fmtDate(s.published_at)}</p>
                    <div className="mt-1 flex flex-wrap gap-1">
                      <RelevanceBadge value={relevanceOf(s)} />
                      <CredibilityBadge value={credibilityOf(s)} />
                      {s.injection_flag && <InjectionBadge />}
                    </div>
                    {s.summary && <p className="mt-1 line-clamp-2 text-sm text-muted-foreground">{s.summary}</p>}
                    {(s.keywords?.length ?? 0) > 0 && <p className="mt-1 text-xs text-muted-foreground">keywords: {s.keywords?.slice(0, 6).join(" · ")}</p>}
                  </div>
                  <div className="flex shrink-0 flex-col gap-1 sm:flex-row">
                    {can.create && (
                      <Button size="xs" variant="outline" disabled={s.saved || (save.isPending && save.variables === s.id)}
                              onClick={() => save.mutate(s.id, { onSuccess: () => toast.success("Saved"), onError: (e) => toast.error(errorMessage(e)) })}>
                        <Bookmark className="h-3 w-3" /> {s.saved ? "Saved" : "Save"}
                      </Button>
                    )}
                    <Button size="xs" variant="ghost" onClick={() => cite(s)}><Quote className="h-3 w-3" /> Cite</Button>
                  </div>
                </div>
              </li>
            );
          })}
        </ol>
      )}
      {filtered.length > limit && <Button variant="outline" className="w-full" onClick={() => setLimit((l) => l + 20)}>Load {Math.min(20, filtered.length - limit)} more</Button>}
      <SourceDrawer sourceId={openId} onOpenChange={(o) => { if (!o) setOpenId(null); }} />
    </div>
  );
}

"use client";
import Link from "next/link";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { ArrowLeft, Download, FileDown, Loader2, RefreshCw, Sparkles } from "lucide-react";
import { toast } from "sonner";
import { Button } from "@/components/ui/button";
import { Skeleton } from "@/components/ui/skeleton";
import { StatusChip } from "@/components/data/status-chip";
import { CostPill } from "@/features/common/components/ai-badge";
import { NotAvailable, QueryError } from "@/features/common/components/query-state";
import { RunCard } from "@/features/common/components/run-card";
import { authHeaders, useBrands, usePermissions, useWorkspacePath } from "@/features/common/hooks";
import { downloadAuthed, errorMessage, errorStatus, fmtDate, fmtDateTime, isNotAvailable, toItems } from "@/features/common/utils";
import { useSession } from "@/stores/session";
import { kindLabel, reportSections, reportSources, reportsApi, type Report } from "../api";
import { MarkdownView } from "./markdown-view";

/** Report viewer (doc 24 §18): numbered sections (✦ marked), tables with snapshot time, citations, sources appendix, export. */
export function ReportViewer({ id }: { id: string }) {
  const qc = useQueryClient();
  const ws = useWorkspacePath();
  const { canCreate } = usePermissions();
  const brands = toItems(useBrands().data);
  const workspaceId = useSession((s) => s.workspaceId);
  const q = useQuery({
    queryKey: ["reports", id], queryFn: () => reportsApi.get(id), retry: false,
    refetchInterval: (query) => (["running", "queued"].includes(query.state.data?.status ?? "") ? 3000 : false),
  });
  const exportFile = useMutation({
    mutationFn: (format: "pdf" | "markdown") => downloadAuthed(`/reports/${id}/export?format=${format}`, `${(q.data?.title ?? "report").replace(/[^\w-]+/g, "_")}.${format === "pdf" ? "pdf" : "md"}`, authHeaders()),
    onError: (e) => toast.error(isNotAvailable(e) ? "Export isn't available on this backend yet" : errorMessage(e)),
  });
  const regenerate = useMutation({
    mutationFn: (r: Report) => reportsApi.create({ kind: r.kind as "custom", brand_id: r.brand_id ?? null, title: r.title, period_start: r.period_start ?? "", period_end: r.period_end ?? "", recipients: [], format: "link" }),
    onSuccess: () => { toast.success("Regenerating as a new version"); void qc.invalidateQueries({ queryKey: ["reports"] }); },
    onError: (e) => toast.error(errorMessage(e)),
  });

  if (q.isLoading) return <div className="space-y-3"><Skeleton className="h-8 w-1/2" /><Skeleton className="h-4 w-1/3" /><Skeleton className="h-64" /></div>;
  if (q.error) {
    if (errorStatus(q.error) === 404) return <div className="py-16 text-center"><p className="font-medium">Report not found</p><p className="mt-1 text-sm text-muted-foreground">It may have been deleted, or reports aren’t enabled on this backend yet.</p><Button asChild className="mt-4" variant="outline"><Link href={ws("reports")}>Back to reports</Link></Button></div>;
    if (errorStatus(q.error) === 501) return <NotAvailable text="The report service isn't enabled yet." />;
    return <QueryError error={q.error} onRetry={() => q.refetch()} title="Couldn't load this report" />;
  }
  const r = q.data;
  if (!r) return null;
  const sections = reportSections(r);
  const sources = reportSources(r);
  const running = r.status === "running" || r.status === "queued";
  const exportHref = (f: string) => `/api/v1/reports/${id}/export?format=${f}${workspaceId ? `&workspace_id=${workspaceId}` : ""}`;

  return (
    <article className="mx-auto max-w-4xl space-y-6">
      <header className="space-y-2">
        <Link href={ws("reports")} className="inline-flex items-center gap-1 text-sm text-muted-foreground hover:underline"><ArrowLeft className="h-3.5 w-3.5" /> Reports</Link>
        <h1 className="text-2xl font-semibold tracking-tight">{r.title}</h1>
        <p className="flex flex-wrap items-center gap-2 text-sm text-muted-foreground">
          <span>{kindLabel(r.kind)}</span>
          {r.brand_id && <span>· {brands.find((b) => b.id === r.brand_id)?.name ?? "brand"}</span>}
          {r.period_start && <span>· {fmtDate(r.period_start)} – {fmtDate(r.period_end)}</span>}
          {r.status && r.status !== "completed" && <StatusChip status={r.status} />}
        </p>
        <p className="flex flex-wrap items-center gap-2 text-xs text-muted-foreground">
          <span className="inline-flex items-center gap-1 text-ai"><Sparkles className="h-3 w-3" /> report</span>
          <span>Generated {fmtDateTime(r.created_at)} · {sections.length} sections · {sources.length} sources</span>
          <CostPill usd={r.cost_usd} />
          {r.ai_run_id && <Link className="hover:underline" href={ws(`command-center/${r.ai_run_id}`)}>run ↗</Link>}
          {r.content?.data_freshness && <span>· data: {r.content.data_freshness}</span>}
        </p>
        <div className="flex flex-wrap gap-2">
          {(["pdf", "markdown"] as const).map((f) => (
            <Button key={f} size="sm" variant="outline" asChild disabled={running}>
              <a href={exportHref(f)} onClick={(e) => { e.preventDefault(); exportFile.mutate(f); }}>{f === "pdf" ? <FileDown /> : <Download />} Export {f === "pdf" ? "PDF" : "Markdown"}</a>
            </Button>
          ))}
          {canCreate && <Button size="sm" variant="outline" onClick={() => regenerate.mutate(r)} disabled={regenerate.isPending || running}>{regenerate.isPending ? <Loader2 className="animate-spin" /> : <RefreshCw />} Regenerate</Button>}
          {exportFile.isPending && <Loader2 className="h-4 w-4 animate-spin self-center" />}
        </div>
        {(r.recipients ?? []).length > 0 && <p className="text-xs text-muted-foreground">Delivered to: {r.recipients?.map((x) => `${x.value}${x.status ? ` (${x.status})` : ""}`).join(", ")}</p>}
      </header>

      {running && (r.ai_run_id ? <RunCard runId={r.ai_run_id} title="✦ report agent is composing" onDone={() => void q.refetch()} /> : <p className="flex items-center gap-2 text-sm text-muted-foreground"><Loader2 className="h-4 w-4 animate-spin" /> Generating sections…</p>)}
      {r.status === "failed" && <QueryError error={new Error(r.error ?? "Report generation failed")} title="Generation failed" onRetry={canCreate ? () => regenerate.mutate(r) : undefined} />}

      {r.content?.summary && !sections.some((s) => s.key === "summary") && <section className="rounded-lg bg-muted/40 p-4"><MarkdownView markdown={r.content.summary} /></section>}
      {sections.length === 0 && !running && r.content?.markdown && <MarkdownView markdown={r.content.markdown} />}
      {sections.map((s, i) => (
        <section key={s.key ?? i} aria-labelledby={`sec-${i}`} className="border-t pt-4">
          <h2 id={`sec-${i}`} className="flex items-center gap-2 text-lg font-semibold"><span className="text-muted-foreground tabular-nums">{i + 1}</span> {s.title}{s.ai_generated !== false && <Sparkles className="h-4 w-4 text-ai" aria-label="AI-written" />}</h2>
          {s.status === "failed" && <p className="mt-1 text-sm text-red-600">This section failed: {s.error ?? "unknown error"}</p>}
          {(s.markdown ?? s.body_md ?? s.body) && <MarkdownView markdown={s.markdown ?? s.body_md ?? s.body ?? ""} />}
          {s.table && (
            <div className="my-3 overflow-x-auto rounded-md border">
              <table className="w-full text-sm"><thead><tr>{s.table.columns.map((c) => <th key={c} className="border-b px-2 py-1 text-left font-medium">{c}</th>)}</tr></thead>
                <tbody>{s.table.rows.map((row, ri) => <tr key={ri} className="border-b last:border-0">{row.map((c, ci) => <td key={ci} className="px-2 py-1 tabular-nums">{c == null ? "n/a" : String(c)}</td>)}</tr>)}</tbody></table>
            </div>
          )}
          {s.data_snapshot_at && <p className="text-[11px] text-muted-foreground">Data: analytics snapshot {fmtDateTime(s.data_snapshot_at)}</p>}
        </section>
      ))}
      {sources.length > 0 && (
        <section aria-labelledby="sources-h" className="border-t pt-4">
          <h2 id="sources-h" className="text-lg font-semibold">Sources</h2>
          <ol className="mt-2 space-y-1 text-sm">
            {sources.map((s, i) => (
              <li key={s.id ?? i} id={`src-${s.n ?? i + 1}`} className="scroll-mt-20">
                <span className="mr-1 text-muted-foreground">[{s.n ?? i + 1}]</span>
                {s.url ? <a className="text-primary hover:underline" href={s.url} target="_blank" rel="noreferrer">{s.title ?? s.url}</a> : (s.title ?? s.description ?? s.kind ?? "source")}
                {s.domain && <span className="text-muted-foreground"> · {s.domain}</span>}{s.kind && <span className="text-muted-foreground"> · {s.kind}</span>}
              </li>
            ))}
          </ol>
        </section>
      )}
    </article>
  );
}

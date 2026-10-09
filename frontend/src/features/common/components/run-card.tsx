"use client";
import { useState } from "react";
import Link from "next/link";
import { useMutation, useQuery } from "@tanstack/react-query";
import { toast } from "sonner";
import { Ban, CheckCircle2, ChevronDown, ChevronRight, Circle, ExternalLink, Loader2, PauseCircle, Sparkles, XCircle } from "lucide-react";
import { Button } from "@/components/ui/button";
import { StatusChip } from "@/components/data/status-chip";
import { api } from "@/lib/api";
import { cn } from "@/lib/utils";
import type { AiRun, ListResponse } from "../types";
import { useRunPolling, useWorkspacePath, ACTIVE_RUN } from "../hooks";
import { errorMessage, fmtInt, fmtUsd, toItems } from "../utils";

interface ToolCall { id?: string; tool_name: string; side_effect?: string; args_summary?: string; result_summary?: string; status: string; duration_ms?: number }

export function TaskGlyph({ status }: { status: string }) {
  if (status === "succeeded" || status === "completed") return <CheckCircle2 className="h-4 w-4 text-emerald-600" aria-label="succeeded" />;
  if (status === "failed") return <XCircle className="h-4 w-4 text-red-600" aria-label="failed" />;
  if (status === "running" || status === "planning") return <Loader2 className="h-4 w-4 animate-spin text-blue-600" aria-label="running" />;
  if (status === "awaiting_approval" || status === "paused" || status === "waiting") return <PauseCircle className="h-4 w-4 text-amber-600" aria-label="awaiting approval" />;
  if (status === "skipped" || status === "cancelled") return <Ban className="h-4 w-4 text-muted-foreground" aria-label={status} />;
  return <Circle className="h-4 w-4 text-muted-foreground" aria-label="pending" />;
}

function tokensLabel(t: AiRun["tokens"]): string | null {
  if (t == null) return null;
  if (typeof t === "number") return `${fmtInt(t)} tok`;
  const total = t.total ?? Object.entries(t).filter(([k]) => k !== "cached" && k !== "cached_tokens").reduce((s, [, v]) => s + (typeof v === "number" ? v : 0), 0);
  return total ? `${fmtInt(total)} tok` : null;
}

/** Human title for a run: explicit title, the user message, or the intent label (intent may be an object). */
export function runTitle(run: AiRun | undefined | null, fallback = "AI run"): string {
  if (!run) return fallback;
  const intent = run.intent;
  const intentText = typeof intent === "string" ? intent : intent && typeof intent === "object" ? String(intent.label ?? intent.name ?? intent.intent ?? "") : "";
  return run.title || run.message || intentText || run.agent || fallback;
}

/**
 * Transparency card for an AI run (doc 23 §23.6): live step, steps checklist, sources, tool calls,
 * approvals needed, failure reason and cost. Polls until terminal.
 */
export function RunCard({ runId, title, onDone, className, compact }: {
  runId: string; title?: string; onDone?: (run: AiRun) => void; className?: string; compact?: boolean;
}) {
  const ws = useWorkspacePath();
  const { run, isLoading, error, refetch } = useRunPolling(runId, { onDone });
  const [showTools, setShowTools] = useState(false);
  const [showSources, setShowSources] = useState(!compact);
  const tools = useQuery({
    queryKey: ["ai", "runs", runId, "tool-calls"],
    queryFn: () => api.get<ListResponse<ToolCall>>(`/ai/runs/${runId}/tool-calls`),
    enabled: showTools,
    retry: false,
  });
  const cancel = useMutation({
    mutationFn: () => api.post(`/ai/runs/${runId}/cancel`),
    onSuccess: () => { toast.success("Cancel requested"); void refetch(); },
    onError: (e) => toast.error(errorMessage(e)),
  });
  const tasks = Array.isArray(run?.plan?.tasks) ? run.plan.tasks : [];
  const sources = Array.isArray(run?.result?.sources) ? run.result.sources.filter((x) => x && typeof x === "object") : [];
  const actions = Array.isArray(run?.result?.actions) ? run.result.actions.filter((x) => x && typeof x === "object") : [];
  const summary = typeof run?.result?.reasoning_summary === "string" ? run.result.reasoning_summary : typeof run?.reasoning_summary === "string" ? run.reasoning_summary : null;
  const active = run ? ACTIVE_RUN.includes(String(run.status)) : true;
  const current = tasks.find((t) => t.status === "running");
  const done = tasks.filter((t) => t.status === "succeeded").length;

  return (
    <div className={cn("rounded-lg border bg-card p-3 text-sm", className)} aria-live="polite">
      <div className="flex items-center gap-2">
        <Sparkles className="h-4 w-4 shrink-0 text-ai" aria-hidden />
        <span className="min-w-0 flex-1 truncate font-medium">{title ?? runTitle(run)}</span>
        {run ? <StatusChip status={String(run.status)} /> : isLoading ? <Loader2 className="h-4 w-4 animate-spin" /> : null}
      </div>
      {error && <p className="mt-2 text-xs text-red-600">{errorMessage(error)}</p>}
      {run && (
        <>
          {active && (
            <p className="mt-1 text-xs text-muted-foreground">
              {current ? `${current.agent ? `${current.agent} · ` : ""}${current.label}` : run.status === "queued" ? "Waiting for a worker…" : "Planning…"}
              {tasks.length > 0 && ` · step ${Math.min(done + 1, tasks.length)}/${tasks.length}`}
            </p>
          )}
          {tasks.length > 0 && (
            <ul className="mt-2 space-y-1" aria-label="Run steps">
              {tasks.map((t) => (
                <li key={t.key} className="flex items-center gap-2 text-xs">
                  <TaskGlyph status={t.status} />
                  <span className="min-w-0 flex-1 truncate">{t.label}{t.agent && <span className="ml-1 font-mono text-muted-foreground">{t.agent}</span>}</span>
                  {t.sources_count ? <span className="text-muted-foreground">{t.sources_count} src</span> : null}
                  {t.duration_ms != null && <span className="tabular-nums text-muted-foreground">{(t.duration_ms / 1000).toFixed(1)}s</span>}
                  {t.cost_usd != null && <span className="tabular-nums text-muted-foreground">{fmtUsd(t.cost_usd)}</span>}
                </li>
              ))}
            </ul>
          )}
          {tasks.some((t) => t.error) && (
            <ul className="mt-2 space-y-1">
              {tasks.filter((t) => t.error).map((t) => <li key={t.key} className="rounded bg-red-50 px-2 py-1 text-xs text-red-800 dark:bg-red-900/30 dark:text-red-200">{t.label}: {t.error}</li>)}
            </ul>
          )}
          {summary && !compact && <p className="mt-2 whitespace-pre-wrap rounded-md bg-muted p-2 text-xs">{summary}</p>}
          {run.error && <p className="mt-2 rounded-md bg-red-50 p-2 text-xs text-red-800 dark:bg-red-900/30 dark:text-red-200">{run.error}</p>}
          {actions.length > 0 && (
            <div className="mt-2 rounded-md border border-amber-300 bg-amber-50 p-2 text-xs dark:border-amber-800 dark:bg-amber-900/20">
              <p className="font-medium">Needs approval</p>
              <ul className="mt-1 space-y-1">{actions.map((a, i) => <li key={a.approval_id ?? i} className="flex items-center gap-2"><StatusChip status={a.status} /><span>{a.description}</span></li>)}</ul>
              <Link href={ws("approvals")} className="mt-1 inline-block text-primary hover:underline">Open approvals ↗</Link>
            </div>
          )}
          {sources.length > 0 && (
            <div className="mt-2">
              <button type="button" className="flex items-center gap-1 text-xs text-muted-foreground hover:text-foreground" onClick={() => setShowSources((s) => !s)} aria-expanded={showSources}>
                {showSources ? <ChevronDown className="h-3 w-3" /> : <ChevronRight className="h-3 w-3" />} {sources.length} source{sources.length === 1 ? "" : "s"} used
              </button>
              {showSources && (
                <ol className="mt-1 space-y-1 text-xs">
                  {sources.map((s, i) => (
                    <li key={s.id ?? i} className="flex items-start gap-1.5">
                      <span className="text-muted-foreground">[{i + 1}]</span>
                      <span className="min-w-0 flex-1">
                        {s.url ? <a href={s.url} target="_blank" rel="noreferrer" className="hover:underline">{s.title || s.url}</a> : (s.title ?? "Untitled")}
                        {s.domain && <span className="ml-1 text-muted-foreground">{s.domain}</span>}
                      </span>
                      {s.credibility != null && <span className="text-muted-foreground" title="Credibility">cred {Number(s.credibility).toFixed(2)}</span>}
                    </li>
                  ))}
                </ol>
              )}
            </div>
          )}
          <div className="mt-2 flex flex-wrap items-center gap-2 border-t pt-2 text-xs text-muted-foreground">
            <button type="button" className="flex items-center gap-1 hover:text-foreground" onClick={() => setShowTools((s) => !s)} aria-expanded={showTools}>
              {showTools ? <ChevronDown className="h-3 w-3" /> : <ChevronRight className="h-3 w-3" />} Tool calls
            </button>
            {tokensLabel(run.tokens) && <span>· {tokensLabel(run.tokens)}</span>}
            <span>· {fmtUsd(run.cost_usd)}</span>
            <Link href={ws(`command-center/${runId}`)} className="ml-auto inline-flex items-center gap-1 hover:text-foreground">Run <ExternalLink className="h-3 w-3" /></Link>
            {active && <Button size="xs" variant="ghost" onClick={() => cancel.mutate()} disabled={cancel.isPending}>Cancel</Button>}
          </div>
          {showTools && (
            <div className="mt-1 text-xs">
              {tools.isLoading && <p className="text-muted-foreground">Loading tool calls…</p>}
              {tools.error && <p className="text-muted-foreground">Tool call log unavailable.</p>}
              {tools.data && toItems(tools.data).length === 0 && <p className="text-muted-foreground">No tool calls.</p>}
              <ul className="space-y-1">
                {toItems(tools.data).map((t, i) => (
                  <li key={t.id ?? i} className="flex items-center gap-2">
                    <TaskGlyph status={t.status} />
                    <span className="font-mono">{t.tool_name}</span>
                    {t.side_effect && <span className="rounded border px-1 text-[10px] uppercase text-muted-foreground">{t.side_effect}</span>}
                    <span className="min-w-0 flex-1 truncate text-muted-foreground">{t.result_summary ?? t.args_summary}</span>
                    {t.duration_ms != null && <span className="tabular-nums text-muted-foreground">{t.duration_ms}ms</span>}
                  </li>
                ))}
              </ul>
            </div>
          )}
        </>
      )}
    </div>
  );
}

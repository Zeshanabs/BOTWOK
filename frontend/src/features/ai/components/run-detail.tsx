"use client";
/** Run inspector: header, live timeline with expandable step cards, failure block, right-hand panels (doc 24 §6). */
import { useEffect, useState } from "react";
import { toast } from "sonner";
import { AlertTriangle, ChevronDown, ChevronRight, Play, RotateCw, Square, Wrench } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import { Skeleton } from "@/components/ui/skeleton";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { StatusChip } from "@/components/shared/status-chip";
import { ConfirmDialog } from "@/components/shared/confirm-dialog";
import { QueryError, errorMessage } from "@/components/shared/async-states";
import { fmtCompact, fmtDuration, fmtUsd, msSince } from "@/lib/formatters";
import { useCan } from "@/lib/permissions";
import { cn } from "@/lib/utils";
import { useNow } from "@/hooks/useNow";
import { SourceDrawer } from "@/features/research/components/source-drawer";
import { useRun, useRunControls, useToolCalls } from "../hooks";
import { deliverableList, isRunActive, reasoningLines, runTitle, runTokens, type RunTask, type ToolCall } from "../types";
import { TaskGlyph } from "./task-glyph";
import { ActionsPanel, OutputPanel, ReasoningPanel, SourcesPanel } from "./run-panels";

function summary(v: ToolCall["args_summary"]): string {
  if (v == null) return "";
  if (typeof v === "string") return v;
  try { return JSON.stringify(v); } catch { return ""; }
}

function ToolCallRow({ c }: { c: ToolCall }) {
  return (
    <li className="grid grid-cols-[auto_minmax(0,1fr)_auto] items-start gap-2 py-1 text-xs">
      <TaskGlyph status={c.status === "ok" || c.status === "succeeded" || c.status === "completed" ? "succeeded" : c.status} className="h-3.5 w-3.5" />
      <div className="min-w-0">
        <p><span className="font-mono font-medium">{c.tool_name}</span>{c.side_effect && <span className="ml-1 text-muted-foreground">· {c.side_effect.toLowerCase()}</span>}</p>
        {summary(c.args_summary) && <p className="truncate text-muted-foreground" title={summary(c.args_summary)}>args: {summary(c.args_summary)}</p>}
        {summary(c.result_summary) && <p className="truncate text-muted-foreground" title={summary(c.result_summary)}>result: {summary(c.result_summary)}</p>}
        {c.error && <p className="text-destructive">{c.error}</p>}
      </div>
      <span className="tabular-nums text-muted-foreground">{fmtDuration(c.duration_ms)}</span>
    </li>
  );
}

function StepCard({ task, calls, onRetry, canRetry }: { task: RunTask; calls: ToolCall[]; onRetry?: () => void; canRetry: boolean }) {
  const tokens = (task.tokens_in ?? 0) + (task.tokens_out ?? 0);
  return (
    <div className="ml-6 mt-1 space-y-2 rounded-lg border bg-muted/30 p-3 text-xs">
      <div className="flex flex-wrap gap-x-3 gap-y-1 text-muted-foreground">
        {task.agent && <span>agent <span className="font-medium text-foreground">{task.agent}</span></span>}
        {(task.tier || task.model) && <span>{task.tier}{task.tier && task.model ? " → " : ""}{task.model}</span>}
        {tokens > 0 && <span>{fmtCompact(tokens)} tok</span>}
        {task.cost_usd != null && <span>{fmtUsd(task.cost_usd, 4)}</span>}
        {task.sources_count != null && <span>{task.sources_count} sources</span>}
        {task.requires_approval && <span className="text-warning">approval gate</span>}
      </div>
      {task.output_summary && <p className="whitespace-pre-wrap">{task.output_summary}</p>}
      {task.error && <p className="text-destructive">{task.error}</p>}
      <div>
        <p className="mb-1 flex items-center gap-1 font-medium"><Wrench className="h-3 w-3" /> Tool calls ({calls.length})</p>
        {calls.length ? <ul className="divide-y">{calls.map((c) => <ToolCallRow key={c.id} c={c} />)}</ul> : <p className="text-muted-foreground">No tool calls recorded for this step.</p>}
      </div>
      {task.status === "failed" && canRetry && onRetry && <Button size="xs" variant="outline" onClick={onRetry}><RotateCw className="h-3 w-3" /> Retry step</Button>}
    </div>
  );
}

export function RunDetail({ runId, followUp }: { runId: string; followUp?: React.ReactNode }) {
  const can = useCan();
  const { data: run, isLoading, error, refetch } = useRun(runId);
  const active = isRunActive(run?.status);
  const toolCalls = useToolCalls(runId, active);
  const { cancel, resume } = useRunControls(runId);
  const now = useNow(active);
  const [expanded, setExpanded] = useState<Record<string, boolean>>({});
  const [confirmCancel, setConfirmCancel] = useState(false);
  const [sourceId, setSourceId] = useState<string | null>(null);
  const [tab, setTab] = useState<string | null>(null);

  const cancellable = !!run && ["queued", "planning", "running", "awaiting_approval", "paused"].includes(run.status);

  // ⌘. cancels the focused run
  useEffect(() => {
    const h = (e: KeyboardEvent) => {
      if ((e.metaKey || e.ctrlKey) && e.key === "." && cancellable && can.create) { e.preventDefault(); setConfirmCancel(true); }
    };
    window.addEventListener("keydown", h);
    return () => window.removeEventListener("keydown", h);
  }, [cancellable, can.create]);

  if (isLoading) {
    return <div className="space-y-3" aria-busy="true"><Skeleton className="h-8 w-2/3" /><Skeleton className="h-5 w-1/2" />{Array.from({ length: 5 }).map((_, i) => <Skeleton key={i} className="h-8 w-full" />)}</div>;
  }
  if (error || !run) return <QueryError error={error} onRetry={() => refetch()} title="Couldn't load this run" notFoundText="This run doesn't exist in this workspace." />;

  const tasks = run.plan?.tasks ?? [];
  const calls = toolCalls.data ?? [];
  const linked = calls.some((c) => c.task_key || c.task_id);
  const callsFor = (t: RunTask) => calls.filter((c) => (c.task_key && c.task_key === t.key) || (t.id && c.task_id === t.id));
  const done = tasks.filter((t) => t.status === "succeeded").length;
  const failedTasks = tasks.filter((t) => t.status === "failed");
  const failedCalls = calls.filter((c) => c.status === "failed" || c.status === "error");
  const actions = run.result?.actions ?? [];
  const pendingActions = actions.filter((a) => a.status === "pending");
  const deliverables = deliverableList(run.result?.deliverables);
  const sources = run.result?.sources ?? [];
  const reasoning = reasoningLines(run.result?.reasoning_summary ?? run.reasoning_summary);
  const startedAgo = msSince(run.started_at ?? run.created_at ?? run.queued_at, now);
  const finishedAgo = run.finished_at ? msSince(run.finished_at, now) ?? 0 : 0;
  const elapsed = startedAgo !== null ? startedAgo - finishedAgo : null;
  const tokens = runTokens(run);
  const currentTab = tab ?? (pendingActions.length || run.status === "awaiting_approval" ? "actions" : deliverables.length ? "output" : "sources");

  function retry(taskId?: string) {
    resume.mutate(taskId, { onSuccess: () => toast.success("Retrying"), onError: (e) => toast.error(errorMessage(e)) });
  }

  return (
    <div className="grid gap-6 xl:grid-cols-[minmax(0,1fr)_360px]">
      <section className="min-w-0 space-y-4" aria-label="Run timeline">
        <header className="space-y-2">
          <h2 className="text-lg font-semibold leading-tight">{runTitle(run)}</h2>
          <div className="flex flex-wrap items-center gap-x-3 gap-y-1 text-xs text-muted-foreground">
            <span className="font-mono">{run.id.slice(0, 13)}…</span>
            <StatusChip status={run.status} />
            {tasks.length > 0 && <span>step {Math.min(done + (active ? 1 : 0), tasks.length)}/{tasks.length}</span>}
            {elapsed !== null && elapsed > 0 && <span className="tabular-nums">{fmtDuration(elapsed)}</span>}
            {tokens !== null && <span className="tabular-nums">{fmtCompact(tokens)} tok</span>}
            <span className="tabular-nums">{fmtUsd(run.cost_usd)}</span>
            <span className="ml-auto flex gap-2">
              {can.create && (run.status === "paused" || run.status === "failed") && (
                <Button size="sm" variant="outline" onClick={() => retry(failedTasks[0]?.id)} disabled={resume.isPending}><Play className="h-3 w-3" /> {run.status === "failed" ? "Retry from failed step" : "Resume"}</Button>
              )}
              {can.create && cancellable && (
                <Button size="sm" variant="outline" onClick={() => setConfirmCancel(true)}><Square className="h-3 w-3" /> Cancel <kbd className="hidden text-[10px] sm:inline">⌘.</kbd></Button>
              )}
            </span>
          </div>
        </header>

        {(run.message || run.input?.message) && (
          <div className="rounded-lg bg-muted/60 p-3 text-sm"><span className="mr-2 text-xs font-medium text-muted-foreground">You</span>{run.message || run.input?.message}</div>
        )}

        {(run.status === "failed" || failedTasks.length > 0 || failedCalls.length > 0) && (
          <div className="rounded-lg border border-destructive/40 bg-destructive/[0.06] p-3 text-sm text-destructive" role="alert">
            <p className="flex items-center gap-1 font-semibold"><AlertTriangle className="h-4 w-4" /> What failed</p>
            <ul className="mt-1 space-y-1 text-xs">
              {failedTasks.map((t) => <li key={t.key}>Step {t.key} {t.agent ? `· ${t.agent}` : ""} — {t.label}{t.error ? `: ${t.error}` : ""}</li>)}
              {failedCalls.map((c) => <li key={c.id}>Tool <span className="font-mono">{c.tool_name}</span>{c.error ? `: ${c.error}` : " failed"}{run.status !== "failed" ? " (recovered)" : ""}</li>)}
              {run.error && <li>{run.error}</li>}
            </ul>
            {can.create && failedTasks.length > 0 && <Button size="xs" variant="outline" className="mt-2" onClick={() => retry(failedTasks[0].id)}><RotateCw className="h-3 w-3" /> Retry failed</Button>}
          </div>
        )}

        <ol className="space-y-1" aria-live="polite">
          <li className="flex items-center gap-2 rounded-md px-2 py-1.5 text-sm">
            <TaskGlyph status={run.status === "queued" ? "pending" : tasks.length || !active ? "succeeded" : "planning"} />
            <span className="flex-1">{run.status === "queued" ? `Queued${run.queue_position ? ` · position ${run.queue_position}` : "…"}` : "Planning"}{tasks.length > 0 && <span className="ml-2 text-xs text-muted-foreground">plan v{run.plan?.version ?? 1} · {tasks.length} steps</span>}</span>
          </li>
          {tasks.map((t) => {
            const open = !!expanded[t.key];
            const live = t.status === "running" && t.started_at ? msSince(t.started_at, now) : null;
            return (
              <li key={t.key}>
                <button type="button" aria-expanded={open} onClick={() => setExpanded((x) => ({ ...x, [t.key]: !open }))}
                        className={cn("flex w-full items-center gap-2 rounded-md px-2 py-1.5 text-left text-sm hover:bg-accent", t.status === "failed" && "bg-destructive/[0.06]/60")}>
                  <TaskGlyph status={t.status} />
                  <span className="w-8 shrink-0 font-mono text-xs text-muted-foreground">{t.key}</span>
                  {t.agent && <Badge variant="outline" className="hidden sm:inline-flex">{t.agent}</Badge>}
                  <span className={cn("min-w-0 flex-1 truncate", t.status === "skipped" && "text-muted-foreground line-through")}>{t.label}</span>
                  {t.status === "awaiting_approval" && <span className="text-xs text-warning">⏸ gate</span>}
                  <span className="text-xs tabular-nums text-muted-foreground">{t.duration_ms != null ? fmtDuration(t.duration_ms) : live ? `${fmtDuration(live)}…` : ""}</span>
                  {t.cost_usd != null && <span className="hidden w-16 text-right text-xs tabular-nums text-muted-foreground sm:inline">{fmtUsd(t.cost_usd)}</span>}
                  {open ? <ChevronDown className="h-4 w-4 text-muted-foreground" /> : <ChevronRight className="h-4 w-4 text-muted-foreground" />}
                </button>
                {open && <StepCard task={t} calls={linked ? callsFor(t) : []} canRetry={can.create} onRetry={() => retry(t.id)} />}
              </li>
            );
          })}
        </ol>

        {!linked && calls.length > 0 && (
          <details className="rounded-lg border p-3 text-sm">
            <summary className="cursor-pointer font-medium">All tool calls ({calls.length})</summary>
            <ul className="mt-2 divide-y">{calls.map((c) => <ToolCallRow key={c.id} c={c} />)}</ul>
          </details>
        )}
        {toolCalls.error != null && <QueryError error={toolCalls.error} onRetry={() => toolCalls.refetch()} title="Couldn't load tool calls" notAvailableText="Tool-call details aren't available on this install yet." />}

        <footer className="flex flex-wrap items-center justify-between gap-2 border-t pt-3 text-xs text-muted-foreground">
          <span>Side effects are always proposed for approval — never executed silently.</span>
          <span className="tabular-nums">{tokens !== null ? `${fmtCompact(tokens)} tokens · ` : ""}total {fmtUsd(run.cost_usd, 4)}</span>
        </footer>
        {followUp}
      </section>

      <aside className="min-w-0" aria-label="Run results">
        <Tabs value={currentTab} onValueChange={setTab}>
          <TabsList className="w-full">
            <TabsTrigger value="actions" className={pendingActions.length ? "text-warning" : undefined}>Actions{actions.length ? ` ${pendingActions.length || actions.length}` : ""}</TabsTrigger>
            <TabsTrigger value="output">Output{deliverables.length ? ` ${deliverables.length}` : ""}</TabsTrigger>
            <TabsTrigger value="sources">Sources{sources.length ? ` ${sources.length}` : ""}</TabsTrigger>
            <TabsTrigger value="why">Why</TabsTrigger>
          </TabsList>
          <TabsContent value="actions"><ActionsPanel actions={actions} /></TabsContent>
          <TabsContent value="output"><OutputPanel deliverables={deliverables} /></TabsContent>
          <TabsContent value="sources"><SourcesPanel sources={sources} onOpen={setSourceId} /></TabsContent>
          <TabsContent value="why"><ReasoningPanel lines={reasoning} /></TabsContent>
        </Tabs>
      </aside>

      <ConfirmDialog open={confirmCancel} onOpenChange={setConfirmCancel} title="Cancel this run?" confirmLabel="Cancel run" busy={cancel.isPending}
                     description="Completed steps and drafts are kept; pending actions are withdrawn."
                     onConfirm={() => cancel.mutate(undefined, { onSuccess: () => { toast.success("Run cancelled"); setConfirmCancel(false); }, onError: (e) => toast.error(errorMessage(e)) })} />
      <SourceDrawer sourceId={sourceId} onOpenChange={(o) => { if (!o) setSourceId(null); }} />
    </div>
  );
}


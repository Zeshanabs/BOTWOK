"use client";
/**
 * RunProgress — compact live view of an AI run: plan checklist (✓/⟳/✗ + durations + cost), total cost and
 * "what failed". Polls GET /ai/runs/{id} every 1.5 s while active and refetches on AI_RUN_* SSE events.
 * Shared: any screen that starts a run (ideas, trends, reports, studio…) can drop this in.
 */
import { useEffect, useRef } from "react";
import Link from "next/link";
import { AlertTriangle, ExternalLink } from "lucide-react";
import { StatusChip } from "@/components/data/status-chip";
import { QueryError } from "@/components/data/async-states";
import { Skeleton } from "@/components/ui/skeleton";
import { fmtDuration, fmtUsd, msSince } from "@/lib/formatters";
import { cn } from "@/lib/utils";
import { useNow } from "@/hooks/useNow";
import { useSession } from "@/stores/session";
import { useRun } from "../hooks";
import { isRunActive, isRunTerminal, type AiRun } from "../types";
import { TaskGlyph } from "./task-glyph";

export interface RunProgressProps {
  runId: string;
  /** Optional heading shown above the checklist. */
  title?: string;
  /** Hide per-step cost and the inspector link for tight spaces. */
  compact?: boolean;
  /** Called once when the run reaches a terminal status (completed/failed/cancelled). */
  onFinished?: (run: AiRun) => void;
  className?: string;
}

export function RunProgress({ runId, title, compact, onFinished, className }: RunProgressProps) {
  const slug = useSession((s) => s.workspaceSlug);
  const { data: run, isLoading, error, refetch } = useRun(runId);
  const active = isRunActive(run?.status);
  const now = useNow(active);
  const finishedRef = useRef<string | null>(null);

  useEffect(() => {
    if (run && isRunTerminal(run.status) && finishedRef.current !== run.id) {
      finishedRef.current = run.id;
      onFinished?.(run);
    }
  }, [run, onFinished]);

  if (isLoading) {
    return (
      <div className={cn("space-y-2", className)} aria-busy="true">
        <Skeleton className="h-5 w-40" />
        <Skeleton className="h-4 w-full" />
        <Skeleton className="h-4 w-3/4" />
      </div>
    );
  }
  if (error || !run) return <QueryError error={error} onRetry={() => refetch()} title="Couldn't load run progress" className={className} />;

  const tasks = run.plan?.tasks ?? [];
  const done = tasks.filter((t) => t.status === "succeeded").length;
  const failedTasks = tasks.filter((t) => t.status === "failed");
  const startedMs = msSince(run.started_at ?? run.created_at ?? run.queued_at, now);
  const endMs = run.finished_at ? msSince(run.finished_at, now) : 0;
  const elapsed = startedMs !== null ? startedMs - (endMs ?? 0) : null;

  return (
    <div className={cn("space-y-3 text-sm", className)} aria-live="polite">
      <div className="flex flex-wrap items-center gap-2">
        {title && <span className="font-medium">{title}</span>}
        <StatusChip status={run.status} />
        {tasks.length > 0 && <span className="text-xs text-muted-foreground">step {Math.min(done + (active ? 1 : 0), tasks.length)}/{tasks.length}</span>}
        {elapsed !== null && elapsed > 0 && <span className="text-xs tabular-nums text-muted-foreground">{fmtDuration(elapsed)}</span>}
        <span className="ml-auto text-xs tabular-nums text-muted-foreground">Cost {fmtUsd(run.cost_usd)}</span>
      </div>

      <ul className="space-y-1.5">
        <li className="flex items-center gap-2">
          <TaskGlyph status={run.status === "queued" ? "pending" : tasks.length || !active ? "succeeded" : "planning"} />
          <span className="flex-1 text-muted-foreground">
            {run.status === "queued" ? `Queued${run.queue_position ? ` · position ${run.queue_position}` : "…"}` : tasks.length ? `Planned · ${tasks.length} steps${run.plan?.version ? ` · plan v${run.plan.version}` : ""}` : active ? "Planning…" : "No plan recorded"}
          </span>
        </li>
        {tasks.map((t) => (
          <li key={t.key} className="flex items-center gap-2">
            <TaskGlyph status={t.status} />
            <span className={cn("min-w-0 flex-1 truncate", t.status === "skipped" && "text-muted-foreground line-through")}>
              {t.label}
              {t.agent && !compact && <span className="ml-1 text-xs text-muted-foreground">· {t.agent}</span>}
            </span>
            {t.duration_ms != null && <span className="text-xs tabular-nums text-muted-foreground">{fmtDuration(t.duration_ms)}</span>}
            {!compact && t.cost_usd != null && <span className="w-16 text-right text-xs tabular-nums text-muted-foreground">{fmtUsd(t.cost_usd)}</span>}
          </li>
        ))}
      </ul>

      {(run.error || failedTasks.length > 0) && (
        <div className="rounded-md border border-red-200 bg-red-50 p-3 text-red-800 dark:border-red-900 dark:bg-red-950/40 dark:text-red-200" role="alert">
          <p className="flex items-center gap-1 font-medium"><AlertTriangle className="h-4 w-4" /> What failed</p>
          {failedTasks.map((t) => <p key={t.key} className="mt-1 text-xs">Step “{t.label}”{t.error ? `: ${t.error}` : ""}</p>)}
          {run.error && <p className="mt-1 text-xs">{run.error}</p>}
        </div>
      )}

      {!compact && slug && (
        <Link href={`/w/${slug}/command-center/${run.id}`} className="inline-flex items-center gap-1 text-xs text-primary hover:underline">
          Open in Command Center <ExternalLink className="h-3 w-3" />
        </Link>
      )}
    </div>
  );
}

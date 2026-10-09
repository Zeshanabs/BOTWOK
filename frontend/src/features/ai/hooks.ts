"use client";
import { useEffect } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { onEvent } from "@/hooks/useSSE";
import { toItems } from "@/lib/formatters";
import { aiApi } from "./api";
import { isRunActive, type StartRunInput } from "./types";

export const aiKeys = {
  runs: (filters: Record<string, unknown> = {}) => ["ai", "runs", "list", filters] as const,
  run: (id: string) => ["ai", "runs", id] as const,
  toolCalls: (id: string) => ["ai", "runs", id, "tool-calls"] as const,
};

/** Live run: polls every 1.5 s while queued/planning/running and refetches on AI_RUN_* SSE events for this run. */
export function useRun(runId: string | null | undefined) {
  const qc = useQueryClient();
  const query = useQuery({
    queryKey: aiKeys.run(runId ?? "none"),
    queryFn: () => aiApi.getRun(runId as string),
    enabled: !!runId,
    refetchInterval: (q) => (isRunActive(q.state.data?.status) || (!q.state.data && !q.state.error) ? 1500 : false),
  });
  useEffect(() => {
    if (!runId) return;
    return onEvent((e) => {
      if (!e.name.startsWith("AI_RUN")) return;
      const p = e.payload ?? {};
      if (p.run_id === runId || p.ai_run_id === runId || p.id === runId) {
        qc.invalidateQueries({ queryKey: aiKeys.run(runId) });
      }
    });
  }, [runId, qc]);
  return query;
}

export function useRuns(filters: { status?: string; brand_id?: string | null } = {}) {
  return useQuery({
    queryKey: aiKeys.runs(filters),
    queryFn: async () => toItems(await aiApi.listRuns({ limit: 50, ...filters })),
    refetchInterval: (q) => ((q.state.data ?? []).some((r) => isRunActive(r.status)) ? 5000 : false),
  });
}

export function useToolCalls(runId: string | null | undefined, live: boolean) {
  return useQuery({
    queryKey: aiKeys.toolCalls(runId ?? "none"),
    queryFn: async () => toItems(await aiApi.toolCalls(runId as string)),
    enabled: !!runId,
    refetchInterval: live ? 3000 : false,
  });
}

export function useStartRun() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (body: StartRunInput) => aiApi.startRun(body),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["ai", "runs", "list"] }),
  });
}

export function useRunControls(runId: string) {
  const qc = useQueryClient();
  const invalidate = () => qc.invalidateQueries({ queryKey: ["ai", "runs"] });
  const cancel = useMutation({ mutationFn: () => aiApi.cancelRun(runId), onSettled: invalidate });
  const resume = useMutation({ mutationFn: (retryTaskId?: string) => aiApi.resumeRun(runId, retryTaskId ? { retry_task_id: retryTaskId } : undefined), onSettled: invalidate });
  return { cancel, resume };
}

export function useApprovalDecision() {
  const qc = useQueryClient();
  const invalidate = () => { qc.invalidateQueries({ queryKey: ["ai", "runs"] }); qc.invalidateQueries({ queryKey: ["approvals"] }); };
  const approve = useMutation({ mutationFn: (v: { id: string; comment?: string }) => aiApi.approve(v.id, v.comment), onSettled: invalidate });
  const reject = useMutation({ mutationFn: (v: { id: string; comment: string }) => aiApi.reject(v.id, v.comment), onSettled: invalidate });
  return { approve, reject };
}

export function useRequestContentApproval() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (contentId: string) => aiApi.requestContentApproval(contentId),
    onSuccess: () => { qc.invalidateQueries({ queryKey: ["content"] }); qc.invalidateQueries({ queryKey: ["approvals"] }); },
  });
}

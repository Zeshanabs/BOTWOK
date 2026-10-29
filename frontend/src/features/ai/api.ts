import { api, qs } from "@/lib/api";
import type { Page } from "@/lib/formatters";
import type { AiRun, StartRunInput, StartRunResponse, ToolCall } from "./types";

export const aiApi = {
  listRuns: (params: { limit?: number; status?: string; brand_id?: string | null; cursor?: string } = {}) =>
    api.get<Page<AiRun> | AiRun[]>(`/ai/runs${qs({ limit: params.limit ?? 30, status: params.status, brand_id: params.brand_id, cursor: params.cursor })}`),
  getRun: (id: string) => api.get<AiRun>(`/ai/runs/${id}`),
  toolCalls: (id: string) => api.get<Page<ToolCall> | ToolCall[]>(`/ai/runs/${id}/tool-calls?limit=200`),
  startRun: (body: StartRunInput) => api.post<StartRunResponse>("/ai/runs", body),
  cancelRun: (id: string) => api.post<unknown>(`/ai/runs/${id}/cancel`),
  resumeRun: (id: string, body?: { retry_task_id?: string }) => api.post<unknown>(`/ai/runs/${id}/resume`, body ?? {}),
  approve: (approvalId: string, comment?: string) => api.post<unknown>(`/approvals/${approvalId}/approve`, comment ? { comment } : {}),
  reject: (approvalId: string, comment: string) => api.post<unknown>(`/approvals/${approvalId}/reject`, { comment }),
  requestContentApproval: (contentId: string) => api.post<unknown>(`/content/${contentId}/request-approval`, {}),
};

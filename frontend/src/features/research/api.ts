import { api, qs } from "@/lib/api";
import type { Page } from "@/lib/formatters";
import type { ResearchRun, ResearchRunInput, ResearchSourceDetail, ResearchSourceRef } from "./types";

export const researchApi = {
  runs: (params: { brand_id?: string | null; limit?: number } = {}) => api.get<Page<ResearchRun> | ResearchRun[]>(`/research/runs${qs({ brand_id: params.brand_id, limit: params.limit ?? 50 })}`),
  run: (id: string) => api.get<ResearchRun>(`/research/runs/${id}`),
  start: (body: ResearchRunInput) => api.post<{ run_id: string; ai_run_id?: string | null; id?: string }>("/research/runs", body),
  sources: (params: { q?: string; domain?: string; competitor_id?: string; min_credibility?: number; since?: string; limit?: number }) =>
    api.get<Page<ResearchSourceRef> | ResearchSourceRef[]>(`/research/sources${qs({ ...params, limit: params.limit ?? 50 })}`),
  source: (id: string) => api.get<ResearchSourceDetail>(`/research/sources/${id}`),
  save: (id: string) => api.post<unknown>(`/research/sources/${id}/save`, {}),
};

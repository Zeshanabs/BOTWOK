import { api, qs } from "@/lib/api";
import type { Page } from "@/lib/formatters";
import type { CompareResponse, Competitor, CompetitorCreateInput, CompetitorPost, CompetitorReport, CompetitorSnapshot } from "./types";

export const competitorsApi = {
  list: (brandId?: string | null) => api.get<Page<Competitor> | Competitor[]>(`/competitors${qs({ brand_id: brandId, limit: 100 })}`),
  get: (id: string) => api.get<Competitor>(`/competitors/${id}`),
  create: (body: CompetitorCreateInput) => api.post<Competitor>("/competitors", body),
  update: (id: string, body: Partial<CompetitorCreateInput> & { status?: string }) => api.patch<Competitor>(`/competitors/${id}`, body),
  remove: (id: string) => api.delete<unknown>(`/competitors/${id}`),
  sync: (id: string) => api.post<{ job_id?: string }>(`/competitors/${id}/sync`, {}),
  posts: (id: string, params: { platform?: string; limit?: number } = {}) => api.get<Page<CompetitorPost> | CompetitorPost[]>(`/competitors/${id}/posts${qs({ platform: params.platform, limit: params.limit ?? 100 })}`),
  snapshots: (id: string) => api.get<Page<CompetitorSnapshot> | CompetitorSnapshot[]>(`/competitors/${id}/snapshots?limit=200`),
  compare: (ids: string[], period = "90d") => api.get<CompareResponse>(`/competitors/compare${qs({ ids: ids.join(","), period })}`),
  reports: (id: string) => api.get<Page<CompetitorReport> | CompetitorReport[]>(`/competitors/${id}/reports`),
  createReport: (id: string, body: { competitor_ids: string[]; period: string; compare_with_brand: boolean; sections: string[] }) =>
    api.post<{ run_id?: string; report_id?: string; id?: string }>(`/competitors/${id}/reports`, body),
};

import { api, qs } from "@/lib/api";
import type { Page } from "@/lib/formatters";
import type { Trend, TrendDetail } from "./types";

export const trendsApi = {
  list: (params: { brand_id?: string | null; status?: string; min_score?: number } = {}) =>
    api.get<Page<Trend> | Trend[]>(`/trends${qs({ brand_id: params.brand_id, status: params.status, min_score: params.min_score, limit: 100 })}`),
  get: (id: string) => api.get<TrendDetail>(`/trends/${id}`),
  scan: (brandId: string) => api.post<{ run_id?: string; job_id?: string }>("/trends/scan", { brand_id: brandId }),
};

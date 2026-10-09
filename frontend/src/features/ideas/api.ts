import { api, qs } from "@/lib/api";
import type { Page } from "@/lib/formatters";
import type { GenerateIdeasInput, Idea } from "./types";

export const ideasApi = {
  list: (params: { brand_id?: string | null; status?: string } = {}) => api.get<Page<Idea> | Idea[]>(`/ideas${qs({ brand_id: params.brand_id, status: params.status, limit: 200 })}`),
  create: (body: Partial<Idea> & { brand_id: string; title: string }) => api.post<Idea>("/ideas", body),
  update: (id: string, body: Partial<Pick<Idea, "status" | "title" | "angle" | "pillar_id" | "platforms" | "content_type">>) => api.patch<Idea>(`/ideas/${id}`, body),
  remove: (id: string) => api.delete<unknown>(`/ideas/${id}`),
  generate: (body: GenerateIdeasInput) => api.post<{ run_id: string }>("/ideas/generate", body),
  promote: (id: string) => api.post<{ content_id?: string; id?: string; content_item_id?: string }>(`/ideas/${id}/promote`, {}),
};

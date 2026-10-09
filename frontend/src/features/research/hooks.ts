"use client";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { toItems } from "@/lib/formatters";
import { researchApi } from "./api";
import { ACTIVE_RESEARCH, type ResearchRunInput } from "./types";

export const researchKeys = {
  runs: (brandId?: string | null) => ["research", "runs", { brandId: brandId ?? null }] as const,
  run: (id: string) => ["research", "runs", id] as const,
  sources: (filters: Record<string, unknown>) => ["research", "sources", filters] as const,
  source: (id: string) => ["research", "source", id] as const,
};

export function useResearchRuns(brandId?: string | null) {
  return useQuery({
    queryKey: researchKeys.runs(brandId),
    queryFn: async () => toItems(await researchApi.runs({ brand_id: brandId })),
    refetchInterval: (q) => ((q.state.data ?? []).some((r) => ACTIVE_RESEARCH.includes(r.status)) ? 5000 : false),
  });
}

export function useResearchRun(id: string | null | undefined) {
  return useQuery({
    queryKey: researchKeys.run(id ?? "none"),
    queryFn: () => researchApi.run(id as string),
    enabled: !!id,
    refetchInterval: (q) => (ACTIVE_RESEARCH.includes(q.state.data?.status ?? "") ? 2000 : false),
  });
}

export function useResearchSources(filters: { competitor_id?: string; q?: string }, enabled = true) {
  return useQuery({
    queryKey: researchKeys.sources(filters),
    queryFn: async () => toItems(await researchApi.sources(filters)),
    enabled,
  });
}

export function useResearchSource(id: string | null | undefined) {
  return useQuery({ queryKey: researchKeys.source(id ?? "none"), queryFn: () => researchApi.source(id as string), enabled: !!id });
}

export function useStartResearch() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (body: ResearchRunInput) => researchApi.start(body),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["research", "runs"] }),
  });
}

export function useSaveSource() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (id: string) => researchApi.save(id),
    onSuccess: (_d, id) => { qc.invalidateQueries({ queryKey: researchKeys.source(id) }); qc.invalidateQueries({ queryKey: ["research", "runs"] }); },
  });
}

"use client";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { toItems } from "@/lib/formatters";
import { competitorsApi } from "./api";
import type { CompetitorCreateInput } from "./types";

export const competitorKeys = {
  list: (brandId?: string | null) => ["competitors", "list", brandId ?? null] as const,
  detail: (id: string) => ["competitors", id] as const,
  posts: (id: string) => ["competitors", id, "posts"] as const,
  snapshots: (id: string) => ["competitors", id, "snapshots"] as const,
  reports: (id: string) => ["competitors", id, "reports"] as const,
  compare: (ids: string[]) => ["competitors", "compare", ids] as const,
};

const syncing = (s?: string | null) => s === "syncing" || s === "running" || s === "queued";

export function useCompetitors(brandId: string | null | undefined) {
  return useQuery({
    queryKey: competitorKeys.list(brandId),
    queryFn: async () => toItems(await competitorsApi.list(brandId)),
    refetchInterval: (q) => ((q.state.data ?? []).some((c) => syncing(c.sync_status) || (c.profiles ?? []).some((p) => syncing(p.sync_status))) ? 4000 : false),
  });
}

export function useCompetitor(id: string) {
  return useQuery({
    queryKey: competitorKeys.detail(id),
    queryFn: () => competitorsApi.get(id),
    refetchInterval: (q) => (syncing(q.state.data?.sync_status) || (q.state.data?.profiles ?? []).some((p) => syncing(p.sync_status)) ? 4000 : false),
  });
}

export function useCompetitorPosts(id: string, enabled = true) {
  return useQuery({ queryKey: competitorKeys.posts(id), queryFn: async () => toItems(await competitorsApi.posts(id)), enabled });
}
export function useCompetitorSnapshots(id: string, enabled = true) {
  return useQuery({ queryKey: competitorKeys.snapshots(id), queryFn: async () => toItems(await competitorsApi.snapshots(id)), enabled });
}
export function useCompetitorReports(id: string, enabled = true) {
  return useQuery({ queryKey: competitorKeys.reports(id), queryFn: async () => toItems(await competitorsApi.reports(id)), enabled });
}
export function useCompare(ids: string[], period: string) {
  return useQuery({ queryKey: [...competitorKeys.compare(ids), period], queryFn: () => competitorsApi.compare(ids, period), enabled: ids.length >= 2 });
}

export function useCompetitorMutations() {
  const qc = useQueryClient();
  const invalidate = () => qc.invalidateQueries({ queryKey: ["competitors"] });
  return {
    create: useMutation({ mutationFn: (body: CompetitorCreateInput) => competitorsApi.create(body), onSuccess: invalidate }),
    sync: useMutation({ mutationFn: (id: string) => competitorsApi.sync(id), onSuccess: invalidate }),
    remove: useMutation({ mutationFn: (id: string) => competitorsApi.remove(id), onSuccess: invalidate }),
    createReport: useMutation({
      mutationFn: (v: { id: string; period: string; sections: string[]; competitorIds?: string[] }) =>
        competitorsApi.createReport(v.id, { competitor_ids: v.competitorIds ?? [v.id], period: v.period, compare_with_brand: true, sections: v.sections }),
      onSuccess: (_d, v) => qc.invalidateQueries({ queryKey: competitorKeys.reports(v.id) }),
    }),
  };
}

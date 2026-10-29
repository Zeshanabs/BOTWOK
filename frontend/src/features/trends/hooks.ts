"use client";
import { useEffect } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { onEvent } from "@/hooks/useSSE";
import { toItems } from "@/lib/formatters";
import { trendsApi } from "./api";

export const trendKeys = {
  list: (brandId?: string | null, status?: string) => ["trends", "list", brandId ?? null, status ?? "all"] as const,
  detail: (id: string) => ["trends", id] as const,
};

export function useTrends(brandId: string | null | undefined, status?: string) {
  const qc = useQueryClient();
  useEffect(() => onEvent((e) => { if (e.name.startsWith("TREND_")) qc.invalidateQueries({ queryKey: ["trends"] }); }), [qc]);
  return useQuery({
    queryKey: trendKeys.list(brandId, status),
    queryFn: async () => toItems(await trendsApi.list({ brand_id: brandId, status: status === "all" ? undefined : status })),
    enabled: !!brandId,
  });
}

export function useTrend(id: string | null) {
  return useQuery({ queryKey: trendKeys.detail(id ?? "none"), queryFn: () => trendsApi.get(id as string), enabled: !!id });
}

export function useScanTrends() {
  const qc = useQueryClient();
  return useMutation({ mutationFn: (brandId: string) => trendsApi.scan(brandId), onSuccess: () => qc.invalidateQueries({ queryKey: ["trends"] }) });
}

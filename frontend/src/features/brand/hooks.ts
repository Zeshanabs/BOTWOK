"use client";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { toItems } from "@/lib/formatters";
import { useSession } from "@/stores/session";
import { brandApi } from "./api";
import type { BrandCreateInput, BrandSettingsUpdate, PillarInput } from "./types";

export const brandKeys = {
  // ["brands"] is shared with the header's brand switcher
  list: ["brands"] as const,
  detail: (id: string) => ["brands", id] as const,
  settings: (id: string) => ["brands", id, "settings"] as const,
  pillars: (id: string) => ["brands", id, "pillars"] as const,
  context: (id: string) => ["brands", id, "context"] as const,
};

export function useBrands() {
  const ws = useSession((s) => s.workspaceId);
  return useQuery({ queryKey: brandKeys.list, queryFn: () => brandApi.list(), enabled: !!ws, select: (d) => toItems(d) });
}

/** Active brand id from the header switcher (falls back to the first brand). */
export function useActiveBrandId(): string | null {
  const brandId = useSession((s) => s.brandId);
  const brands = useBrands();
  return brandId ?? brands.data?.[0]?.id ?? null;
}

export function useBrand(id: string | null | undefined) {
  return useQuery({ queryKey: brandKeys.detail(id ?? "none"), queryFn: () => brandApi.get(id as string), enabled: !!id });
}

export function useBrandSettings(id: string | null | undefined) {
  return useQuery({ queryKey: brandKeys.settings(id ?? "none"), queryFn: () => brandApi.settings(id as string), enabled: !!id });
}

export function usePillars(id: string | null | undefined) {
  return useQuery({ queryKey: brandKeys.pillars(id ?? "none"), queryFn: async () => toItems(await brandApi.pillars(id as string)), enabled: !!id });
}

export function useBrandContext(id: string | null | undefined, enabled = true) {
  return useQuery({ queryKey: brandKeys.context(id ?? "none"), queryFn: () => brandApi.context(id as string), enabled: !!id && enabled });
}

export function useCreateBrand() {
  const qc = useQueryClient();
  return useMutation({ mutationFn: (body: BrandCreateInput) => brandApi.create(body), onSuccess: () => qc.invalidateQueries({ queryKey: brandKeys.list }) });
}

export function useUpdateBrand(id: string) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (body: Parameters<typeof brandApi.update>[1]) => brandApi.update(id, body),
    onSuccess: () => { qc.invalidateQueries({ queryKey: brandKeys.list }); qc.invalidateQueries({ queryKey: brandKeys.context(id) }); },
  });
}

export function useSaveSettings(id: string) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (body: BrandSettingsUpdate) => brandApi.putSettings(id, body),
    onSuccess: (data) => {
      if (data) qc.setQueryData(brandKeys.settings(id), data);
      qc.invalidateQueries({ queryKey: brandKeys.settings(id) });
      qc.invalidateQueries({ queryKey: brandKeys.context(id) });
    },
  });
}

export function usePillarMutations(id: string) {
  const qc = useQueryClient();
  const invalidate = () => { qc.invalidateQueries({ queryKey: brandKeys.pillars(id) }); qc.invalidateQueries({ queryKey: brandKeys.context(id) }); };
  return {
    create: useMutation({ mutationFn: (body: PillarInput) => brandApi.createPillar(id, body), onSuccess: invalidate }),
    update: useMutation({ mutationFn: (v: { pillarId: string; body: PillarInput }) => brandApi.updatePillar(id, v.pillarId, v.body), onSuccess: invalidate }),
    remove: useMutation({ mutationFn: (pillarId: string) => brandApi.deletePillar(id, pillarId), onSuccess: invalidate }),
  };
}

"use client";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { toast } from "sonner";
import { errorMessage } from "@/components/data/async-states";
import { toItems } from "@/lib/formatters";
import { ideasApi } from "./api";
import type { GenerateIdeasInput, Idea } from "./types";

export const ideaKeys = {
  list: (brandId?: string | null) => ["ideas", "list", brandId ?? null] as const,
};

export function useIdeas(brandId: string | null | undefined) {
  return useQuery({ queryKey: ideaKeys.list(brandId), queryFn: async () => toItems(await ideasApi.list({ brand_id: brandId })), enabled: !!brandId });
}

export function useGenerateIdeas() {
  return useMutation({ mutationFn: (body: GenerateIdeasInput) => ideasApi.generate(body) });
}

/** Optimistic status/field update with rollback toast (doc 23 §23.5). */
export function useUpdateIdea(brandId: string | null | undefined) {
  const qc = useQueryClient();
  const key = ideaKeys.list(brandId);
  return useMutation({
    mutationFn: (v: { id: string; body: Parameters<typeof ideasApi.update>[1] }) => ideasApi.update(v.id, v.body),
    onMutate: async (v) => {
      await qc.cancelQueries({ queryKey: key });
      const prev = qc.getQueryData<Idea[]>(key);
      qc.setQueryData<Idea[]>(key, (cur) => (cur ?? []).map((i) => (i.id === v.id ? { ...i, ...v.body } : i)));
      return { prev };
    },
    onError: (e, _v, ctx) => { if (ctx?.prev) qc.setQueryData(key, ctx.prev); toast.error(`Change rolled back: ${errorMessage(e)}`); },
    onSettled: () => qc.invalidateQueries({ queryKey: key }),
  });
}

export function useDeleteIdea(brandId: string | null | undefined) {
  const qc = useQueryClient();
  return useMutation({ mutationFn: (id: string) => ideasApi.remove(id), onSettled: () => qc.invalidateQueries({ queryKey: ideaKeys.list(brandId) }) });
}

export function useCreateIdea(brandId: string | null | undefined) {
  const qc = useQueryClient();
  return useMutation({ mutationFn: (body: Parameters<typeof ideasApi.create>[0]) => ideasApi.create(body), onSuccess: () => qc.invalidateQueries({ queryKey: ideaKeys.list(brandId) }) });
}

export function usePromoteIdea(brandId: string | null | undefined) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (id: string) => ideasApi.promote(id),
    onSuccess: () => { qc.invalidateQueries({ queryKey: ideaKeys.list(brandId) }); qc.invalidateQueries({ queryKey: ["content"] }); },
  });
}

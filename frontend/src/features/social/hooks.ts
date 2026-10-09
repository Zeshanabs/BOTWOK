"use client";
import { useEffect } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { onEvent } from "@/hooks/useSSE";
import { toItems } from "@/lib/formatters";
import { socialApi } from "./api";

export const socialKeys = {
  accounts: (brandId?: string | null) => ["social", "accounts", brandId ?? null] as const,
  selection: (platform: string, token: string) => ["social", "selection", platform, token] as const,
};

export function useSocialAccounts(brandId?: string | null) {
  const qc = useQueryClient();
  useEffect(() => onEvent((e) => { if (e.name.startsWith("SOCIAL_ACCOUNT")) qc.invalidateQueries({ queryKey: ["social", "accounts"] }); }), [qc]);
  return useQuery({ queryKey: socialKeys.accounts(brandId), queryFn: async () => toItems(await socialApi.accounts(brandId)) });
}

export function useSelection(platform: string | null, token: string | null) {
  return useQuery({
    queryKey: socialKeys.selection(platform ?? "", token ?? ""),
    queryFn: async () => {
      const d = await socialApi.selection(platform as string, token as string);
      return Array.isArray(d) ? d : d.accounts ?? d.items ?? [];
    },
    enabled: !!platform && !!token,
    retry: false,
  });
}

export function useSocialMutations() {
  const qc = useQueryClient();
  const invalidate = () => qc.invalidateQueries({ queryKey: ["social", "accounts"] });
  return {
    connect: useMutation({ mutationFn: (v: { platform: string; brand_id?: string | null; flavor?: string; reconnect_account_id?: string }) => socialApi.connect(v.platform, { brand_id: v.brand_id, flavor: v.flavor, reconnect_account_id: v.reconnect_account_id }) }),
    select: useMutation({ mutationFn: (v: { platform: string; selection_token: string; external_id: string }) => socialApi.select(v.platform, { selection_token: v.selection_token, external_id: v.external_id }), onSuccess: invalidate }),
    test: useMutation({ mutationFn: (id: string) => socialApi.test(id), onSettled: invalidate }),
    refresh: useMutation({ mutationFn: (id: string) => socialApi.refresh(id), onSettled: invalidate }),
    disconnect: useMutation({ mutationFn: (v: { id: string; force?: boolean }) => socialApi.disconnect(v.id, v.force), onSuccess: invalidate }),
  };
}

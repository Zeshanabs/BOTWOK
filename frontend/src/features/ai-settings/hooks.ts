"use client";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { toItems } from "@/lib/formatters";
import { aiSettingsApi, detectOllama } from "./api";
import type { AiSettings, UsageRow } from "./types";

export const aiSettingsKeys = {
  settings: ["ai", "settings"] as const,
  agents: ["ai", "agents"] as const,
  prompt: (agentId: string) => ["ai", "prompts", agentId] as const,
  usage: (from: string, to: string, by: string) => ["ai", "usage", from, to, by] as const,
  ollama: ["ai", "ollama"] as const,
};

export function useAiSettings() {
  return useQuery({ queryKey: aiSettingsKeys.settings, queryFn: () => aiSettingsApi.get() });
}
export function useSaveAiSettings() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (body: Partial<AiSettings>) => aiSettingsApi.put(body),
    onSuccess: (d) => { if (d) qc.setQueryData(aiSettingsKeys.settings, d); qc.invalidateQueries({ queryKey: aiSettingsKeys.settings }); },
  });
}
export function useProviderActions() {
  const qc = useQueryClient();
  const invalidate = () => qc.invalidateQueries({ queryKey: aiSettingsKeys.settings });
  return {
    setKey: useMutation({ mutationFn: (v: { provider: string; key: string; base_url?: string }) => aiSettingsApi.setKey(v.provider, { key: v.key, base_url: v.base_url }), onSuccess: invalidate }),
    test: useMutation({ mutationFn: (provider: string) => aiSettingsApi.testProvider(provider), onSettled: invalidate }),
  };
}
export function useAgents() {
  return useQuery({ queryKey: aiSettingsKeys.agents, queryFn: async () => toItems(await aiSettingsApi.agents()) });
}
export function usePrompt(agentId: string | null) {
  return useQuery({ queryKey: aiSettingsKeys.prompt(agentId ?? "none"), queryFn: () => aiSettingsApi.prompt(agentId as string), enabled: !!agentId });
}
export function useSavePrompt(agentId: string) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (body: { body: string; variables?: string[]; restore_version?: number }) => aiSettingsApi.putPrompt(agentId, body),
    onSuccess: () => qc.invalidateQueries({ queryKey: aiSettingsKeys.prompt(agentId) }),
  });
}
export function useUsage(from: string, to: string, by: "day" | "agent" | "model") {
  return useQuery({
    queryKey: aiSettingsKeys.usage(from, to, by),
    queryFn: async () => {
      const d = await aiSettingsApi.usage({ from, to, group_by: by });
      const rows: UsageRow[] = Array.isArray(d) ? d : d.items ?? d.groups ?? [];
      return { rows, total: Array.isArray(d) ? null : d.total_cost_usd ?? null };
    },
  });
}
export function useOllama() {
  return useQuery({ queryKey: aiSettingsKeys.ollama, queryFn: () => detectOllama(), staleTime: 60_000, retry: false });
}

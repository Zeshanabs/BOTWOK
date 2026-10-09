import { api, qs } from "@/lib/api";
import type { Page } from "@/lib/formatters";
import type { Agent, AiSettings, PromptTemplate, ProviderStatus, UsageResponse, UsageRow } from "./types";

export const aiSettingsApi = {
  get: () => api.get<AiSettings>("/ai/settings"),
  put: (body: Partial<AiSettings>) => api.put<AiSettings>("/ai/settings", body),
  setKey: (provider: string, body: { key: string; base_url?: string }) => api.post<ProviderStatus>(`/ai/providers/${provider}/key`, body),
  testProvider: (provider: string) => api.post<{ ok?: boolean; status?: string; latency_ms?: number; error?: string | null; models?: string[] }>(`/ai/providers/${provider}/test`, {}),
  agents: () => api.get<Page<Agent> | Agent[]>("/ai/agents"),
  prompt: (agentId: string) => api.get<PromptTemplate>(`/ai/prompts/${agentId}`),
  putPrompt: (agentId: string, body: { body: string; variables?: string[]; restore_version?: number }) => api.put<PromptTemplate>(`/ai/prompts/${agentId}`, body),
  usage: (params: { from: string; to: string; group_by: "day" | "agent" | "model" }) => api.get<UsageResponse | UsageRow[]>(`/ai/usage${qs(params)}`),
};

/** Best-effort local Ollama detection straight from the browser (CORS may block it; failure is silent). */
export async function detectOllama(baseUrl = "http://localhost:11434"): Promise<string[] | null> {
  try {
    const ctrl = new AbortController();
    const t = setTimeout(() => ctrl.abort(), 2500);
    const res = await fetch(`${baseUrl}/api/tags`, { signal: ctrl.signal });
    clearTimeout(t);
    if (!res.ok) return null;
    const data = (await res.json()) as { models?: { name?: string; model?: string }[] };
    return (data.models ?? []).map((m) => m.name ?? m.model ?? "").filter(Boolean);
  } catch {
    return null;
  }
}

/** AI settings types (doc 16 ai_settings jsonb sections; doc 17 §AI). Read defensively; written section-by-section. */

export type Tier = "cheap" | "balanced" | "powerful";
export const TIERS: Tier[] = ["cheap", "balanced", "powerful"];

export interface Route { primary?: string | null; fallback?: string | string[] | null; model?: string | null; tier?: Tier | null }

export interface ProviderStatus {
  enabled?: boolean;
  configured?: boolean;
  status?: "valid" | "active" | "invalid" | "unverified" | "not_set" | string | null;
  last4?: string | null;
  last_verified_at?: string | null;
  base_url?: string | null;
  error?: string | null;
}

export interface AiSettings {
  routing?: { cheap?: Route; balanced?: Route; powerful?: Route; embeddings?: Route; per_agent?: Record<string, Route>; fallback_on_error?: boolean; [k: string]: unknown };
  providers?: Record<string, ProviderStatus>;
  media?: { image_provider?: string | null; video_provider?: string | null; speech_provider?: string | null; [k: string]: unknown };
  search?: { provider?: string | null; order?: string[]; [k: string]: unknown };
  safety?: {
    auto_approve?: "never" | "threshold" | "score_threshold" | string;
    critic_threshold?: number | null;
    require_sources?: boolean;
    block_on_failed_fact_check?: boolean;
    max_steps?: number | null;
    [k: string]: unknown;
  };
  budgets?: { per_run_usd?: number | null; daily_usd?: number | null; monthly_usd?: number | null; confirm_above_usd?: number | null; [k: string]: unknown };
  updated_at?: string | null;
  updated_by?: { full_name?: string } | null;
}

export interface Agent { id: string; name?: string; description?: string | null; tier?: Tier | string; tools?: string[]; enabled?: boolean; resolved_model?: string | null }

export interface PromptVersion { id?: string; version: number; body: string; variables?: string[]; is_active?: boolean; created_at?: string; created_by?: string | { full_name?: string } | null }
export interface PromptTemplate { agent_id?: string; version?: number; body?: string; variables?: string[]; versions?: PromptVersion[]; active_version?: number }

export interface UsageRow {
  key?: string; day?: string; date?: string; agent?: string; agent_id?: string; model?: string;
  runs?: number; calls?: number; tokens?: number; tokens_in?: number; tokens_out?: number; cost_usd?: number | string; failures?: number;
}
export interface UsageResponse { items?: UsageRow[]; groups?: UsageRow[]; total_cost_usd?: number | string; from?: string; to?: string }

export const PROVIDERS: { name: string; label: string; kind: "llm" | "search" | "media" }[] = [
  { name: "anthropic", label: "Anthropic", kind: "llm" },
  { name: "openai", label: "OpenAI", kind: "llm" },
  { name: "google", label: "Google", kind: "llm" },
  { name: "xai", label: "xAI", kind: "llm" },
  { name: "tavily", label: "Tavily (search)", kind: "search" },
  { name: "brave", label: "Brave (search)", kind: "search" },
  { name: "exa", label: "Exa (search)", kind: "search" },
  { name: "elevenlabs", label: "ElevenLabs (speech)", kind: "media" },
];

export function usageKey(r: UsageRow): string {
  return r.key ?? r.day ?? r.date ?? r.agent ?? r.agent_id ?? r.model ?? "—";
}
export function usageTokens(r: UsageRow): number {
  return r.tokens ?? (r.tokens_in ?? 0) + (r.tokens_out ?? 0);
}
export function fallbackText(f: Route["fallback"]): string {
  return Array.isArray(f) ? f.join(", ") : f ?? "";
}

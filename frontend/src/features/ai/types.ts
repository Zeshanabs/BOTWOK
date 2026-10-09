/** AI run types (doc 17 §AI, doc 05 §5.6). Fields beyond the doc are optional and read defensively. */

export type RunStatus = "queued" | "planning" | "running" | "awaiting_approval" | "paused" | "completed" | "failed" | "cancelled";
export type TaskStatus = "pending" | "ready" | "running" | "awaiting_approval" | "succeeded" | "failed" | "skipped" | "cancelled";

export const ACTIVE_RUN_STATUSES: RunStatus[] = ["queued", "planning", "running"];
export const TERMINAL_RUN_STATUSES: RunStatus[] = ["completed", "failed", "cancelled"];

export function isRunActive(status: string | null | undefined): boolean {
  return ACTIVE_RUN_STATUSES.includes(status as RunStatus);
}
export function isRunTerminal(status: string | null | undefined): boolean {
  return TERMINAL_RUN_STATUSES.includes(status as RunStatus);
}

export interface RunTask {
  id?: string;
  key: string;
  label: string;
  agent?: string | null;
  action?: string | null;
  status: TaskStatus | string;
  duration_ms?: number | null;
  cost_usd?: number | string | null;
  sources_count?: number | null;
  tokens_in?: number | null;
  tokens_out?: number | null;
  model?: string | null;
  tier?: string | null;
  error?: string | null;
  requires_approval?: boolean;
  output_summary?: string | null;
  started_at?: string | null;
  finished_at?: string | null;
}

export interface RunSource {
  id?: string;
  source_id?: string;
  title?: string | null;
  url?: string | null;
  domain?: string | null;
  published_at?: string | null;
  relevance?: number | string | null;
  credibility?: number | string | null;
  summary?: string | null;
  injection_flag?: boolean;
  steps?: string[];
}

export interface RunDeliverable {
  id?: string;
  content_id?: string;
  type?: string;
  kind?: string;
  title?: string | null;
  platform?: string | null;
  status?: string | null;
  summary?: string | null;
  text?: string | null;
  critic_score?: number | null;
  url?: string | null;
}

export interface RunAction {
  approval_id: string;
  description: string;
  status: string;
  tool?: string | null;
  task_key?: string | null;
  scope?: Record<string, unknown> | null;
}

export interface RunResult {
  deliverables?: RunDeliverable[] | Record<string, unknown> | null;
  sources?: RunSource[] | null;
  reasoning_summary?: string | string[] | null;
  actions?: RunAction[] | null;
  summary?: string | null;
  text?: string | null;
}

export interface AiRun {
  id: string;
  status: RunStatus;
  mode?: string;
  title?: string | null;
  message?: string | null;
  input?: { message?: string; agent?: string; [k: string]: unknown } | null;
  intent?: string | { name?: string; intent?: string; [k: string]: unknown } | null;
  brand_id?: string | null;
  conversation_id?: string | null;
  plan?: { version?: number; tasks?: RunTask[] } | null;
  result?: RunResult | null;
  cost_usd?: number | string | null;
  tokens?: number | { in?: number; out?: number } | null;
  tokens_in?: number | null;
  tokens_out?: number | null;
  error?: string | null;
  reasoning_summary?: string | null;
  queue_position?: number | null;
  created_at?: string | null;
  queued_at?: string | null;
  started_at?: string | null;
  finished_at?: string | null;
  user?: { id?: string; full_name?: string } | null;
  automation_run_id?: string | null;
}

export interface ToolCall {
  id: string;
  task_id?: string | null;
  task_key?: string | null;
  tool_name: string;
  side_effect?: string | null;
  args_summary?: string | Record<string, unknown> | null;
  result_summary?: string | Record<string, unknown> | null;
  status: string;
  duration_ms?: number | null;
  error?: string | null;
  started_at?: string | null;
}

export interface StartRunInput {
  message: string;
  brand_id?: string | null;
  conversation_id?: string | null;
  mode: "chat" | "task" | "tool";
  agent?: string;
  action?: string;
  inputs?: Record<string, unknown>;
  budget_usd?: number;
  context?: { mentions?: { type: string; id: string; label?: string }[]; [k: string]: unknown };
}

export interface StartRunResponse {
  run_id: string;
  conversation_id?: string | null;
}

export function runTitle(run: Pick<AiRun, "title" | "message" | "input" | "intent" | "id">): string {
  const msg = run.title || run.message || run.input?.message;
  if (msg) return msg;
  const intent = typeof run.intent === "string" ? run.intent : run.intent?.name || run.intent?.intent;
  return intent ? String(intent) : `Run ${run.id.slice(0, 8)}`;
}

export function runTokens(run: AiRun): number | null {
  if (typeof run.tokens === "number") return run.tokens;
  if (run.tokens && typeof run.tokens === "object") return (run.tokens.in ?? 0) + (run.tokens.out ?? 0);
  if (run.tokens_in != null || run.tokens_out != null) return (run.tokens_in ?? 0) + (run.tokens_out ?? 0);
  return null;
}

/** `result.deliverables` is an array for chat/task runs and an object for e.g. brand import. */
export function deliverableList(d: RunResult["deliverables"]): RunDeliverable[] {
  if (!d) return [];
  if (Array.isArray(d)) return d as RunDeliverable[];
  for (const key of ["items", "content", "content_items", "drafts"]) {
    const v = (d as Record<string, unknown>)[key];
    if (Array.isArray(v)) return v as RunDeliverable[];
  }
  return [];
}

export function reasoningLines(r: RunResult["reasoning_summary"] | null | undefined): string[] {
  if (!r) return [];
  if (Array.isArray(r)) return r.map(String);
  return [r];
}

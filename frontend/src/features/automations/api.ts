/** Automations API (doc 14, doc 17 §17.2, flow P). V2 on the backend: every call may 404 — the UI keeps local state then. */
import { api, qs } from "@/lib/api";
import type { ListResponse } from "@/features/common/types";

export type SideEffect = "READ" | "EXTERNAL_READ" | "WRITE_INTERNAL" | "SPEND" | "APPROVAL" | "EXTERNAL_WRITE";
export interface SchemaProp {
  type: "string" | "number" | "integer" | "boolean" | "array" | "object";
  title?: string; description?: string; enum?: string[]; default?: unknown; format?: "textarea" | "json" | "cron" | "expression" | "url" | string;
  minimum?: number; maximum?: number; items?: { type?: string; enum?: string[] };
}
export interface NodeType {
  type: string; label: string; category?: "trigger" | "step" | string; side_effect?: SideEffect | string; description?: string;
  config_schema?: { properties?: Record<string, SchemaProp>; required?: string[] }; branches?: string[];
}
export interface WorkflowNodeDef { key: string; type: string; label?: string | null; config: Record<string, unknown>; position: { x: number; y: number } }
export interface WorkflowEdgeDef { from_node_key: string; to_node_key: string; branch?: string | null }
export interface Automation {
  id: string; name: string; description?: string | null; status: "draft" | "active" | "paused" | string; version?: number; trigger_summary?: string | null;
  last_run_at?: string | null; last_run_status?: string | null; next_run_at?: string | null; success_rate_30d?: number | null; autonomous_actions_enabled?: boolean;
  brand_id?: string | null; owner?: string | { name?: string; full_name?: string } | null; settings?: Record<string, unknown>; nodes?: WorkflowNodeDef[]; edges?: WorkflowEdgeDef[]; updated_at?: string | null;
}
export interface RunStep { id?: string; node_key: string; status: string; error?: string | null; started_at?: string | null; finished_at?: string | null; ai_run_id?: string | null; input?: unknown; output?: unknown; attempts?: number }
export interface AutomationRun {
  id: string; status: string; trigger_type?: string; trigger_payload?: Record<string, unknown>; started_at: string; finished_at?: string | null; cost_usd?: number | null;
  dry_run?: boolean; error?: string | null; workflow_version?: number; current_node_key?: string | null; steps?: RunStep[];
}
export interface SavePayload { name: string; nodes: WorkflowNodeDef[]; edges: WorkflowEdgeDef[]; settings?: Record<string, unknown>; autonomous_actions_enabled?: boolean }


// The API serializes edges as {from, to, branch, condition}; the builder uses {from_node_key, to_node_key, branch}.
type WireEdge = { from?: string; to?: string; from_node_key?: string; to_node_key?: string; branch?: string | null; condition?: unknown };
const fromWire = (e: WireEdge): WorkflowEdgeDef => ({ from_node_key: e.from_node_key ?? e.from ?? "", to_node_key: e.to_node_key ?? e.to ?? "", branch: e.branch ?? null });
const toWire = (e: WorkflowEdgeDef) => ({ from: e.from_node_key, to: e.to_node_key, branch: e.branch ?? null });
function normalize(a: Automation): Automation {
  return { ...a, edges: ((a.edges ?? []) as unknown as WireEdge[]).map(fromWire) };
}

export const automationsApi = {
  list: () => api.get<ListResponse<Automation>>("/automations"),
  create: async (b: { name: string; brand_id?: string | null; nodes?: WorkflowNodeDef[]; edges?: WorkflowEdgeDef[] }) =>
    normalize(await api.post<Automation>("/automations", { ...b, edges: (b.edges ?? []).map(toWire) })),
  /** Server-side template instantiation (keys from GET /automations/templates). Templates that schedule/publish require autonomous_actions_enabled=true. */
  fromTemplate: async (key: string, b: { name?: string; brand_id?: string | null; params?: Record<string, unknown>; autonomous_actions_enabled?: boolean; enable?: boolean }) =>
    normalize(await api.post<Automation>(`/automations/from-template/${key}`, b)),
  get: async (id: string) => normalize(await api.get<Automation>(`/automations/${id}`)),
  put: async (id: string, b: SavePayload) => normalize(await api.put<Automation>(`/automations/${id}`, { ...b, edges: b.edges.map(toWire) })),
  remove: (id: string) => api.delete<void>(`/automations/${id}`),
  enable: (id: string) => api.post<Automation>(`/automations/${id}/enable`),
  disable: (id: string) => api.post<Automation>(`/automations/${id}/disable`),
  run: (id: string, b: { dry_run?: boolean; payload?: Record<string, unknown> }) => api.post<{ run_id: string }>(`/automations/${id}/run`, b),
  runs: (id: string) => api.get<ListResponse<AutomationRun>>(`/automations/${id}/runs${qs({ limit: 25 })}`),
  runDetail: (runId: string) => api.get<AutomationRun>(`/automations/runs/${runId}`),
  cancelRun: (runId: string) => api.post<void>(`/automations/runs/${runId}/cancel`),
  nodeTypes: () => api.get<ListResponse<NodeType>>("/automations/node-types"),
};

const AGENTS = ["research", "social_listening", "competitor_intel", "trend", "strategy", "ideation", "writer", "repurposer", "visual", "critic", "fact_check", "performance_analyst", "report"];
const PLATFORM_ENUM = ["linkedin", "x", "instagram", "facebook", "threads", "youtube", "tiktok", "pinterest", "gbp"];
const EVENTS = ["TREND_DETECTED", "RESEARCH_COMPLETED", "SOURCE_SAVED", "COMPETITOR_SNAPSHOT_TAKEN", "PUBLISH_SUCCESS", "PUBLISH_FAILED", "ANALYTICS_UPDATED", "RECOMMENDATION_CREATED", "CONTENT_APPROVED", "REPORT_GENERATED"];

/** Built-in catalog used when GET /automations/node-types isn't available (doc 14 node list). */
export const BUILTIN_NODE_TYPES: NodeType[] = [
  { type: "trigger", label: "Trigger", category: "trigger", side_effect: "READ", description: "Starts the workflow: schedule, event, webhook or manual.",
    config_schema: { required: ["kind"], properties: { kind: { type: "string", title: "Kind", enum: ["cron", "event", "webhook", "manual"], default: "event" }, cron: { type: "string", title: "Cron (≥ 15 min)", format: "cron", description: "e.g. 0 8 * * MON" }, event: { type: "string", title: "Event", enum: EVENTS }, filter: { type: "string", title: "Filter", format: "expression", description: "e.g. payload.score >= 80" } } } },
  { type: "condition", label: "Condition", side_effect: "READ", branches: ["true", "false"], description: "Branch on an upstream value.",
    config_schema: { required: ["field", "operator"], properties: { field: { type: "string", title: "Field", format: "expression", description: "e.g. trigger.relevance" }, operator: { type: "string", title: "Operator", enum: [">", ">=", "<", "<=", "==", "!=", "contains"] }, value: { type: "string", title: "Value" } } } },
  { type: "ai_agent", label: "AI Agent", side_effect: "SPEND", description: "Run one agent with instructions; output feeds the next node.",
    config_schema: { required: ["agent"], properties: { agent: { type: "string", title: "Agent", enum: AGENTS }, instructions: { type: "string", title: "Instructions", format: "textarea" }, count: { type: "integer", title: "Count", minimum: 1, maximum: 20 }, pick_top: { type: "integer", title: "Keep top N", minimum: 1 }, max_cost_usd: { type: "number", title: "Max cost (USD)" } } } },
  { type: "research", label: "Research", side_effect: "EXTERNAL_READ", description: "Web/news/RSS research with citations.",
    config_schema: { required: ["query"], properties: { query: { type: "string", title: "Query", format: "expression" }, depth: { type: "string", title: "Depth", enum: ["quick", "standard", "deep"], default: "standard" }, recency_days: { type: "integer", title: "Recency (days)", minimum: 1 } } } },
  { type: "generate", label: "Generate", side_effect: "SPEND", description: "Ideas, post, variants, image or report.",
    config_schema: { required: ["what"], properties: { what: { type: "string", title: "Generate", enum: ["ideas", "post", "variants", "image", "report"] }, platform: { type: "string", title: "Platform", enum: PLATFORM_ENUM }, format: { type: "string", title: "Format", enum: ["text", "image", "carousel", "video", "short_video", "article", "poll", "document"] }, critic: { type: "boolean", title: "Run critic", default: true } } } },
  { type: "transform", label: "Transform", side_effect: "READ", description: "Map or reshape data between nodes.",
    config_schema: { properties: { mapping: { type: "object", title: "Mapping (JSON)", format: "json" } } } },
  { type: "approve", label: "Approve", side_effect: "APPROVAL", branches: ["approved", "rejected"], description: "Pause until a human approves.",
    config_schema: { required: ["role"], properties: { role: { type: "string", title: "Approver role", enum: ["approver", "admin", "owner"], default: "approver" }, expires_hours: { type: "integer", title: "Expires after (h)", default: 24, minimum: 1 }, note: { type: "string", title: "Note to approver", format: "textarea" } } } },
  { type: "schedule", label: "Schedule", side_effect: "EXTERNAL_WRITE", description: "Schedule approved content (dry-run simulated).",
    config_schema: { required: ["platform"], properties: { platform: { type: "string", title: "Platform", enum: PLATFORM_ENUM }, social_account_id: { type: "string", title: "Account ID" }, when: { type: "string", title: "When", enum: ["next_best_time", "in_hours", "fixed"], default: "next_best_time" }, hours: { type: "number", title: "Hours (if in_hours)" } } } },
  { type: "publish", label: "Publish", side_effect: "EXTERNAL_WRITE", description: "Publish approved variants only.",
    config_schema: { required: ["platform"], properties: { platform: { type: "string", title: "Platform", enum: PLATFORM_ENUM }, social_account_id: { type: "string", title: "Account ID" } } } },
  { type: "wait", label: "Wait", side_effect: "READ", description: "Delay or wait for a condition.",
    config_schema: { properties: { hours: { type: "number", title: "Hours", minimum: 0 }, until: { type: "string", title: "Until (expression)", format: "expression" }, max_iterations: { type: "integer", title: "Max iterations", minimum: 1 } } } },
  { type: "webhook", label: "Webhook", side_effect: "EXTERNAL_WRITE", description: "Call an external URL (signed).",
    config_schema: { required: ["url"], properties: { url: { type: "string", title: "URL", format: "url" }, method: { type: "string", title: "Method", enum: ["POST", "PUT"], default: "POST" }, body: { type: "object", title: "Body (JSON)", format: "json" } } } },
  { type: "notification", label: "Notification", side_effect: "WRITE_INTERNAL", description: "In-app, email or Slack notice.",
    config_schema: { required: ["channel"], properties: { channel: { type: "string", title: "Channel", enum: ["in_app", "email", "slack"], default: "in_app" }, recipients: { type: "string", title: "Recipients" }, message: { type: "string", title: "Message", format: "textarea" } } } },
  { type: "analytics", label: "Analytics", side_effect: "EXTERNAL_READ", description: "Sync metrics or run an analysis.",
    config_schema: { properties: { action: { type: "string", title: "Action", enum: ["sync", "analyze"], default: "sync" }, period_days: { type: "integer", title: "Period (days)", default: 7 } } } },
  { type: "action", label: "Action", side_effect: "WRITE_INTERNAL", description: "Run a built-in action.",
    config_schema: { required: ["action"], properties: { action: { type: "string", title: "Action", enum: ["competitors.sync", "report.generate", "trends.scan", "ideas.generate"] }, params: { type: "object", title: "Params (JSON)", format: "json" } } } },
];

/** Reference workflow from doc 24 §19: Industry news → LinkedIn post (with approval). */
export function newsToLinkedInTemplate(): { name: string; nodes: WorkflowNodeDef[]; edges: WorkflowEdgeDef[] } {
  const n = (key: string, type: string, label: string, y: number, config: Record<string, unknown>, x = 250): WorkflowNodeDef => ({ key, type, label, config, position: { x, y } });
  return {
    name: "Industry news → LinkedIn post",
    nodes: [
      n("trigger", "trigger", "New industry news detected", 0, { kind: "event", event: "TREND_DETECTED", filter: "payload.score >= 60" }),
      n("relevance", "condition", "Relevance gate", 120, { field: "trigger.relevance", operator: ">", value: "80" }),
      n("research", "research", "Deepen the story", 240, { query: "{{trigger.title}}", depth: "standard", recency_days: 7 }),
      n("ideas", "ai_agent", "Ideas ×3 · pick top 1", 360, { agent: "ideation", count: 3, pick_top: 1, instructions: "Angles for a LinkedIn audience of operators" }),
      n("post", "generate", "LinkedIn post · writer → critic", 480, { what: "post", platform: "linkedin", format: "text", critic: true }),
      n("approval", "approve", "Approval · approver · 24h", 600, { role: "approver", expires_hours: 24 }),
      n("schedule", "schedule", "Schedule · next best time", 720, { platform: "linkedin", when: "next_best_time" }),
      n("notify", "notification", "Tell the team it was rejected", 720, { channel: "in_app", message: "News post was rejected" }, 520),
    ],
    edges: [
      { from_node_key: "trigger", to_node_key: "relevance" },
      { from_node_key: "relevance", to_node_key: "research", branch: "true" },
      { from_node_key: "research", to_node_key: "ideas" },
      { from_node_key: "ideas", to_node_key: "post" },
      { from_node_key: "post", to_node_key: "approval" },
      { from_node_key: "approval", to_node_key: "schedule", branch: "approved" },
      { from_node_key: "approval", to_node_key: "notify", branch: "rejected" },
    ],
  };
}

/** Client-side graph validation (doc 14 / flow P step 3). */
export function validateWorkflow(nodes: WorkflowNodeDef[], edges: WorkflowEdgeDef[], types: NodeType[]): { node_key: string | null; message: string }[] {
  const issues: { node_key: string | null; message: string }[] = [];
  const triggers = nodes.filter((n) => n.type === "trigger" || n.type.startsWith("trigger."));
  if (triggers.length === 0) issues.push({ node_key: null, message: "Add exactly one Trigger node." });
  if (triggers.length > 1) triggers.slice(1).forEach((t) => issues.push({ node_key: t.key, message: "Only one trigger is allowed." }));
  const out = new Map<string, string[]>();
  edges.forEach((e) => out.set(e.from_node_key, [...(out.get(e.from_node_key) ?? []), e.to_node_key]));
  const reach = new Set<string>();
  const stack = triggers[0] ? [triggers[0].key] : [];
  while (stack.length) { const k = stack.pop() as string; if (reach.has(k)) continue; reach.add(k); (out.get(k) ?? []).forEach((x) => stack.push(x)); }
  nodes.forEach((n) => { if (triggers[0] && !reach.has(n.key)) issues.push({ node_key: n.key, message: `“${n.label ?? n.type}” isn't reachable from the trigger.` }); });
  for (const n of nodes) {
    const t = types.find((x) => x.type === n.type);
    for (const req of t?.config_schema?.required ?? []) {
      const v = n.config[req];
      if (v == null || v === "") issues.push({ node_key: n.key, message: `“${n.label ?? n.type}”: ${t?.config_schema?.properties?.[req]?.title ?? req} is required.` });
    }
  }
  // Every path into schedule/publish must pass through approve.
  const incoming = new Map<string, string[]>();
  edges.forEach((e) => incoming.set(e.to_node_key, [...(incoming.get(e.to_node_key) ?? []), e.from_node_key]));
  const typeOf = (k: string) => nodes.find((n) => n.key === k)?.type;
  const guarded = (k: string, seen: Set<string>): boolean => {
    if (seen.has(k)) return true;
    seen.add(k);
    const ins = incoming.get(k) ?? [];
    if (!ins.length) return false;
    return ins.every((p) => typeOf(p) === "approve" || guarded(p, seen));
  };
  nodes.filter((n) => n.type === "publish" || n.type === "schedule").forEach((n) => { if (!guarded(n.key, new Set())) issues.push({ node_key: n.key, message: `“${n.label ?? n.type}” needs an Approve node on every path before it.` }); });
  return issues;
}

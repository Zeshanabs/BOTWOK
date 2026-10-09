/** Approvals API (doc 00 §14 APPROVALS, doc 17, flow K). */
import { api, qs } from "@/lib/api";
import type { GenerationMetadata, ListResponse } from "@/features/common/types";
import type { ContentItem, ContentSourceRef, ContentVariant, Critique, FactCheck } from "@/features/studio/api";

export interface ApprovalRunRef { id: string; agent?: string | null; model?: string | null; status?: string; cost_usd?: number | null; prompt_version?: string | null }
/** Preview attached by GET /approvals/{id} (ApprovalService.preview). */
export interface ApprovalTarget {
  type: string; id: string; item?: ContentItem | null; variant_id?: string | null; variants?: ContentVariant[]; critique?: Critique | null; factcheck?: FactCheck | null;
  sources?: ContentSourceRef[]; generation_metadata?: GenerationMetadata | null; risk_level?: string | null; payload?: Record<string, unknown> | null; missing?: boolean;
}
export interface Approval {
  id: string;
  brand_id?: string | null;
  brand?: { id: string; name: string } | null;
  kind: "content" | "ai_action" | "automation_step" | string;
  target_type: string;
  target_id: string;
  /** For content: {title, comment, risk_level, version, variant_ids, platforms, ai_generated, decision?}. */
  payload: Record<string, unknown>;
  status: "pending" | "approved" | "rejected" | "expired" | string;
  requested_by: string;
  requested_by_name?: string | null;
  required_roles?: string[];
  decided_by?: string | null;
  decided_by_name?: string | null;
  decided_at?: string | null;
  decision_comment?: string | null;
  expires_at?: string | null;
  due_at?: string | null;
  created_at: string;
  snapshot_hash?: string | null;
  target?: ApprovalTarget | null;
  runs?: ApprovalRunRef[] | null;
  warnings?: string[];
}

export const approvalsApi = {
  list: (f: { status?: string | string[]; brand_id?: string | null; target_id?: string; mine?: boolean }) => api.get<ListResponse<Approval>>(`/approvals${qs({ ...f })}`),
  get: (id: string) => api.get<Approval>(`/approvals/${id}`),
  approve: (id: string, b: { comment?: string; acknowledged_flags?: string[] }) => api.post<Approval>(`/approvals/${id}/approve`, b),
  /** RejectRequest.decision: "reject" | "request_changes" (request changes → content back to draft). */
  reject: (id: string, b: { comment: string; decision: "reject" | "request_changes" }) => api.post<Approval>(`/approvals/${id}/reject`, b),
};

export function approvalTitle(a: Approval): string {
  const p = a.payload ?? {};
  return a.target?.item?.title ?? (typeof p.title === "string" ? p.title : null) ?? (typeof p.description === "string" ? p.description : null) ?? `${a.kind.replace(/_/g, " ")} ${a.target_id.slice(0, 8)}`;
}
export function approvalPlatforms(a: Approval): string[] {
  const p = a.payload ?? {};
  if (Array.isArray(p.platforms)) return p.platforms.filter((x): x is string => typeof x === "string");
  return (a.target?.variants ?? a.target?.item?.variants ?? []).map((v) => v.platform);
}
export const approvalComment = (a: Approval): string | null => (typeof a.payload?.comment === "string" ? a.payload.comment : typeof a.payload?.note === "string" ? a.payload.note : null);
export const isAiRequested = (a: Approval) => a.payload?.ai_generated === true || /^(agent|automation|system)/.test(a.requested_by ?? "");

/** System settings, API keys, export, notifications and admin endpoints (backend/app/schemas/identity.py). */
import { api, qs } from "@/lib/api";
import type { Page } from "@/lib/formatters";

export interface WorkspaceSettings {
  workspace_id: string; name: string; slug: string; timezone?: string; retention_days?: number | null;
  notification_channels?: { in_app?: boolean; email?: boolean; slack_configured?: boolean; slack_webhook_hint?: string | null; webhook_configured?: boolean; webhook_url_hint?: string | null };
}
export interface WorkspaceSettingsUpdate {
  name?: string; timezone?: string; retention_days?: number | null;
  notification_channels?: { in_app?: boolean; email?: boolean; slack_webhook_url?: string; webhook_url?: string };
}
export interface ApiKey { id: string; name: string; key_prefix: string; scopes?: string[]; last_used_at?: string | null; expires_at?: string | null; revoked_at?: string | null; created_at?: string | null }
export interface ApiKeyCreated extends ApiKey { secret: string }
export interface ExportJob { id: string; status: string; status_url?: string; download_url?: string | null; url?: string | null; error?: string | null }
export interface Notification { id: string; kind: string; title: string; body?: string | null; link?: string | null; severity?: string; read_at?: string | null; created_at?: string | null }
export interface NotificationPage extends Page<Notification> { unread_count?: number }
export interface HealthCheck { ok: boolean; latency_ms?: number | null; detail?: string | null; info?: Record<string, unknown> }
export interface Health { status: "ok" | "degraded" | "down" | string; checks: Record<string, HealthCheck> }
export interface Job { id: number | string; task_name: string; status: string; queue_name: string; attempts?: number; scheduled_at?: string | null }
export interface JobsPage { items: Job[]; available?: boolean; detail?: string | null }
export interface OutboxEvent { id: number | string; event_id: string; name: string; payload?: Record<string, unknown>; actor?: Record<string, unknown> | null; occurred_at: string; published_at?: string | null; attempts?: number }
export interface Costs { period: string; start: string; end: string; total_cost_usd: number; by_kind: { kind: string; quantity: number; cost_usd: number }[] }

export const systemApi = {
  workspace: () => api.get<WorkspaceSettings>("/settings/workspace"),
  putWorkspace: (body: WorkspaceSettingsUpdate) => api.put<WorkspaceSettings>("/settings/workspace", body),
  deleteWorkspace: (ws: string) => api.delete<unknown>(`/workspaces/${ws}`),
  apiKeys: () => api.get<Page<ApiKey> | ApiKey[]>("/settings/api-keys"),
  createApiKey: (body: { name: string; scopes: string[]; expires_at?: string | null }) => api.post<ApiKeyCreated>("/settings/api-keys", body),
  revokeApiKey: (id: string) => api.delete<unknown>(`/settings/api-keys/${id}`),
  startExport: () => api.post<ExportJob>("/settings/export", {}),
  exportStatus: (id: string) => api.get<ExportJob>(`/settings/exports/${id}`),
  notifications: (unread?: boolean) => api.get<NotificationPage | Notification[]>(`/notifications${qs({ unread: unread ? true : undefined, limit: 100 })}`),
  readNotification: (id: string) => api.post<unknown>(`/notifications/${id}/read`, {}),
  readAll: () => api.post<unknown>("/notifications/read-all", {}),
  health: () => api.get<Health>("/admin/health"),
  jobs: (status?: string) => api.get<JobsPage | Job[]>(`/admin/jobs${qs({ status, limit: 100 })}`),
  retryJob: (id: string | number) => api.post<unknown>(`/admin/jobs/${id}/retry`, {}),
  events: () => api.get<Page<OutboxEvent> | OutboxEvent[]>("/admin/events?limit=100"),
  costs: () => api.get<Costs>("/admin/costs"),
};

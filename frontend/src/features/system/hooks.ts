"use client";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { toItems } from "@/lib/formatters";
import { systemApi, type Notification, type WorkspaceSettingsUpdate } from "./api";

export const systemKeys = {
  workspace: ["settings", "workspace"] as const,
  apiKeys: ["settings", "api-keys"] as const,
  export: (id: string) => ["settings", "export", id] as const,
  // ["notifications"] prefix is shared with the header bell
  notifications: ["notifications", "list"] as const,
  health: ["admin", "health"] as const,
  jobs: (status: string) => ["admin", "jobs", status] as const,
  events: ["admin", "events"] as const,
  costs: ["admin", "costs"] as const,
};

export function useWorkspaceSettings() {
  return useQuery({ queryKey: systemKeys.workspace, queryFn: () => systemApi.workspace() });
}
export function useSaveWorkspaceSettings() {
  const qc = useQueryClient();
  return useMutation({ mutationFn: (b: WorkspaceSettingsUpdate) => systemApi.putWorkspace(b), onSuccess: (d) => { if (d) qc.setQueryData(systemKeys.workspace, d); } });
}
export function useApiKeys(enabled: boolean) {
  return useQuery({ queryKey: systemKeys.apiKeys, queryFn: async () => toItems(await systemApi.apiKeys()), enabled });
}
export function useApiKeyMutations() {
  const qc = useQueryClient();
  const invalidate = () => qc.invalidateQueries({ queryKey: systemKeys.apiKeys });
  return {
    create: useMutation({ mutationFn: (b: { name: string; scopes: string[]; expires_at?: string | null }) => systemApi.createApiKey(b), onSuccess: invalidate }),
    revoke: useMutation({ mutationFn: (id: string) => systemApi.revokeApiKey(id), onSettled: invalidate }),
  };
}
export function useExportStatus(id: string | null) {
  return useQuery({
    queryKey: systemKeys.export(id ?? "none"), queryFn: () => systemApi.exportStatus(id as string), enabled: !!id,
    refetchInterval: (q) => (["queued", "running", "processing"].includes(q.state.data?.status ?? "queued") && !q.state.error ? 2000 : false),
  });
}
export function useNotifications() {
  return useQuery({
    queryKey: systemKeys.notifications,
    queryFn: async () => {
      const d = await systemApi.notifications();
      return { items: toItems<Notification>(d), unread: Array.isArray(d) ? null : d.unread_count ?? null };
    },
  });
}
export function useNotificationMutations() {
  const qc = useQueryClient();
  const invalidate = () => qc.invalidateQueries({ queryKey: ["notifications"] });
  return {
    read: useMutation({ mutationFn: (id: string) => systemApi.readNotification(id), onSettled: invalidate }),
    readAll: useMutation({ mutationFn: () => systemApi.readAll(), onSettled: invalidate }),
  };
}
export function useHealth(enabled: boolean) {
  return useQuery({ queryKey: systemKeys.health, queryFn: () => systemApi.health(), enabled, refetchInterval: 30_000 });
}
export function useJobs(enabled: boolean, status: string) {
  return useQuery({
    queryKey: systemKeys.jobs(status), enabled,
    queryFn: async () => { const d = await systemApi.jobs(status === "all" ? undefined : status); return Array.isArray(d) ? { items: d, available: true, detail: null } : d; },
  });
}
export function useEvents(enabled: boolean) {
  return useQuery({ queryKey: systemKeys.events, queryFn: async () => toItems(await systemApi.events()), enabled, refetchInterval: 10_000 });
}
export function useCosts(enabled: boolean) {
  return useQuery({ queryKey: systemKeys.costs, queryFn: () => systemApi.costs(), enabled });
}
export function useRetryJob() {
  const qc = useQueryClient();
  return useMutation({ mutationFn: (id: string | number) => systemApi.retryJob(id), onSettled: () => qc.invalidateQueries({ queryKey: ["admin", "jobs"] }) });
}

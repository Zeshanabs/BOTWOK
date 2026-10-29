"use client";
import { useEffect, useRef } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { toast } from "sonner";
import { api, qs } from "@/lib/api";
import type { ListResponse } from "@/features/common/types";
import { errorMessage } from "@/features/common/utils";
import { contentApi, type ContentFilters, type ContentItem, type ContentVariant } from "./api";

export { useRunPolling } from "@/features/common/hooks";

export const contentKeys = {
  all: ["content"] as const,
  list: (f: ContentFilters) => ["content", "list", f] as const,
  detail: (id: string) => ["content", id] as const,
  versions: (id: string) => ["content", id, "versions"] as const,
  approvals: (id: string) => ["approvals", "target", id] as const,
};

export function useContentList(filters: ContentFilters) {
  return useQuery({ queryKey: contentKeys.list(filters), queryFn: () => contentApi.list(filters) });
}

export function useContent(id: string | null | undefined) {
  return useQuery({ queryKey: contentKeys.detail(id ?? ""), queryFn: () => contentApi.get(id as string), enabled: !!id });
}

export function useVersions(id: string) {
  return useQuery({ queryKey: contentKeys.versions(id), queryFn: () => contentApi.versions(id), retry: false });
}

export interface ApprovalRecord {
  id: string;
  status: string;
  kind?: string;
  target_id?: string;
  requested_by?: string;
  requested_by_name?: string | null;
  decided_by?: string | null;
  decided_by_name?: string | null;
  decided_at?: string | null;
  decision_comment?: string | null;
  payload?: Record<string, unknown>;
  created_at: string;
  expires_at?: string | null;
}
export function useApprovalHistory(contentId: string) {
  return useQuery({
    queryKey: contentKeys.approvals(contentId),
    queryFn: () => api.get<ListResponse<ApprovalRecord>>(`/approvals${qs({ target_id: contentId })}`),
    retry: false,
  });
}

/** Replace a variant in the cached content item. */
export function patchVariantInCache(item: ContentItem | undefined, v: ContentVariant): ContentItem | undefined {
  if (!item) return item;
  const variants = (item.variants ?? []).map((x) => (x.id === v.id ? { ...x, ...v } : x));
  if (!variants.some((x) => x.id === v.id)) variants.push(v);
  return { ...item, variants };
}

export function useContentMutations(id: string) {
  const qc = useQueryClient();
  const setItem = (item: ContentItem) => { if (item && typeof item === "object" && "id" in item) qc.setQueryData(contentKeys.detail(id), item); };
  const refresh = () => {
    void qc.invalidateQueries({ queryKey: contentKeys.detail(id) });
    void qc.invalidateQueries({ queryKey: contentKeys.versions(id) });
  };
  return {
    refresh,
    transition: useMutation({
      mutationFn: (body: { to: string; comment?: string }) => contentApi.transition(id, body),
      onMutate: async (body) => {
        await qc.cancelQueries({ queryKey: contentKeys.detail(id) });
        const prev = qc.getQueryData<ContentItem>(contentKeys.detail(id));
        if (prev) qc.setQueryData(contentKeys.detail(id), { ...prev, status: body.to as ContentItem["status"] });
        return { prev };
      },
      onError: (e, _b, ctx) => { if (ctx?.prev) qc.setQueryData(contentKeys.detail(id), ctx.prev); toast.error(`Status not changed: ${errorMessage(e)}`); },
      onSuccess: (item, body) => { setItem(item); toast.success(`Moved to ${body.to.replace(/_/g, " ")}`); },
      onSettled: () => { refresh(); void qc.invalidateQueries({ queryKey: ["approvals"] }); },
    }),
    requestApproval: useMutation({
      mutationFn: (body: { comment?: string; expires_in_hours?: number }) => contentApi.requestApproval(id, body),
      onSuccess: () => { toast.success("Approval requested"); refresh(); void qc.invalidateQueries({ queryKey: ["approvals"] }); },
    }),
    restore: useMutation({
      mutationFn: (v: { version: number; variant_id?: string | null }) => contentApi.restore(id, v.version, v.variant_id),
      onSuccess: (item, v) => { setItem(item); toast.success(`Restored v${v.version} as a new version`); refresh(); },
      onError: (e) => toast.error(`Restore failed: ${errorMessage(e)}`),
    }),
    attachAsset: useMutation({
      mutationFn: (b: { media_asset_id: string; variant_id?: string | null; role?: string; position?: number; alt_text?: string | null }) => contentApi.attachAsset(id, b),
      onSuccess: () => { toast.success("Media attached"); refresh(); },
      onError: (e) => toast.error(`Couldn't attach media: ${errorMessage(e)}`),
    }),
  };
}

/** Run `save` every `intervalMs` while `dirty`; also flushes on unmount-free page hide. */
export function useAutosave(dirty: boolean, save: () => void, intervalMs = 5000) {
  const saveRef = useRef(save);
  const dirtyRef = useRef(dirty);
  useEffect(() => { saveRef.current = save; dirtyRef.current = dirty; });
  useEffect(() => {
    const t = window.setInterval(() => { if (dirtyRef.current) saveRef.current(); }, intervalMs);
    const onHide = () => { if (document.visibilityState === "hidden" && dirtyRef.current) saveRef.current(); };
    document.addEventListener("visibilitychange", onHide);
    return () => { window.clearInterval(t); document.removeEventListener("visibilitychange", onHide); };
  }, [intervalMs]);
}

/** Browser-level unsaved-changes guard. */
export function useUnsavedGuard(dirty: boolean) {
  useEffect(() => {
    if (!dirty) return;
    const h = (e: BeforeUnloadEvent) => { e.preventDefault(); };
    window.addEventListener("beforeunload", h);
    return () => window.removeEventListener("beforeunload", h);
  }, [dirty]);
}


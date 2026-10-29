"use client";
import { useCallback, useEffect, useRef, useSyncExternalStore } from "react";
import { useParams } from "next/navigation";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { api, qs } from "@/lib/api";
import { hasRole, useSession } from "@/stores/session";
import type { AiRun, Brand, Campaign, ListResponse, Pillar, SocialAccount } from "./types";
import { toItems } from "./utils";
import { browserTz } from "./tz";

/** Build workspace-scoped hrefs: wsPath("studio/123") → /w/acme/studio/123 */
export function useWorkspacePath() {
  const slug = useSession((s) => s.workspaceSlug);
  const params = useParams<{ workspace?: string }>();
  const ws = params?.workspace ?? slug ?? "w";
  return useCallback((p: string) => `/w/${ws}/${p.replace(/^\//, "")}`, [ws]);
}

/** Capability checks per doc 00 §4 (approver rank sits below editor but can create and approve). */
export function usePermissions() {
  const role = useSession((s) => s.role);
  return {
    role,
    canCreate: hasRole(role, "approver"),
    canApprove: role === "approver" || hasRole(role, "admin"),
    canManage: hasRole(role, "admin"),
    canSchedule: hasRole(role, "approver"),
    isViewer: role === "viewer" || !role,
  };
}

export function useBrands() {
  const workspaceId = useSession((s) => s.workspaceId);
  // Same key + raw response as the header switcher so the cache is shared.
  return useQuery({ queryKey: ["brands"], queryFn: () => api.get<ListResponse<Brand>>("/brands"), enabled: !!workspaceId });
}

export function useActiveBrand(): { brandId: string | null; brand: Brand | undefined; timezone: string } {
  const brandId = useSession((s) => s.brandId);
  const brands = useBrands();
  const brand = toItems(brands.data).find((b) => b.id === brandId);
  return { brandId, brand, timezone: brand?.timezone || browserTz() };
}

export function usePillars(brandId: string | null | undefined) {
  return useQuery({
    queryKey: ["brands", brandId, "pillars"],
    queryFn: () => api.get<ListResponse<Pillar>>(`/brands/${brandId}/pillars`),
    enabled: !!brandId,
    staleTime: 60_000,
    retry: false,
  });
}

export function useCampaigns(brandId: string | null | undefined) {
  return useQuery({
    queryKey: ["campaigns", brandId ?? "all"],
    queryFn: () => api.get<ListResponse<Campaign>>(`/campaigns${qs({ brand_id: brandId })}`),
    staleTime: 60_000,
    retry: false,
  });
}

export function useSocialAccounts(brandId?: string | null) {
  return useQuery({
    queryKey: ["social", "accounts", brandId ?? "all"],
    queryFn: () => api.get<ListResponse<SocialAccount>>(`/social/accounts${qs({ brand_id: brandId })}`),
    staleTime: 30_000,
  });
}

export const TERMINAL_RUN = ["completed", "failed", "cancelled"];
export const ACTIVE_RUN = ["queued", "planning", "running"];

/**
 * Poll an AI run (GET /ai/runs/{id}) every 1.5 s until it is terminal or parked for approval.
 * Shares the ["ai","runs",id] cache key with the global AI drawer.
 */
export function useRunPolling(runId: string | null | undefined, opts: { onDone?: (run: AiRun) => void } = {}) {
  const query = useQuery({
    queryKey: ["ai", "runs", runId],
    queryFn: () => api.get<AiRun>(`/ai/runs/${runId}`),
    enabled: !!runId,
    refetchInterval: (q) => (ACTIVE_RUN.includes(String(q.state.data?.status ?? "queued")) ? 1500 : false),
  });
  const status = query.data?.status;
  const onDoneRef = useRef(opts.onDone);
  useEffect(() => { onDoneRef.current = opts.onDone; });
  const firedFor = useRef<string | null>(null);
  useEffect(() => {
    if (!runId || !query.data || !status) return;
    const done = TERMINAL_RUN.includes(status) || status === "awaiting_approval";
    if (done && firedFor.current !== `${runId}:${status}`) {
      firedFor.current = `${runId}:${status}`;
      onDoneRef.current?.(query.data);
    }
  }, [runId, status, query.data]);
  return { ...query, run: query.data, isActive: !!runId && (!status || ACTIVE_RUN.includes(status)) };
}

/** Invalidate helper for feature code that changes cross-cutting data. */
export function useInvalidate() {
  const qc = useQueryClient();
  return useCallback((...keys: unknown[][]) => { keys.forEach((k) => qc.invalidateQueries({ queryKey: k })); }, [qc]);
}

function subscribeMedia(query: string) {
  return (cb: () => void) => {
    if (typeof window === "undefined") return () => {};
    const mq = window.matchMedia(query);
    mq.addEventListener("change", cb);
    return () => mq.removeEventListener("change", cb);
  };
}
export function useMediaQuery(query: string, serverValue = false): boolean {
  const subscribe = useCallback((cb: () => void) => subscribeMedia(query)(cb), [query]);
  return useSyncExternalStore(subscribe, () => window.matchMedia(query).matches, () => serverValue);
}

/** Auth headers for raw fetches (downloads, presigned uploads proxied through the API). */
export function authHeaders(): Record<string, string> {
  const { accessToken, workspaceId } = useSession.getState();
  const h: Record<string, string> = {};
  if (accessToken) h.Authorization = `Bearer ${accessToken}`;
  if (workspaceId) h["X-Workspace-Id"] = workspaceId;
  return h;
}

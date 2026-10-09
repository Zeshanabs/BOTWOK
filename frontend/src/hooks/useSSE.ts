"use client";
/** Subscribe to workspace events (SSE). Auth uses the httpOnly access cookie set by the backend. */
import { useEffect, useRef } from "react";
import { useQueryClient } from "@tanstack/react-query";
import { useSession } from "@/stores/session";

export interface BotwokEvent { event_id: string; name: string; workspace_id: string | null; payload: Record<string, unknown>; occurred_at: string }
type Handler = (e: BotwokEvent) => void;
const handlers = new Set<Handler>();

export function onEvent(h: Handler) { handlers.add(h); return () => { handlers.delete(h); }; }

/** Mount once in the workspace layout. Invalidates common queries on relevant events. */
export function useSSEConnection() {
  const workspaceId = useSession((s) => s.workspaceId);
  const token = useSession((s) => s.accessToken);
  const qc = useQueryClient();
  const esRef = useRef<EventSource | null>(null);
  useEffect(() => {
    if (!workspaceId || !token) return;
    const es = new EventSource(`/api/v1/events/stream?workspace_id=${workspaceId}`, { withCredentials: true });
    esRef.current = es;
    const dispatch = (raw: MessageEvent) => {
      try {
        const e = JSON.parse(raw.data) as BotwokEvent;
        handlers.forEach((h) => h(e));
        const n = e.name;
        if (n.startsWith("AI_RUN")) qc.invalidateQueries({ queryKey: ["ai", "runs"] });
        if (n.startsWith("PUBLISH") || n.startsWith("POST_")) { qc.invalidateQueries({ queryKey: ["calendar"] }); qc.invalidateQueries({ queryKey: ["publishing"] }); }
        if (n.startsWith("CONTENT") || n.startsWith("VARIANT") || n.startsWith("APPROVAL")) { qc.invalidateQueries({ queryKey: ["content"] }); qc.invalidateQueries({ queryKey: ["approvals"] }); }
        if (n === "NOTIFICATION_CREATED") qc.invalidateQueries({ queryKey: ["notifications"] });
        if (n.startsWith("RESEARCH") || n === "SOURCE_SAVED") qc.invalidateQueries({ queryKey: ["research"] });
        if (n.startsWith("COMPETITOR")) qc.invalidateQueries({ queryKey: ["competitors"] });
        if (n.startsWith("MEDIA")) qc.invalidateQueries({ queryKey: ["media"] });
      } catch { /* ignore */ }
    };
    es.onmessage = dispatch;
    // named events are emitted with `event: <NAME>`; listen to the known prefixes generically
    const names = ["AI_RUN_STARTED","AI_RUN_STEP_COMPLETED","AI_RUN_AWAITING_APPROVAL","AI_RUN_COMPLETED","AI_RUN_FAILED","PUBLISH_STARTED","PUBLISH_SUCCESS","PUBLISH_FAILED","PUBLISH_DEAD_LETTERED","POST_SCHEDULED","POST_RESCHEDULED","POST_CANCELLED","POST_PAUSED","CONTENT_CREATED","CONTENT_UPDATED","CONTENT_STATUS_CHANGED","VARIANT_CREATED","APPROVAL_REQUESTED","CONTENT_APPROVED","CONTENT_REJECTED","NOTIFICATION_CREATED","RESEARCH_STARTED","RESEARCH_COMPLETED","RESEARCH_FAILED","SOURCE_SAVED","COMPETITOR_ADDED","COMPETITOR_UPDATED","COMPETITOR_SNAPSHOT_TAKEN","TREND_DETECTED","MEDIA_GENERATED","MEDIA_PROCESSED","ANALYTICS_UPDATED","SOCIAL_ACCOUNT_CONNECTED","SOCIAL_ACCOUNT_TOKEN_EXPIRING","SOCIAL_ACCOUNT_EXPIRED","SOCIAL_ACCOUNT_REVOKED","BUDGET_THRESHOLD_REACHED","BUDGET_EXCEEDED","AI_ANALYSIS_COMPLETED","RECOMMENDATION_CREATED","REPORT_GENERATED","AUTOMATION_TRIGGERED","AUTOMATION_STEP_COMPLETED","AUTOMATION_COMPLETED","AUTOMATION_FAILED"];
    names.forEach((n) => es.addEventListener(n, dispatch as EventListener));
    return () => { es.close(); esRef.current = null; };
  }, [workspaceId, token, qc]);
}

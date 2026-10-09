import { Check, Loader2, X } from "lucide-react";
import { fmtRelative } from "@/lib/formatters";
import type { Competitor } from "../types";

export function syncState(c: Competitor): { state: "syncing" | "failed" | "synced" | "never"; progress?: number | null; error?: string | null } {
  const profiles = c.profiles ?? [];
  const s = c.sync_status ?? (profiles.some((p) => ["syncing", "running", "queued"].includes(p.sync_status ?? "")) ? "syncing"
    : profiles.some((p) => ["failed", "error"].includes(p.sync_status ?? "")) ? "failed" : null);
  if (s === "syncing" || s === "running" || s === "queued") return { state: "syncing", progress: c.sync_progress };
  if (s === "failed" || s === "error") return { state: "failed", error: c.last_error ?? profiles.find((p) => p.last_error)?.last_error };
  return c.last_synced_at ? { state: "synced" } : { state: "never" };
}

export function SyncBadge({ competitor }: { competitor: Competitor }) {
  const s = syncState(competitor);
  if (s.state === "syncing") {
    return <span className="inline-flex items-center gap-1 text-xs text-blue-700 dark:text-blue-300"><Loader2 className="h-3 w-3 animate-spin motion-reduce:animate-none" /> syncing{s.progress != null ? ` ${Math.round(s.progress <= 1 ? s.progress * 100 : s.progress)}%` : "…"}</span>;
  }
  if (s.state === "failed") {
    return <span className="inline-flex items-center gap-1 text-xs text-red-700 dark:text-red-300" title={s.error ?? undefined}><X className="h-3 w-3" /> sync failed</span>;
  }
  if (s.state === "synced") {
    return <span className="inline-flex items-center gap-1 text-xs text-green-700 dark:text-green-300"><Check className="h-3 w-3" /> synced {fmtRelative(competitor.last_synced_at)}</span>;
  }
  return <span className="text-xs text-muted-foreground">not synced yet</span>;
}

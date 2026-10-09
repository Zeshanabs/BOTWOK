/**
 * Status → tone (doc 00 §11). Colour only ever means one thing: success / warning / danger / info / "ai" for
 * AI-generated, primary for "in flight on our side", outline for terminal-but-inert. Text and a dot always accompany it.
 */
export type StatusTone = "neutral" | "info" | "success" | "warning" | "danger" | "ai" | "primary" | "outline";

export const TONE_CLASSES: Record<StatusTone, string> = {
  neutral: "bg-muted text-foreground/75",
  info: "bg-info/12 text-info",
  success: "bg-success/12 text-success",
  warning: "bg-warning/14 text-warning",
  danger: "bg-destructive/10 text-destructive",
  ai: "bg-ai/12 text-ai",
  primary: "bg-primary/10 text-primary",
  outline: "border border-border bg-transparent text-muted-foreground",
};

export const STATUS_TONES: Record<string, StatusTone> = {
  // content
  idea: "neutral", draft: "neutral", ai_generated: "ai", needs_review: "warning", approved: "success", rejected: "outline", archived: "outline",
  // schedule / publishing
  scheduled: "primary", queued: "primary", publishing: "primary", published: "success", failed: "danger", cancelled: "outline", paused: "outline",
  succeeded: "success", ambiguous: "warning", reconciled: "success",
  // runs / tasks / jobs
  planning: "ai", running: "info", awaiting_approval: "warning", waiting: "warning", completed: "success", pending: "neutral", ready: "neutral", skipped: "outline",
  // approvals / invitations
  expired: "outline", accepted: "success",
  // accounts / providers / health
  active: "success", revoked: "danger", disconnected: "outline", error: "danger", not_set: "outline", invalid: "danger", unverified: "neutral",
  ok: "success", degraded: "warning", down: "danger", processing: "info",
  // ideas / trends
  new: "neutral", shortlisted: "primary", promoted: "success", discarded: "outline",
  emerging: "ai", rising: "success", peaking: "warning", declining: "outline", dismissed: "outline",
  // capability / fact-check / critique
  available: "success", unsupported: "outline", supported: "success", contradicted: "danger", unverifiable: "warning", opinion: "neutral",
  low: "neutral", medium: "warning", high: "danger", blocker: "danger", warning: "warning", info: "info", internal: "primary",
};

/** Statuses that are "in motion" get a pulsing dot. */
export const LIVE_STATUSES = new Set(["publishing", "running", "planning", "processing", "queued"]);

export const statusTone = (s: string): StatusTone => STATUS_TONES[s] ?? "neutral";

/** Backwards-compatible class map (status → chip classes). */
export const STATUS_STYLES: Record<string, string> = Object.fromEntries(Object.entries(STATUS_TONES).map(([k, t]) => [k, TONE_CLASSES[t]]));

export const statusLabel = (s: string) => s.replace(/_/g, " ").replace(/\b\w/g, (c) => c.toUpperCase());

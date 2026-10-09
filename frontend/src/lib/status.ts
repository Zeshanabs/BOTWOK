/** Status → badge classes (doc 00 §11). Text + icon always accompany color. */
export const STATUS_STYLES: Record<string, string> = {
  idea: "bg-slate-100 text-slate-700 dark:bg-slate-800 dark:text-slate-200",
  draft: "bg-gray-100 text-gray-700 dark:bg-gray-800 dark:text-gray-200",
  ai_generated: "bg-violet-100 text-violet-800 dark:bg-violet-900/50 dark:text-violet-200",
  needs_review: "bg-amber-100 text-amber-800 dark:bg-amber-900/50 dark:text-amber-200",
  approved: "bg-emerald-100 text-emerald-800 dark:bg-emerald-900/50 dark:text-emerald-200",
  scheduled: "bg-sky-100 text-sky-800 dark:bg-sky-900/50 dark:text-sky-200",
  queued: "bg-sky-100 text-sky-800 dark:bg-sky-900/50 dark:text-sky-200",
  publishing: "bg-blue-100 text-blue-800 animate-pulse dark:bg-blue-900/50 dark:text-blue-200",
  published: "bg-green-100 text-green-800 dark:bg-green-900/50 dark:text-green-200",
  failed: "bg-red-100 text-red-800 dark:bg-red-900/50 dark:text-red-200",
  cancelled: "bg-zinc-100 text-zinc-700 dark:bg-zinc-800 dark:text-zinc-200",
  rejected: "border border-zinc-300 text-zinc-700 dark:border-zinc-700 dark:text-zinc-200",
  archived: "border border-zinc-300 text-zinc-600 dark:border-zinc-700 dark:text-zinc-300",
  paused: "border border-zinc-300 text-zinc-700 dark:border-zinc-700 dark:text-zinc-200",
  // runs
  running: "bg-blue-100 text-blue-800 dark:bg-blue-900/50 dark:text-blue-200",
  planning: "bg-violet-100 text-violet-800 dark:bg-violet-900/50 dark:text-violet-200",
  awaiting_approval: "bg-amber-100 text-amber-800 dark:bg-amber-900/50 dark:text-amber-200",
  completed: "bg-green-100 text-green-800 dark:bg-green-900/50 dark:text-green-200",
  succeeded: "bg-green-100 text-green-800 dark:bg-green-900/50 dark:text-green-200",
  pending: "bg-gray-100 text-gray-700 dark:bg-gray-800 dark:text-gray-200",
  // accounts
  active: "bg-green-100 text-green-800 dark:bg-green-900/50 dark:text-green-200",
  expired: "border border-zinc-300 text-zinc-700 dark:border-zinc-700 dark:text-zinc-200",
  revoked: "border border-red-300 text-red-700 dark:border-red-800 dark:text-red-200",
  disconnected: "border border-zinc-300 text-zinc-600 dark:border-zinc-700 dark:text-zinc-300",
  error: "bg-red-100 text-red-800 dark:bg-red-900/50 dark:text-red-200",
};
export const statusLabel = (s: string) => s.replace(/_/g, " ").replace(/\b\w/g, (c) => c.toUpperCase());

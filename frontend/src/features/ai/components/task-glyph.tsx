import { Ban, Check, Circle, Loader2, PauseCircle, X } from "lucide-react";
import { cn } from "@/lib/utils";

/** ✓ succeeded · ⟳ running · ✗ failed · ⏸ awaiting approval · ⊘ skipped/cancelled · ○ pending (doc 24 notation). */
export function TaskGlyph({ status, className }: { status: string; className?: string }) {
  const base = cn("h-4 w-4 shrink-0", className);
  switch (status) {
    case "succeeded":
    case "completed":
      return <Check className={cn(base, "text-green-600 dark:text-green-400")} aria-label="Succeeded" />;
    case "running":
    case "planning":
      return <Loader2 className={cn(base, "animate-spin text-blue-600 motion-reduce:animate-none dark:text-blue-400")} aria-label="Running" />;
    case "failed":
      return <X className={cn(base, "text-red-600 dark:text-red-400")} aria-label="Failed" />;
    case "awaiting_approval":
    case "paused":
      return <PauseCircle className={cn(base, "text-amber-600 dark:text-amber-400")} aria-label="Awaiting approval" />;
    case "skipped":
    case "cancelled":
      return <Ban className={cn(base, "text-zinc-500")} aria-label={status === "skipped" ? "Skipped" : "Cancelled"} />;
    default:
      return <Circle className={cn(base, "text-muted-foreground")} aria-label="Pending" />;
  }
}

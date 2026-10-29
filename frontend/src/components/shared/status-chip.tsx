import { LIVE_STATUSES, statusLabel, statusTone, TONE_CLASSES } from "@/lib/status";
import { cn } from "@/lib/utils";

/** Status pill: tone colour + dot + text, so colour is never the only signal (doc 23 §23.5). */
export function StatusChip({ status, className, label }: { status: string; className?: string; label?: string }) {
  const tone = statusTone(status);
  const live = LIVE_STATUSES.has(status);
  return (
    <span
      data-status={status}
      className={cn("inline-flex h-[22px] shrink-0 items-center gap-1.5 whitespace-nowrap rounded-full px-2 text-[11px] font-medium leading-none", TONE_CLASSES[tone], className)}
    >
      <span className="relative flex h-1.5 w-1.5" aria-hidden>
        {live && <span className="absolute inline-flex h-full w-full animate-ping rounded-full bg-current opacity-60" />}
        <span className={cn("relative inline-flex h-1.5 w-1.5 rounded-full bg-current", tone === "outline" && "opacity-60")} />
      </span>
      {label ?? statusLabel(status)}
    </span>
  );
}

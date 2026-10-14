"use client";
/**
 * Data-availability class badge (doc 25 flow E): where a competitor/analytics figure comes from.
 * Exported for every screen that shows collected third-party data.
 */
import { Ban, Globe, Hand, Search, ShieldCheck } from "lucide-react";
import type { LucideIcon } from "lucide-react";
import { Tooltip, TooltipContent, TooltipProvider, TooltipTrigger } from "@/components/ui/tooltip";
import { cn } from "@/lib/utils";

export type Availability = "official_api" | "public_web" | "search" | "user_provided" | "not_collected";

export const AVAILABILITY_META: Record<Availability, { label: string; short: string; icon: LucideIcon; className: string; explain: string }> = {
  official_api: {
    label: "Official API", short: "API", icon: ShieldCheck,
    className: "border-emerald-300 bg-emerald-50 text-emerald-800 dark:border-emerald-800 dark:bg-emerald-950/40 dark:text-emerald-200",
    explain: "Read through a permitted official platform API using one of your connected accounts.",
  },
  public_web: {
    label: "Public web", short: "Web", icon: Globe,
    className: "border-sky-300 bg-sky-50 text-sky-800 dark:border-sky-800 dark:bg-sky-950/40 dark:text-sky-200",
    explain: "From the competitor's own website, blog, RSS or press pages, fetched per robots.txt.",
  },
  search: {
    label: "Search", short: "Search", icon: Search,
    className: "border-violet-300 bg-violet-50 text-violet-800 dark:border-violet-800 dark:bg-violet-950/40 dark:text-violet-200",
    explain: "Mentions found through the configured web-search provider (e.g. trade press coverage).",
  },
  user_provided: {
    label: "User-provided", short: "Manual", icon: Hand,
    className: "border-amber-300 bg-amber-50 text-amber-800 dark:border-amber-800 dark:bg-amber-950/40 dark:text-amber-200",
    explain: "Entered or imported by your team. Botwok did not verify these figures.",
  },
  not_collected: {
    label: "Not collected", short: "Not collected", icon: Ban,
    className: "border-zinc-300 text-zinc-600 dark:border-zinc-700 dark:text-zinc-300",
    explain: "No permitted source for this platform (platform restriction). Botwok never scrapes social platforms; only the handle is stored. You can add data manually.",
  },
};

export function availabilityMeta(a: string | null | undefined) {
  return AVAILABILITY_META[(a ?? "not_collected") as Availability] ?? AVAILABILITY_META.not_collected;
}

export function AvailabilityBadge({ availability, reason, short, showTooltip = true, className }: {
  availability: string | null | undefined;
  /** Optional server-provided reason (e.g. "not_found_or_not_professional"); appended to the tooltip. */
  reason?: string | null;
  short?: boolean;
  showTooltip?: boolean;
  className?: string;
}) {
  const m = availabilityMeta(availability);
  const Icon = m.icon;
  const label = short ? m.short : availability === "not_collected" && !short ? "Not collected (platform restriction)" : m.label;
  const badge = (
    <span
      className={cn("inline-flex items-center gap-1 rounded-full border px-2 py-0.5 text-[11px] font-medium whitespace-nowrap", m.className, className)}
      aria-label={`Data source: ${m.label}`}
      tabIndex={showTooltip ? 0 : undefined}
    >
      <Icon className="h-3 w-3" aria-hidden />
      {label}
    </span>
  );
  if (!showTooltip) return badge;
  return (
    <TooltipProvider delayDuration={150}>
      <Tooltip>
        <TooltipTrigger asChild>{badge}</TooltipTrigger>
        <TooltipContent className="max-w-xs">
          <p className="font-medium">{m.label}</p>
          <p>{m.explain}</p>
          {reason && <p className="mt-1 opacity-80">Reason: {reason.replace(/_/g, " ")}</p>}
        </TooltipContent>
      </Tooltip>
    </TooltipProvider>
  );
}

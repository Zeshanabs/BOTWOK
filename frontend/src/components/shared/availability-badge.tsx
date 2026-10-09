import { Hint } from "@/features/common/components/hint";
import { TONE_CLASSES, type StatusTone } from "@/lib/status";
import { cn } from "@/lib/utils";

/** Where a competitor datum came from (backend `AvailabilityClass`). */
export type Availability = "official_api" | "public_web" | "search" | "user_provided" | "not_collected";

const META: Record<string, { label: string; short: string; tone: StatusTone; hint: string }> = {
  official_api: { label: "Official API", short: "API", tone: "success", hint: "Collected through the platform's official API." },
  public_web: { label: "Public web", short: "Web", tone: "info", hint: "Collected from publicly accessible pages, within the platform's terms." },
  search: { label: "Search", short: "Search", tone: "neutral", hint: "Found through a search provider; may be incomplete." },
  user_provided: { label: "Provided", short: "User", tone: "neutral", hint: "Entered by a member of this workspace." },
  internal: { label: "Internal", short: "Int.", tone: "primary", hint: "Your own connected account data." },
  not_collected: { label: "Not collected", short: "—", tone: "outline", hint: "Nothing lawful to collect for this platform yet." },
  not_available: { label: "Not available", short: "n/a", tone: "outline", hint: "The platform does not expose this." },
};

export function AvailabilityBadge({ availability, short, reason, className }: { availability: string; short?: boolean; reason?: string | null; className?: string }) {
  const m = META[availability] ?? { label: availability.replace(/_/g, " "), short: availability.slice(0, 4), tone: "neutral" as StatusTone, hint: "" };
  const chip = (
    <span className={cn("inline-flex h-5 items-center whitespace-nowrap rounded-full px-1.5 text-[10.5px] font-medium uppercase tracking-wide", TONE_CLASSES[m.tone], className)}>
      {short ? m.short : m.label}
    </span>
  );
  const tip = reason || m.hint;
  return tip ? <Hint label={tip}><span className="inline-flex cursor-help">{chip}</span></Hint> : chip;
}

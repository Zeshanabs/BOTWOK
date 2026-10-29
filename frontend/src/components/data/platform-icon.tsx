import { platformMeta } from "@/lib/platforms";
import { cn } from "@/lib/utils";

export function PlatformIcon({ platform, size = 20, className }: { platform: string; size?: number; className?: string }) {
  const m = platformMeta(platform);
  return (
    <span title={m.label} aria-label={m.label} className={cn("inline-flex shrink-0 items-center justify-center rounded-md font-semibold text-white", className)}
          style={{ width: size, height: size, fontSize: Math.max(9, size * 0.42), background: m.color }}>
      {m.short}
    </span>
  );
}

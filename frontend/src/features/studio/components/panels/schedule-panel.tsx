"use client";
import { PlatformIcon } from "@/components/data/platform-icon";
import { StatusChip } from "@/components/data/status-chip";
import { Button } from "@/components/ui/button";
import { useActiveBrand } from "@/features/common/hooks";
import { platformMeta } from "@/lib/platforms";
import { ScheduleForm } from "@/features/publishing/components/schedule-form";
import type { ContentItem, ContentVariant } from "../../api";

/** Schedule tab: per-variant scheduling (master content isn't publishable by itself). */
export function SchedulePanel({ content, variant, onSelectVariant }: { content: ContentItem; variant: ContentVariant | null; onSelectVariant: (id: string) => void }) {
  const { timezone } = useActiveBrand();
  if (!variant) {
    const vs = content.variants ?? [];
    return (
      <div className="space-y-3">
        <p className="text-sm text-muted-foreground">Schedules belong to platform versions. Pick one:</p>
        {vs.length === 0 && <p className="text-sm text-muted-foreground">No platform versions yet — use Repurpose or “Add platform version”.</p>}
        {vs.map((v) => (
          <Button key={v.id} variant="outline" className="w-full justify-start" onClick={() => onSelectVariant(v.id)}>
            <PlatformIcon platform={v.platform} size={18} /> {platformMeta(v.platform).label}<span className="ml-auto"><StatusChip status={v.status} /></span>
          </Button>
        ))}
      </div>
    );
  }
  return <ScheduleForm key={variant.id} variant={variant} contentApproved={content.status === "approved"} brandId={content.brand_id} defaultTz={timezone} />;
}

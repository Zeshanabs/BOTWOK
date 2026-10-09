"use client";
import { useDraggable } from "@dnd-kit/core";
import { AlertTriangle, Lock, Pause, Sparkles } from "lucide-react";
import { PlatformIcon } from "@/components/data/platform-icon";
import { statusLabel } from "@/lib/status";
import { cn } from "@/lib/utils";
import { MediaThumb } from "@/features/media/components/media-thumb";
import { timeLabel } from "@/features/common/tz";
import { cardKey, cardTime, dragMode, scheduleStatusOf, STATUS_BORDER, type CalendarCard as Card } from "../api";

export function CardBody({ card, tz, compact }: { card: Card; tz: string; compact?: boolean }) {
  const t = cardTime(card);
  const sched = scheduleStatusOf(card);
  const mode = dragMode(card);
  const thumb = card.thumbnail_url || card.thumbnail_media_id;
  return (
    <div className={cn("flex items-start gap-1.5 rounded-md border border-l-4 bg-card p-1.5 text-left text-xs shadow-xs", STATUS_BORDER[card.status] ?? "border-l-gray-300", card.status === "publishing" && "animate-pulse")}>
      {thumb && !compact && <MediaThumb asset={{ id: card.thumbnail_media_id ?? card.id, url: card.thumbnail_url, kind: "image" }} className="h-8 w-8 shrink-0" />}
      <div className="min-w-0 flex-1">
        <div className="flex items-center gap-1">
          {card.platform && <PlatformIcon platform={card.platform} size={14} />}
          {t && <span className="font-medium tabular-nums">{timeLabel(t, tz)}</span>}
          {card.ai_generated && <Sparkles className="h-3 w-3 text-ai" aria-label="AI-created" />}
          {(card.warnings ?? []).length > 0 && <AlertTriangle className="h-3 w-3 text-amber-600" aria-label={(card.warnings ?? []).map((w) => w.message).join("; ")} />}
          {(sched === "paused" || card.paused) && <Pause className="h-3 w-3 text-muted-foreground" aria-label="paused" />}
          {mode === "locked" && <Lock className="ml-auto h-3 w-3 text-muted-foreground" aria-label="not movable" />}
        </div>
        <p className="truncate">{card.title || "Untitled"}</p>
        {!compact && <p className="truncate text-[10px] text-muted-foreground">{statusLabel(card.status)}{card.social_account ? ` · ${card.social_account.display_name}` : ""}</p>}
      </div>
    </div>
  );
}

/** Draggable calendar card; locked statuses (publishing/published/failed/cancelled) are not draggable. */
export function CalendarCard({ card, tz, onOpen, compact }: { card: Card; tz: string; onOpen: (c: Card) => void; compact?: boolean }) {
  const mode = dragMode(card);
  const { attributes, listeners, setNodeRef, isDragging } = useDraggable({ id: `card:${cardKey(card)}`, data: { card }, disabled: mode === "locked" });
  return (
    <button ref={setNodeRef} type="button" {...listeners} {...attributes} onClick={() => onOpen(card)}
            title={`${card.title} · ${statusLabel(card.status)}${(card.warnings ?? []).length ? ` · ⚠ ${(card.warnings ?? []).map((w) => w.message).join("; ")}` : ""}`}
            className={cn("block w-full touch-manipulation rounded-md focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring", isDragging && "opacity-40", mode !== "locked" && "cursor-grab active:cursor-grabbing")}>
      <CardBody card={card} tz={tz} compact={compact} />
    </button>
  );
}

/** Tray item: approved, unscheduled variant dragged onto a day to schedule (click/Enter opens the schedule dialog instead). */
export function TrayCard({ card, tz, onSchedule }: { card: Card; tz: string; onSchedule: (c: Card) => void }) {
  const { attributes, listeners, setNodeRef, isDragging } = useDraggable({ id: `tray:${card.content_variant_id ?? card.id}`, data: { tray: card } });
  return (
    <button ref={setNodeRef} type="button" {...listeners} {...attributes} onClick={() => onSchedule(card)} aria-roledescription="draggable approved post"
            title="Drag onto a day to schedule, or click to pick a time"
            className={cn("block w-full cursor-grab rounded-md text-left focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring", isDragging && "opacity-40")}>
      <CardBody card={card} tz={tz} />
    </button>
  );
}

"use client";
import { useState } from "react";
import Link from "next/link";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { Ban, CalendarClock, ExternalLink, Loader2, Pause, Play, Sparkles } from "lucide-react";
import { toast } from "sonner";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Sheet, SheetContent, SheetDescription, SheetHeader, SheetTitle } from "@/components/ui/sheet";
import { PlatformIcon } from "@/components/data/platform-icon";
import { StatusChip } from "@/components/data/status-chip";
import { ConfirmDialog } from "@/features/common/components/confirm-dialog";
import { usePermissions, useWorkspacePath } from "@/features/common/hooks";
import { fromLocalInput, toLocalInput } from "@/features/common/tz";
import { errorMessage, fmtDateTime } from "@/features/common/utils";
import { schedulingApi } from "@/features/publishing/api";
import { platformMeta } from "@/lib/platforms";
import { cardTime, dragMode, scheduleStatusOf, type CalendarCard } from "../api";

/** Card preview Sheet: details, warnings, and the non-drag actions (reschedule, pause/resume, cancel) — used on mobile instead of drag. */
export function CardSheet({ card, tz, onOpenChange, onMove }: { card: CalendarCard | null; tz: string; onOpenChange: (o: boolean) => void; onMove: (c: CalendarCard, iso: string) => void }) {
  const qc = useQueryClient();
  const ws = useWorkspacePath();
  const { canSchedule } = usePermissions();
  const [when, setWhen] = useState<string | null>(null);
  const [confirmCancel, setConfirmCancel] = useState(false);
  const sched = card ? scheduleStatusOf(card) : null;
  const postId = card?.scheduled_post_id ?? null;
  const act = useMutation({
    mutationFn: (kind: "pause" | "resume" | "cancel") => (kind === "pause" ? schedulingApi.pause(postId!) : kind === "resume" ? schedulingApi.resume(postId!) : schedulingApi.cancel(postId!)),
    onSuccess: (_r, kind) => { toast.success(kind === "pause" ? "Paused" : kind === "resume" ? "Resumed" : "Cancelled"); setConfirmCancel(false); onOpenChange(false); void qc.invalidateQueries({ queryKey: ["calendar"] }); void qc.invalidateQueries({ queryKey: ["publishing"] }); },
    onError: (e) => { setConfirmCancel(false); toast.error(errorMessage(e)); },
  });
  const t = card ? cardTime(card) : null;
  const value = when ?? (t ? toLocalInput(t, tz) : "");
  const movable = card ? dragMode(card) !== "locked" : false;
  return (
    <Sheet open={!!card} onOpenChange={(o) => { if (!o) setWhen(null); onOpenChange(o); }}>
      <SheetContent className="w-full overflow-y-auto sm:max-w-md">
        {card && (
          <>
            <SheetHeader>
              <SheetTitle className="flex items-center gap-2 pr-6">{card.platform && <PlatformIcon platform={card.platform} size={20} />}<span className="truncate">{card.title}</span></SheetTitle>
              <SheetDescription>{card.platform ? platformMeta(card.platform).label : "Content"}{card.format ? ` · ${card.format.replace(/_/g, " ")}` : ""}{card.social_account ? ` · ${card.social_account.display_name}` : ""}</SheetDescription>
            </SheetHeader>
            <div className="space-y-4 px-4 pb-6 text-sm">
              <div className="flex flex-wrap items-center gap-2"><StatusChip status={card.status} />{card.content_status && card.content_status !== card.status && <span className="text-xs text-muted-foreground">content: {card.content_status.replace(/_/g, " ")}</span>}{card.ai_generated && <span className="flex items-center gap-1 text-xs text-ai"><Sparkles className="h-3 w-3" /> AI-created</span>}</div>
              <p className="flex items-center gap-2"><CalendarClock className="h-4 w-4 text-muted-foreground" />{t ? `${fmtDateTime(t, tz, { weekday: "short" })} (${tz})` : "No time set"}{!card.scheduled_post_id && t && <span className="text-xs text-muted-foreground">planned date</span>}</p>
              {card.last_error && <p className="rounded-md bg-red-50 p-2 text-xs text-red-800 dark:bg-red-900/30 dark:text-red-200">Last error: {card.last_error}</p>}
              {card.published_url && <a className="inline-flex items-center gap-1 text-sm text-primary hover:underline" href={card.published_url} target="_blank" rel="noreferrer">View on {card.platform ? platformMeta(card.platform).label : "platform"} <ExternalLink className="h-3 w-3" /></a>}
              {card.created_by_name && <p className="text-xs text-muted-foreground">Scheduled by {card.created_by_name}</p>}
              {(card.warnings ?? []).length > 0 && <ul className="space-y-1 rounded-md border border-amber-300 bg-amber-50 p-2 text-xs dark:border-amber-800 dark:bg-amber-900/20">{card.warnings?.map((w, i) => <li key={i}>⚠ {w.message}</li>)}</ul>}
              {canSchedule && movable && (
                <div className="space-y-1.5">
                  <Label htmlFor="resched">Reschedule</Label>
                  <div className="flex gap-2">
                    <Input id="resched" type="datetime-local" value={value} onChange={(e) => setWhen(e.target.value)} />
                    <Button disabled={!when} onClick={() => { const iso = fromLocalInput(value, tz); if (iso) { onMove(card, iso); setWhen(null); onOpenChange(false); } }}>Move</Button>
                  </div>
                  {sched === "queued" && <p className="text-xs text-amber-700 dark:text-amber-300">Already queued — moving removes it from the queue.</p>}
                </div>
              )}
              {!movable && sched && <p className="text-xs text-muted-foreground">{sched === "failed" ? "Failed posts are handled in Publishing." : `A ${sched} post can't be moved.`}{sched === "failed" && <Link className="ml-1 text-primary hover:underline" href={ws("publishing?status=failed")}>Open Publishing</Link>}</p>}
              <div className="flex flex-wrap gap-2">
                <Button asChild variant="outline" size="sm"><Link href={ws(`studio/${card.content_item_id}${card.platform ? `?variant=${card.platform}` : ""}`)}><ExternalLink /> Open in Studio</Link></Button>
                {canSchedule && postId && sched === "scheduled" && <Button size="sm" variant="outline" onClick={() => act.mutate("pause")} disabled={act.isPending}><Pause /> Pause</Button>}
                {canSchedule && postId && sched === "paused" && <Button size="sm" variant="outline" onClick={() => act.mutate("resume")} disabled={act.isPending}><Play /> Resume</Button>}
                {canSchedule && postId && ["scheduled", "queued", "paused", "failed"].includes(sched ?? "") && <Button size="sm" variant="ghost" className="text-red-600" onClick={() => setConfirmCancel(true)}><Ban /> Cancel post</Button>}
                {act.isPending && <Loader2 className="h-4 w-4 animate-spin" />}
              </div>
            </div>
            <ConfirmDialog open={confirmCancel} onOpenChange={setConfirmCancel} destructive title="Cancel this scheduled post?" confirmLabel="Cancel post" pending={act.isPending} onConfirm={() => act.mutate("cancel")}
                           description={<p>“{card.title}” will not be published to {card.platform ? platformMeta(card.platform).label : "the platform"}{card.social_account ? ` (${card.social_account.display_name})` : ""}. The approved content stays in Studio and can be scheduled again.</p>} />
          </>
        )}
      </SheetContent>
    </Sheet>
  );
}

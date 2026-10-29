"use client";
import { useState } from "react";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { Loader2, Sparkles } from "lucide-react";
import { toast } from "sonner";
import { Button } from "@/components/ui/button";
import { Checkbox } from "@/components/ui/checkbox";
import { Dialog, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle } from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { PlatformIcon } from "@/components/shared/platform-icon";
import { fromLocalInput } from "@/features/common/tz";
import { errorMessage, fieldErrors } from "@/features/common/utils";
import { contentApi } from "@/features/studio/api";
import { PLATFORM_RULES } from "@/features/studio/platform-rules";
import { PLATFORMS, type Platform } from "@/lib/platforms";
import { cn } from "@/lib/utils";

/** Quick-create from an empty slot: title, platforms, planned time, optional ✦ AI draft. Never schedules. */
export function QuickCreateDialog({ open, onOpenChange, brandId, tz, defaultLocal, onCreated }: {
  open: boolean; onOpenChange: (o: boolean) => void; brandId: string | null; tz: string; defaultLocal: string; onCreated: (id: string) => void;
}) {
  const qc = useQueryClient();
  const [title, setTitle] = useState("");
  const [platforms, setPlatforms] = useState<Platform[]>([]);
  const [when, setWhen] = useState(defaultLocal);
  const [ai, setAi] = useState(false);
  const create = useMutation({
    mutationFn: async () => {
      if (!brandId) throw new Error("Select a brand first");
      const planned = fromLocalInput(when, tz) ?? undefined;
      // ContentCreate has no planned date: keep it in the body (extra keys are stored) so the schedule step can prefill it.
      const item = await contentApi.create({ brand_id: brandId, title: title.trim(), master_format: "text", body: planned ? { planned_at: planned, notes: `Planned for ${when.replace("T", " ")} (${tz})` } : undefined });
      for (const p of platforms) {
        try { await contentApi.createVariant(item.id, { platform: p, format: PLATFORM_RULES[p].formats[0] }); } catch { /* variant creation is best-effort */ }
      }
      if (ai) await contentApi.generate(item.id, { mode: "write", platform: platforms[0] });
      return item;
    },
    onSuccess: (item) => {
      toast.success(ai ? "Created — the writer is drafting it" : "Created as a draft", { action: { label: "Open", onClick: () => onCreated(item.id) } });
      void qc.invalidateQueries({ queryKey: ["calendar"] });
      onOpenChange(false); setTitle(""); setPlatforms([]); setAi(false);
    },
  });
  const errs = fieldErrors(create.error);
  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent>
        <DialogHeader><DialogTitle>Quick create</DialogTitle><DialogDescription>Creates the content (and blank platform versions). It appears on the calendar once an approved version is scheduled — nothing is scheduled automatically.</DialogDescription></DialogHeader>
        <div className="space-y-3">
          <div className="space-y-1.5"><Label htmlFor="qc-title">Title</Label><Input id="qc-title" autoFocus value={title} onChange={(e) => setTitle(e.target.value)} aria-invalid={!!errs.title} />{errs.title && <p className="text-xs text-destructive">{errs.title}</p>}</div>
          <div className="space-y-1.5"><Label htmlFor="qc-when">Planned for ({tz})</Label><Input id="qc-when" type="datetime-local" value={when} onChange={(e) => setWhen(e.target.value)} /></div>
          <div className="space-y-1.5">
            <Label>Platforms</Label>
            <div className="flex flex-wrap gap-1.5">
              {PLATFORMS.map((p) => {
                const on = platforms.includes(p.id);
                return <button key={p.id} type="button" aria-pressed={on} onClick={() => setPlatforms((s) => (on ? s.filter((x) => x !== p.id) : [...s, p.id]))} className={cn("flex items-center gap-1 rounded-full border px-2 py-1 text-xs", on && "border-primary bg-primary/5")}><PlatformIcon platform={p.id} size={14} />{p.label}</button>;
              })}
            </div>
          </div>
          <label className="flex items-center gap-2 text-sm"><Checkbox checked={ai} onCheckedChange={(c) => setAi(c === true)} /><Sparkles className="h-4 w-4 text-ai" /> Draft with AI</label>
          {create.error && !errs.title && <p className="text-sm text-destructive">{errorMessage(create.error)}</p>}
        </div>
        <DialogFooter>
          <Button variant="outline" onClick={() => onOpenChange(false)}>Cancel</Button>
          <Button onClick={() => create.mutate()} disabled={!title.trim() || create.isPending}>{create.isPending && <Loader2 className="animate-spin" />} Create</Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}

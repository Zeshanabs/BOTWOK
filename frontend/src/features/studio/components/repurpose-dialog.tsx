"use client";
import { useState } from "react";
import { useMutation } from "@tanstack/react-query";
import { AlertTriangle, Loader2, Sparkles } from "lucide-react";
import { toast } from "sonner";
import { Button } from "@/components/ui/button";
import { Checkbox } from "@/components/ui/checkbox";
import { Dialog, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle } from "@/components/ui/dialog";
import { Label } from "@/components/ui/label";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { PlatformIcon } from "@/components/data/platform-icon";
import { ConfirmDialog } from "@/features/common/components/confirm-dialog";
import { QueryError } from "@/features/common/components/query-state";
import { RunCard } from "@/features/common/components/run-card";
import { useSocialAccounts } from "@/features/common/hooks";
import type { AiRun } from "@/features/common/types";
import { errorMessage, problemCode, toItems } from "@/features/common/utils";
import { PLATFORMS, type Platform } from "@/lib/platforms";
import { contentApi, type ContentItem } from "../api";
import { composeMaster, PLATFORM_RULES } from "../platform-rules";

interface Target { checked: boolean; format: string }
const TONES = ["Brand default", "More casual", "More formal", "Punchier", "More educational"];

/** Repurpose master → platform variants (flow J). AI mode fans out to the repurposer; blank mode copies the master text. */
export function RepurposeDialog({ open, onOpenChange, content, preselect, onDone }: {
  open: boolean; onOpenChange: (o: boolean) => void; content: ContentItem; preselect?: Platform | null; onDone: () => void;
}) {
  const existing = new Map((content.variants ?? []).map((v) => [v.platform, v]));
  const [targets, setTargets] = useState<Record<string, Target>>(() => Object.fromEntries(PLATFORMS.map((p) => {
    const rule = PLATFORM_RULES[p.id];
    const fmt = existing.get(p.id)?.format ?? (rule.formats.includes(content.master_format) ? content.master_format : rule.formats[0]);
    return [p.id, { checked: preselect ? p.id === preselect : false, format: fmt }];
  })));
  const [mode, setMode] = useState<"ai" | "blank">("ai");
  const [keep, setKeep] = useState({ sources: true, cta: true, media: false });
  const [tone, setTone] = useState(TONES[0]);
  const [runId, setRunId] = useState<string | null>(null);
  const [confirmReapproval, setConfirmReapproval] = useState(false);
  const accounts = toItems(useSocialAccounts(content.brand_id).data).filter((a) => a.status === "active");
  const chosen = Object.entries(targets).filter(([, t]) => t.checked);
  const hasBody = !!(content.body?.body_md || content.body?.hook);

  const repurpose = useMutation({
    mutationFn: (confirm: boolean) => contentApi.repurpose(content.id, {
      targets: chosen.map(([platform, t]) => {
        const acct = accounts.filter((a) => a.platform === platform);
        return { platform, format: t.format, social_account_id: acct.length === 1 ? acct[0].id : undefined };
      }),
      source: "master", keep_sources: keep.sources, keep_cta: keep.cta, keep_media: keep.media, tone: tone === TONES[0] ? undefined : tone, confirm: confirm || undefined,
    }),
    onSuccess: (r) => setRunId(r.run_id),
    onError: (e) => { if (problemCode(e) === "confirm_reapproval" || problemCode(e) === "confirm_regenerate") setConfirmReapproval(true); },
  });
  const blank = useMutation({
    mutationFn: async () => {
      const text = composeMaster(content.body ?? {});
      for (const [platform, t] of chosen) {
        if (existing.has(platform as Platform)) continue;
        await contentApi.createVariant(content.id, { platform, format: t.format, text, hashtags: content.body?.hashtags ?? [] });
      }
    },
    onSuccess: () => { toast.success("Platform versions created"); onDone(); onOpenChange(false); },
    onError: (e) => toast.error(errorMessage(e)),
  });
  const onRunDone = (run: AiRun) => {
    onDone();
    if (run.status === "completed") toast.success("Variants ready — each shows what changed and why");
    else if (run.status === "failed") toast.error(run.error ?? "Repurposing failed");
  };
  const reset = () => { setRunId(null); repurpose.reset(); };

  return (
    <Dialog open={open} onOpenChange={(o) => { if (!o) reset(); onOpenChange(o); }}>
      <DialogContent className="max-h-[90vh] overflow-y-auto sm:max-w-3xl">
        <DialogHeader>
          <DialogTitle className="flex items-center gap-2"><Sparkles className="h-4 w-4 text-ai" /> Repurpose “{content.title}”</DialogTitle>
          <DialogDescription>Create per-platform versions from the master. Each AI version records what changed and is re-validated against the platform rules.</DialogDescription>
        </DialogHeader>
        {!hasBody && <p className="rounded-md bg-amber-50 p-2 text-sm text-amber-800 dark:bg-amber-900/30 dark:text-amber-200">The master has no body yet — write or generate it first.</p>}
        <div className="flex gap-2 text-sm" role="radiogroup" aria-label="Mode">
          {(["ai", "blank"] as const).map((m) => (
            <button key={m} type="button" role="radio" aria-checked={mode === m} onClick={() => setMode(m)} className={`rounded-md border px-3 py-1.5 ${mode === m ? "border-primary bg-primary/5" : ""}`}>
              {m === "ai" ? "✦ Adapt with AI (repurposer)" : "Copy master text (no AI)"}
            </button>
          ))}
        </div>
        <div className="overflow-x-auto">
          <table className="w-full text-sm">
            <thead><tr className="text-left text-xs text-muted-foreground"><th className="py-1 pr-2">Target</th><th className="py-1 pr-2">Format</th><th className="py-1">Constraints</th></tr></thead>
            <tbody>
              {PLATFORMS.map((p) => {
                const rule = PLATFORM_RULES[p.id];
                const t = targets[p.id];
                const ex = existing.get(p.id);
                const needsMedia = rule.mediaRequired && !(content.assets ?? []).length;
                return (
                  <tr key={p.id} className="border-t">
                    <td className="py-1.5 pr-2">
                      <label className="flex items-center gap-2">
                        <Checkbox checked={t.checked} onCheckedChange={(c) => setTargets((s) => ({ ...s, [p.id]: { ...s[p.id], checked: c === true } }))} aria-label={p.label} />
                        <PlatformIcon platform={p.id} size={18} /> {p.label}
                      </label>
                    </td>
                    <td className="py-1.5 pr-2">
                      <Select value={t.format} onValueChange={(f) => setTargets((s) => ({ ...s, [p.id]: { ...s[p.id], format: f } }))}>
                        <SelectTrigger size="sm" className="w-36"><SelectValue /></SelectTrigger>
                        <SelectContent>{rule.formats.map((f) => <SelectItem key={f} value={f}>{f.replace(/_/g, " ")}</SelectItem>)}</SelectContent>
                      </Select>
                    </td>
                    <td className="py-1.5 text-xs text-muted-foreground">
                      {rule.notes.slice(0, 2).join(" · ")}
                      {needsMedia && <span className="ml-1 text-amber-700 dark:text-amber-300">· ⚠ needs a media asset</span>}
                      {ex && t.checked && <span className="block text-amber-700 dark:text-amber-300">{mode === "ai" ? `⚠ ${p.label} version exists: regenerated text becomes a new version` : `${p.label} version exists — skipped`}</span>}
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
        {mode === "ai" && (
          <div className="flex flex-wrap items-center gap-4 text-sm">
            <span className="text-muted-foreground">Keep</span>
            {(["sources", "cta", "media"] as const).map((k) => (
              <label key={k} className="flex items-center gap-1.5"><Checkbox checked={keep[k]} onCheckedChange={(c) => setKeep((s) => ({ ...s, [k]: c === true }))} />{k === "cta" ? "CTA" : k === "media" ? "same media" : "sources"}</label>
            ))}
            <div className="flex items-center gap-2">
              <Label>Tone</Label>
              <Select value={tone} onValueChange={setTone}><SelectTrigger size="sm" className="w-44"><SelectValue /></SelectTrigger>
                <SelectContent>{TONES.map((t) => <SelectItem key={t} value={t}>{t}</SelectItem>)}</SelectContent></Select>
            </div>
          </div>
        )}
        {(content.status === "approved" || content.status === "needs_review") && mode === "ai" && (
          <p className="flex items-center gap-2 text-xs text-amber-700 dark:text-amber-300"><AlertTriangle className="h-3.5 w-3.5" /> New versions will need approval again; already scheduled posts keep their approved versions.</p>
        )}
        {repurpose.error && problemCode(repurpose.error) !== "confirm_reapproval" && <QueryError error={repurpose.error} title="Repurpose was not started" notAvailableText="Repurposing isn't enabled on this backend yet." />}
        {runId && <RunCard runId={runId} title={`Repurposing to ${chosen.length} platform${chosen.length === 1 ? "" : "s"}`} onDone={onRunDone} />}
        <DialogFooter>
          {mode === "ai" && <span className="mr-auto self-center text-xs text-muted-foreground">repurposer · balanced · ~{chosen.length} call{chosen.length === 1 ? "" : "s"} + critic per variant</span>}
          <Button variant="outline" onClick={() => onOpenChange(false)}>{runId ? "Close" : "Cancel"}</Button>
          {mode === "ai" ? (
            <Button onClick={() => repurpose.mutate(false)} disabled={!chosen.length || !hasBody || repurpose.isPending || !!runId}>
              {repurpose.isPending ? <Loader2 className="animate-spin" /> : <Sparkles />} Generate {chosen.length || ""}
            </Button>
          ) : (
            <Button onClick={() => blank.mutate()} disabled={!chosen.length || blank.isPending}>{blank.isPending && <Loader2 className="animate-spin" />} Create {chosen.length || ""}</Button>
          )}
        </DialogFooter>
        <ConfirmDialog open={confirmReapproval} onOpenChange={setConfirmReapproval} title="Re-approval will be required" confirmLabel="Repurpose anyway"
                       description={<p>This content is {content.status.replace(/_/g, " ")}. New AI versions withdraw the pending/granted approval for the affected versions.</p>}
                       onConfirm={() => { setConfirmReapproval(false); repurpose.mutate(true); }} />
      </DialogContent>
    </Dialog>
  );
}

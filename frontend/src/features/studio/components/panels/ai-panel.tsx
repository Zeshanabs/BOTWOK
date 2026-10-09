"use client";
import { useState } from "react";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { Expand, Loader2, Minimize2, PenLine, RefreshCw, Sparkles, Wand2 } from "lucide-react";
import { toast } from "sonner";
import { Button } from "@/components/ui/button";
import { Label } from "@/components/ui/label";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { Textarea } from "@/components/ui/textarea";
import { AiBadge } from "@/features/common/components/ai-badge";
import { ConfirmDialog } from "@/features/common/components/confirm-dialog";
import { QueryError } from "@/features/common/components/query-state";
import { RunCard } from "@/features/common/components/run-card";
import { usePermissions } from "@/features/common/hooks";
import type { AiRun } from "@/features/common/types";
import { fmtUsd, problemCode } from "@/features/common/utils";
import { platformMeta } from "@/lib/platforms";
import { contentApi, type ContentItem, type ContentVariant, type GenerateBody } from "../../api";
import { contentKeys } from "../../hooks";

const TONES = ["Warmer", "More formal", "More casual", "Bolder", "More playful", "More concise"];
type Mode = GenerateBody["mode"];
const ACTIONS: { mode: Mode; label: string; icon: typeof PenLine; hint: string }[] = [
  { mode: "write", label: "Write", icon: PenLine, hint: "Draft from the title, brief and sources" },
  { mode: "rewrite", label: "Rewrite", icon: RefreshCw, hint: "New wording, same message" },
  { mode: "shorten", label: "Shorten", icon: Minimize2, hint: "Tighter, keeps the CTA" },
  { mode: "expand", label: "Expand", icon: Expand, hint: "More depth and examples" },
];

/**
 * AI Assistant tab: writer actions scoped to the master or the selected variant. Every request is an AI run whose steps,
 * sources and cost are shown; results arrive as a new version (previous text stays in history).
 */
export function AiPanel({ content, variant, dirty, onBeforeRun, pendingSources = [], onSourcesConsumed }: { content: ContentItem; variant: ContentVariant | null; dirty: boolean; onBeforeRun: () => void; pendingSources?: { id: string; title: string }[]; onSourcesConsumed?: () => void }) {
  const qc = useQueryClient();
  const { canCreate } = usePermissions();
  const [instructions, setInstructions] = useState("");
  const [tone, setTone] = useState(TONES[0]);
  const [runs, setRuns] = useState<{ id: string; label: string }[]>([]);
  const [pendingConfirm, setPendingConfirm] = useState<GenerateBody | null>(null);
  const meta = variant?.generation_metadata ?? content.generation_metadata ?? null;
  const scope = variant ? `${platformMeta(variant.platform).label} version` : "Master";

  const gen = useMutation({
    mutationFn: (body: GenerateBody) => contentApi.generate(content.id, body),
    onSuccess: (r, body) => { setRuns((s) => [{ id: r.run_id, label: `${body.mode.replace(/_/g, " ")} · ${scope}` }, ...s].slice(0, 5)); if (body.source_ids?.length) onSourcesConsumed?.(); },
    onError: (e, body) => { if (problemCode(e) === "confirm_regenerate") setPendingConfirm(body); },
  });
  const start = (mode: Mode) => {
    onBeforeRun();
    const text = [mode === "change_tone" ? `Change the tone: ${tone}.` : "", instructions.trim()].filter(Boolean).join(" ");
    const body: GenerateBody = {
      mode, instructions: text || undefined, platform: variant?.platform, format: variant?.format ?? content.master_format,
      variant_id: variant?.id, source_ids: pendingSources.length ? pendingSources.map((s) => s.id) : undefined,
    };
    gen.mutate(body);
  };
  const onDone = (run: AiRun) => {
    void qc.invalidateQueries({ queryKey: contentKeys.detail(content.id) });
    void qc.invalidateQueries({ queryKey: contentKeys.versions(content.id) });
    if (run.status === "completed") toast.success("AI version arrived", { description: "Previous text is kept in version history." });
    if (run.status === "failed") toast.error("Generation failed — your text was left untouched");
  };
  const busy = gen.isPending;
  const empty = !content.body?.body_md && !content.body?.hook && !variant?.text;

  return (
    <div className="space-y-4">
      <div className="flex items-center justify-between gap-2 text-xs text-muted-foreground">
        <span>Applies to: <span className="font-medium text-foreground">{scope}</span></span>
        {meta && (meta.model || meta.agent) && <AiBadge meta={meta} label={meta.agent ?? "AI"} />}
      </div>
      {pendingSources.length > 0 && <p className="rounded-md border border-dashed p-2 text-xs">Next run will use {pendingSources.length} selected source{pendingSources.length === 1 ? "" : "s"}: {pendingSources.map((s) => s.title).join("; ")}</p>}
      {dirty && <p className="rounded-md bg-amber-50 p-2 text-xs text-amber-800 dark:bg-amber-900/30 dark:text-amber-200">Unsaved edits are saved first so the AI works from your latest text.</p>}
      {empty && <p className="rounded-md border border-dashed p-3 text-sm text-muted-foreground">Nothing written yet. Add instructions (or rely on the title and brief) and press <strong>Write</strong> to draft it.</p>}
      <div className="grid grid-cols-2 gap-2">
        {ACTIONS.map((a) => (
          <Button key={a.mode} variant="outline" size="sm" className="justify-start" title={a.hint} disabled={!canCreate || busy || (a.mode !== "write" && empty)} onClick={() => start(a.mode)}>
            <a.icon /> {a.label}
          </Button>
        ))}
      </div>
      <div className="flex gap-2">
        <Select value={tone} onValueChange={setTone}><SelectTrigger size="sm" className="flex-1" aria-label="Tone"><SelectValue /></SelectTrigger>
          <SelectContent>{TONES.map((t) => <SelectItem key={t} value={t}>{t}</SelectItem>)}</SelectContent></Select>
        <Button size="sm" variant="outline" disabled={!canCreate || busy || empty} onClick={() => start("change_tone")}><Wand2 /> Change tone</Button>
      </div>
      <div className="space-y-1.5">
        <Label htmlFor="ai-instr">Instructions</Label>
        <Textarea id="ai-instr" rows={3} value={instructions} onChange={(e) => setInstructions(e.target.value)} placeholder="Make the hook punchier; cite the 2026 survey; end with a question" disabled={!canCreate} />
        <Button size="sm" className="w-full" disabled={!canCreate || busy || !instructions.trim()} onClick={() => start(empty ? "write" : "regenerate")}>
          {busy ? <Loader2 className="animate-spin" /> : <Sparkles />} Run with instructions
        </Button>
      </div>
      {gen.error && problemCode(gen.error) !== "confirm_regenerate" && <QueryError error={gen.error} title="Generation not started" notAvailableText="Content generation isn't enabled on this backend yet." />}
      <div className="space-y-2">
        {runs.map((r) => <RunCard key={r.id} runId={r.id} title={`✦ ${r.label}`} onDone={onDone} />)}
      </div>
      {meta && (meta.model || meta.prompt_version || meta.cost_usd != null) && (
        <div className="rounded-md border p-2 text-[11px] text-muted-foreground">
          <p className="font-medium text-foreground">Last generation</p>
          <p>{[meta.agent, meta.provider, meta.model].filter(Boolean).join(" · ")}</p>
          <p>{meta.prompt_version && `prompt ${meta.prompt_version} · `}{meta.temperature != null && `temp ${meta.temperature} · `}{fmtUsd(meta.cost_usd)}</p>
        </div>
      )}
      <ConfirmDialog open={!!pendingConfirm} onOpenChange={(o) => !o && setPendingConfirm(null)} title="Regenerate approved content?" confirmLabel="Regenerate"
                     description={<p>This content is {content.status.replace(/_/g, " ")}. Regenerating withdraws the approval; it will need review again.</p>}
                     onConfirm={() => { if (pendingConfirm) gen.mutate({ ...pendingConfirm, confirm: true }); setPendingConfirm(null); }} />
    </div>
  );
}

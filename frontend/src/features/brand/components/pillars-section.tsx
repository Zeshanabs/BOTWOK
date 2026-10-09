"use client";
/** Content pillars CRUD with a target-share indicator (warns unless the shares sum to 100%). */
import { useState } from "react";
import { toast } from "sonner";
import { Plus, Trash2 } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Progress } from "@/components/ui/progress";
import { Textarea } from "@/components/ui/textarea";
import { TagInput } from "@/components/shared/tag-input";
import { ConfirmDialog } from "@/components/shared/confirm-dialog";
import { ListSkeleton, QueryError, errorMessage } from "@/components/shared/async-states";
import { FormError } from "@/components/shared/form-errors";
import { cn } from "@/lib/utils";
import { usePillarMutations, usePillars } from "../hooks";
import type { Pillar, PillarInput } from "../types";

interface Draft { name: string; description: string; share: string; color: string; examples: string[] }

const toDraft = (p?: Pillar): Draft => ({
  name: p?.name ?? "", description: p?.description ?? "", share: p?.share_target != null ? String(Math.round(Number(p.share_target) * 100)) : "",
  color: p?.color ?? "", examples: p?.examples ?? [],
});
const toInput = (d: Draft): PillarInput => ({
  name: d.name.trim(), description: d.description.trim() || null, share_target: d.share === "" ? null : Math.max(0, Math.min(100, Number(d.share))) / 100,
  color: /^#[0-9a-fA-F]{6}$/.test(d.color) ? d.color : null, examples: d.examples,
});

function PillarEditor({ draft, onChange, readOnly, idPrefix }: { draft: Draft; onChange: (d: Draft) => void; readOnly: boolean; idPrefix: string }) {
  return (
    <div className="grid gap-2 sm:grid-cols-[1fr_6rem_3rem]">
      <Input aria-label="Pillar name" placeholder="Name, e.g. Brewing guides" value={draft.name} onChange={(e) => onChange({ ...draft, name: e.target.value })} disabled={readOnly} />
      <div className="flex items-center gap-1">
        <Input aria-label="Target share percent" type="number" min={0} max={100} placeholder="%" value={draft.share} onChange={(e) => onChange({ ...draft, share: e.target.value })} disabled={readOnly} />
        <span className="text-xs text-muted-foreground">%</span>
      </div>
      <input type="color" aria-label="Pillar color" value={/^#[0-9a-fA-F]{6}$/.test(draft.color) ? draft.color : "#6366f1"} onChange={(e) => onChange({ ...draft, color: e.target.value })} disabled={readOnly} className="h-9 w-full cursor-pointer rounded border bg-transparent p-0.5" />
      <Textarea aria-label="Pillar description" rows={2} placeholder="What belongs in this pillar" value={draft.description} onChange={(e) => onChange({ ...draft, description: e.target.value })} disabled={readOnly} className="sm:col-span-3" />
      <div className="sm:col-span-3"><TagInput id={`${idPrefix}-ex`} ariaLabel="Example topics" placeholder="Example topics (Enter to add)" value={draft.examples} onChange={(v) => onChange({ ...draft, examples: v })} disabled={readOnly} /></div>
    </div>
  );
}

function PillarRow({ pillar, brandId, readOnly }: { pillar: Pillar; brandId: string; readOnly: boolean }) {
  const { update, remove } = usePillarMutations(brandId);
  const [draft, setDraft] = useState<Draft>(() => toDraft(pillar));
  const [confirm, setConfirm] = useState(false);
  const dirty = JSON.stringify(draft) !== JSON.stringify(toDraft(pillar));
  return (
    <li className="space-y-2 rounded-lg border p-3">
      <PillarEditor draft={draft} onChange={setDraft} readOnly={readOnly} idPrefix={pillar.id} />
      {(pillar.warnings?.length ?? 0) > 0 && <p className="text-xs text-warning">{pillar.warnings?.join(" · ")}</p>}
      {!readOnly && (
        <div className="flex justify-end gap-2">
          <Button size="sm" variant="ghost" onClick={() => setConfirm(true)}><Trash2 className="h-3 w-3" /> Delete</Button>
          <Button size="sm" disabled={!dirty || !draft.name.trim() || update.isPending}
                  onClick={() => update.mutate({ pillarId: pillar.id, body: toInput(draft) }, { onSuccess: () => toast.success("Pillar saved"), onError: (e) => toast.error(errorMessage(e)) })}>Save</Button>
        </div>
      )}
      <ConfirmDialog open={confirm} onOpenChange={setConfirm} title={`Delete pillar “${pillar.name}”?`} description="Existing ideas and content keep their text but lose this pillar tag." confirmLabel="Delete" busy={remove.isPending}
                     onConfirm={() => remove.mutate(pillar.id, { onSuccess: () => { toast.success("Pillar deleted"); setConfirm(false); }, onError: (e) => toast.error(errorMessage(e)) })} />
    </li>
  );
}

export function PillarsSection({ brandId, readOnly }: { brandId: string; readOnly: boolean }) {
  const pillars = usePillars(brandId);
  const { create } = usePillarMutations(brandId);
  const [draft, setDraft] = useState<Draft>(toDraft());
  const [adding, setAdding] = useState(false);
  if (pillars.isLoading) return <ListSkeleton rows={4} rowClassName="h-24" />;
  if (pillars.error) return <QueryError error={pillars.error} onRetry={() => pillars.refetch()} title="Couldn't load pillars" />;
  const list = [...(pillars.data ?? [])].sort((a, b) => (a.position ?? 0) - (b.position ?? 0));
  const total = Math.round(list.reduce((s, p) => s + Number(p.share_target ?? 0), 0) * 100);
  const ok = total === 100;

  return (
    <div className="space-y-4">
      <div className="space-y-1">
        <div className="flex items-center justify-between text-sm"><span>Target shares</span><span className={cn("tabular-nums", ok ? "text-success" : "text-warning")}>{total}% of 100%</span></div>
        <Progress value={Math.min(100, total)} aria-label="Sum of pillar target shares" />
        {!ok && list.length > 0 && <p className="text-xs text-warning">Shares should sum to 100% so ideation can weight under-served pillars correctly.</p>}
      </div>
      {!list.length && <p className="rounded-lg border border-dashed p-4 text-sm text-muted-foreground">No pillars yet. Most brands use 3–6 (e.g. Educational, Behind the scenes, Product).</p>}
      <ul className="space-y-3">{list.map((p) => <PillarRow key={p.id} pillar={p} brandId={brandId} readOnly={readOnly} />)}</ul>
      {!readOnly && (adding ? (
        <div className="space-y-2 rounded-lg border border-primary/40 p-3">
          <PillarEditor draft={draft} onChange={setDraft} readOnly={false} idPrefix="new" />
          <FormError error={create.error} />
          <div className="flex justify-end gap-2">
            <Button size="sm" variant="ghost" onClick={() => { setAdding(false); setDraft(toDraft()); create.reset(); }}>Cancel</Button>
            <Button size="sm" disabled={!draft.name.trim() || create.isPending}
                    onClick={() => create.mutate({ ...toInput(draft), position: list.length }, { onSuccess: () => { toast.success("Pillar added"); setDraft(toDraft()); setAdding(false); } })}>Add pillar</Button>
          </div>
        </div>
      ) : <Button variant="outline" size="sm" onClick={() => setAdding(true)}><Plus className="h-3 w-3" /> Add pillar</Button>)}
    </div>
  );
}

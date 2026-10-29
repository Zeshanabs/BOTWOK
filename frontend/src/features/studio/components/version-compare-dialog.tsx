"use client";
import { useState } from "react";
import { ArrowLeftRight, History, Sparkles } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Dialog, DialogContent, DialogDescription, DialogHeader, DialogTitle } from "@/components/ui/dialog";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { useMediaQuery } from "@/features/common/hooks";
import { relTime } from "@/features/common/utils";
import { platformMeta } from "@/lib/platforms";
import { cn } from "@/lib/utils";
import type { ContentVariant, ContentVersion } from "../api";
import { snapshotText, wordDiff, type DiffPart } from "../diff";

export function versionTargetLabel(v: ContentVersion, variants: ContentVariant[]): string {
  if (v.target_type.includes("variant")) {
    const variant = variants.find((x) => x.id === v.target_id);
    return variant ? platformMeta(variant.platform).label : "variant";
  }
  return "Master";
}
export function versionAuthor(v: ContentVersion): string {
  if (v.author_type === "agent") return `✦ ${v.author_id.replace(/^agent:/, "")}`;
  return v.author_name ?? "User";
}

function Parts({ parts, side }: { parts: DiffPart[]; side: "left" | "right" | "inline" }) {
  return (
    <p className="whitespace-pre-wrap break-words text-sm leading-relaxed">
      {parts.map((p, i) => {
        if (p.kind === "same") return <span key={i}>{p.text}</span>;
        if (p.kind === "del" && side !== "right") return <del key={i} className="rounded bg-destructive/10 text-destructive decoration-red-500">{p.text}</del>;
        if (p.kind === "add" && side !== "left") return <ins key={i} className="rounded bg-success/12 text-success no-underline">{p.text}</ins>;
        return null;
      })}
    </p>
  );
}

/** Side-by-side (desktop) or inline word diff of two versions, with Restore. */
export function VersionCompareDialog({ open, onOpenChange, versions, variants, initialA, initialB, onRestore, canRestore }: {
  open: boolean; onOpenChange: (o: boolean) => void; versions: ContentVersion[]; variants: ContentVariant[];
  initialA?: string; initialB?: string; onRestore: (v: ContentVersion) => void; canRestore: boolean;
}) {
  const wide = useMediaQuery("(min-width: 768px)");
  const sorted = [...versions].sort((a, b) => (a.created_at < b.created_at ? 1 : -1));
  const [a, setA] = useState<string | undefined>(initialA ?? sorted[1]?.id);
  const [b, setB] = useState<string | undefined>(initialB ?? sorted[0]?.id);
  const [mode, setMode] = useState<"side" | "inline">("side");
  const va = sorted.find((v) => v.id === a);
  const vb = sorted.find((v) => v.id === b);
  const parts = va && vb ? wordDiff(snapshotText(va.snapshot), snapshotText(vb.snapshot)) : [];
  const effectiveMode = wide ? mode : "inline";
  const option = (v: ContentVersion) => `v${v.version} · ${versionTargetLabel(v, variants)} · ${versionAuthor(v)} · ${relTime(v.created_at)}`;
  const header = (v: ContentVersion | undefined) => v && (
    <div className="mb-2 flex flex-wrap items-center gap-2 text-xs text-muted-foreground">
      <span className="font-medium text-foreground">v{v.version}</span>
      <span>{versionTargetLabel(v, variants)}</span>
      <span className={cn(v.author_type === "agent" && "text-ai")}>{v.author_type === "agent" && <Sparkles className="mr-0.5 inline h-3 w-3" />}{versionAuthor(v)}</span>
      <span>{new Date(v.created_at).toLocaleString()}</span>
      {v.diff_summary && <span className="italic">“{v.diff_summary}”</span>}
    </div>
  );
  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="max-h-[90vh] overflow-y-auto sm:max-w-5xl">
        <DialogHeader>
          <DialogTitle className="flex items-center gap-2"><History className="h-4 w-4" /> Compare versions</DialogTitle>
          <DialogDescription>Word-level diff of the saved snapshots. Restoring creates a new version; nothing is overwritten.</DialogDescription>
        </DialogHeader>
        {sorted.length < 2 ? <p className="text-sm text-muted-foreground">At least two versions are needed to compare.</p> : (
          <>
            <div className="flex flex-wrap items-center gap-2">
              <Select value={a} onValueChange={setA}><SelectTrigger className="w-full sm:w-72"><SelectValue placeholder="Older version" /></SelectTrigger>
                <SelectContent>{sorted.map((v) => <SelectItem key={v.id} value={v.id}>{option(v)}</SelectItem>)}</SelectContent></Select>
              <Button variant="ghost" size="icon-sm" aria-label="Swap" onClick={() => { setA(b); setB(a); }}><ArrowLeftRight /></Button>
              <Select value={b} onValueChange={setB}><SelectTrigger className="w-full sm:w-72"><SelectValue placeholder="Newer version" /></SelectTrigger>
                <SelectContent>{sorted.map((v) => <SelectItem key={v.id} value={v.id}>{option(v)}</SelectItem>)}</SelectContent></Select>
              {wide && (
                <div className="ml-auto flex rounded-md border p-0.5 text-xs" role="radiogroup" aria-label="Diff layout">
                  {(["side", "inline"] as const).map((m) => <button key={m} type="button" role="radio" aria-checked={mode === m} onClick={() => setMode(m)} className={cn("rounded px-2 py-1", mode === m && "bg-secondary")}>{m === "side" ? "Side by side" : "Inline"}</button>)}
                </div>
              )}
            </div>
            {va && vb && va.target_id !== vb.target_id && <p className="text-xs text-warning">These versions belong to different targets ({versionTargetLabel(va, variants)} vs {versionTargetLabel(vb, variants)}).</p>}
            {effectiveMode === "side" ? (
              <div className="grid gap-4 md:grid-cols-2">
                <div className="rounded-lg border p-3">{header(va)}<Parts parts={parts} side="left" />{canRestore && va && <Button className="mt-3" size="sm" variant="outline" onClick={() => onRestore(va)}>Restore v{va.version}</Button>}</div>
                <div className="rounded-lg border p-3">{header(vb)}<Parts parts={parts} side="right" />{canRestore && vb && <Button className="mt-3" size="sm" variant="outline" onClick={() => onRestore(vb)}>Restore v{vb.version}</Button>}</div>
              </div>
            ) : (
              <div className="rounded-lg border p-3">
                {header(vb)}
                <Parts parts={parts} side="inline" />
                {canRestore && va && <Button className="mt-3" size="sm" variant="outline" onClick={() => onRestore(va)}>Restore v{va.version}</Button>}
              </div>
            )}
          </>
        )}
      </DialogContent>
    </Dialog>
  );
}

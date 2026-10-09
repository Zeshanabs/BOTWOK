"use client";
import { useState } from "react";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { Check, Loader2, Sparkles } from "lucide-react";
import { toast } from "sonner";
import { Button } from "@/components/ui/button";
import { Dialog, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle } from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { Textarea } from "@/components/ui/textarea";
import { RunCard } from "@/features/common/components/run-card";
import { QueryError } from "@/features/common/components/query-state";
import type { AiRun } from "@/features/common/types";
import { errorMessage } from "@/features/common/utils";
import { isRunAccepted } from "@/features/studio/api";
import { extractAssets, mediaApi, SIZE_PRESETS, type GenerateResult, type MediaAsset } from "../api";
import { MediaThumb } from "./media-thumb";

/**
 * Generate image (doc 24 §13, flow I): prompt, provider, size preset, count. Results are candidates; `onPick`
 * attaches/keeps one. Shows the run (agent, steps, cost) while the provider works.
 */
export function GenerateImageDialog({ open, onOpenChange, brandId, seedPrompt, onPick, pickLabel = "Use this" }: {
  open: boolean; onOpenChange: (o: boolean) => void; brandId: string | null | undefined; contentId?: string; variantId?: string;
  seedPrompt?: string; onPick?: (asset: MediaAsset) => void; pickLabel?: string;
}) {
  const qc = useQueryClient();
  const [prompt, setPrompt] = useState("");
  const [negative, setNegative] = useState("");
  const [provider, setProvider] = useState("");
  const [preset, setPreset] = useState("square");
  const [count, setCount] = useState("1");
  const [runId, setRunId] = useState<string | null>(null);
  const [candidates, setCandidates] = useState<{ id: string; asset?: MediaAsset }[]>([]);
  const [picked, setPicked] = useState<Set<string>>(new Set());
  const [queued, setQueued] = useState(false);

  const reset = () => { setRunId(null); setCandidates([]); setPicked(new Set()); setQueued(false); };
  const absorb = (v: unknown) => {
    const { assets, ids } = extractAssets(v);
    setCandidates([...assets.map((a) => ({ id: a.id, asset: a })), ...ids.map((id) => ({ id }))]);
    void qc.invalidateQueries({ queryKey: ["media"] });
  };
  const gen = useMutation({
    mutationFn: () => mediaApi.generate({
      prompt, brand_id: brandId ?? null, size: SIZE_PRESETS.find((p) => p.id === preset)?.size ?? "1024x1024",
      n: Number(count), provider: provider.trim() || undefined, negative_prompt: negative.trim() || undefined,
    }),
    onMutate: reset,
    onSuccess: (res: GenerateResult) => {
      if (isRunAccepted(res)) setRunId(res.run_id);
      else if (!Array.isArray(res) && "status" in res && res.status === "queued" && !("id" in res)) { setQueued(true); void qc.invalidateQueries({ queryKey: ["media"] }); }
      else absorb(res);
    },
  });
  const onRunDone = (run: AiRun) => {
    if (run.status === "completed") absorb(run.result?.deliverables ?? run.result);
    else if (run.status === "failed") toast.error(run.error ?? "Image generation failed");
  };

  return (
    <Dialog open={open} onOpenChange={(o) => { if (!o) reset(); onOpenChange(o); }}>
      <DialogContent className="max-h-[90vh] overflow-y-auto sm:max-w-2xl">
        <DialogHeader>
          <DialogTitle className="flex items-center gap-2"><Sparkles className="h-4 w-4 text-ai" /> Generate image</DialogTitle>
          <DialogDescription>The visual agent calls your configured image provider. Generated assets are labelled AI-generated everywhere they are used.</DialogDescription>
        </DialogHeader>
        <div className="grid gap-4 sm:grid-cols-2">
          <div className="space-y-1.5 sm:col-span-2">
            <div className="flex items-center justify-between">
              <Label htmlFor="gen-prompt">Prompt</Label>
              {seedPrompt && <Button type="button" size="xs" variant="ghost" onClick={() => setPrompt(seedPrompt)}><Sparkles className="text-ai" /> Prompt from content</Button>}
            </div>
            <Textarea id="gen-prompt" rows={4} value={prompt} onChange={(e) => setPrompt(e.target.value)} placeholder="Overhead shot of a cold brew bottle on a wooden counter, morning light, brand teal accents" />
          </div>
          <div className="space-y-1.5 sm:col-span-2">
            <Label htmlFor="gen-neg">Negative prompt <span className="text-muted-foreground">(optional)</span></Label>
            <Input id="gen-neg" value={negative} onChange={(e) => setNegative(e.target.value)} placeholder="text, logos, real people" />
          </div>
          <div className="space-y-1.5">
            <Label>Size preset</Label>
            <Select value={preset} onValueChange={setPreset}>
              <SelectTrigger className="w-full"><SelectValue /></SelectTrigger>
              <SelectContent>{SIZE_PRESETS.map((p) => <SelectItem key={p.id} value={p.id}>{p.label} · {p.size} <span className="text-muted-foreground">({p.platforms})</span></SelectItem>)}</SelectContent>
            </Select>
          </div>
          <div className="grid grid-cols-2 gap-3">
            <div className="space-y-1.5">
              <Label>Count</Label>
              <Select value={count} onValueChange={setCount}>
                <SelectTrigger className="w-full"><SelectValue /></SelectTrigger>
                <SelectContent>{["1", "2", "3", "4"].map((c) => <SelectItem key={c} value={c}>{c}</SelectItem>)}</SelectContent>
              </Select>
            </div>
            <div className="space-y-1.5">
              <Label htmlFor="gen-provider">Provider</Label>
              <Input id="gen-provider" value={provider} onChange={(e) => setProvider(e.target.value)} placeholder="default" />
            </div>
          </div>
        </div>
        {gen.error && <QueryError error={gen.error} title="Generation was not started" notAvailableText="Image generation isn't enabled on this backend yet. Configure an image provider in Settings › AI." />}
        {runId && <RunCard runId={runId} title="Generating image" onDone={onRunDone} compact />}
        {queued && <p className="rounded-md bg-muted p-2 text-sm">Generating in the background — the images appear in the Media Library when the provider finishes.</p>}
        {candidates.length > 0 && (
          <div>
            <p className="mb-2 text-sm font-medium">Candidates</p>
            <div className="grid grid-cols-2 gap-3 sm:grid-cols-4">
              {candidates.map((c) => (
                <div key={c.id} className="space-y-1.5">
                  <MediaThumb asset={c.asset ?? { id: c.id, kind: "image" }} className="aspect-square w-full" />
                  {onPick && (
                    <Button size="xs" className="w-full" variant={picked.has(c.id) ? "secondary" : "default"} disabled={picked.has(c.id)}
                            onClick={async () => {
                              try {
                                const asset = c.asset ?? (await mediaApi.get(c.id));
                                onPick(asset);
                                setPicked((s) => new Set(s).add(c.id));
                              } catch (e) { toast.error(errorMessage(e)); }
                            }}>
                      {picked.has(c.id) ? <><Check /> Added</> : pickLabel}
                    </Button>
                  )}
                </div>
              ))}
            </div>
            <p className="mt-2 text-xs text-muted-foreground">Unpicked candidates stay in the Media Library.</p>
          </div>
        )}
        <DialogFooter>
          <span className="mr-auto self-center text-xs text-muted-foreground">visual · image provider · cost shown on the run</span>
          <Button variant="outline" onClick={() => onOpenChange(false)}>Close</Button>
          <Button onClick={() => gen.mutate()} disabled={!prompt.trim() || gen.isPending}>
            {gen.isPending ? <Loader2 className="animate-spin" /> : <Sparkles />} {candidates.length ? "Generate again" : `Generate ${count}`}
          </Button>
        </DialogFooter>
        {gen.isError && <p className="sr-only">{errorMessage(gen.error)}</p>}
      </DialogContent>
    </Dialog>
  );
}

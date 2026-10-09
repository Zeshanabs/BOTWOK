"use client";
import { useState } from "react";
import { Button } from "@/components/ui/button";
import { Checkbox } from "@/components/ui/checkbox";
import { Dialog, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle } from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Textarea } from "@/components/ui/textarea";
import { PlatformIcon } from "@/components/data/platform-icon";
import { FieldError, FormError, problemFieldErrors } from "@/components/data/form-errors";
import { isNotAvailable } from "@/components/data/async-states";
import { PLATFORMS } from "@/lib/platforms";
import { usePillars } from "@/features/brand/hooks";
import { useGenerateIdeas } from "../hooks";

export function GenerateIdeasDialog({ open, onOpenChange, brandId, onStarted }: { open: boolean; onOpenChange: (o: boolean) => void; brandId: string | null; onStarted: (runId: string) => void }) {
  const generate = useGenerateIdeas();
  const pillars = usePillars(brandId);
  const [count, setCount] = useState("10");
  const [selPillars, setSelPillars] = useState<string[]>([]);
  const [platforms, setPlatforms] = useState<string[]>([]);
  const [prompt, setPrompt] = useState("");
  const errors = problemFieldErrors(generate.error);

  function submit(e: React.FormEvent) {
    e.preventDefault();
    if (!brandId) return;
    const n = Math.max(1, Math.min(50, Number(count) || 10));
    generate.mutate(
      { brand_id: brandId, count: n, pillars: selPillars.length ? selPillars : undefined, platforms: platforms.length ? platforms : undefined, from: prompt.trim() ? { prompt: prompt.trim() } : undefined },
      { onSuccess: (d) => { onStarted(d.run_id); onOpenChange(false); setPrompt(""); } },
    );
  }

  return (
    <Dialog open={open} onOpenChange={(o) => { if (!o) generate.reset(); onOpenChange(o); }}>
      <DialogContent className="max-h-[90vh] overflow-y-auto sm:max-w-lg">
        <DialogHeader>
          <DialogTitle>✦ Generate ideas</DialogTitle>
          <DialogDescription>The ideation agent (cheap tier) uses your brand context, pillar mix, trends and saved research. Near-duplicates of recent ideas are skipped.</DialogDescription>
        </DialogHeader>
        <form id="gen-ideas" onSubmit={submit} className="space-y-4">
          <div className="space-y-1">
            <Label htmlFor="gi-count">How many</Label>
            <Input id="gi-count" type="number" min={1} max={50} value={count} onChange={(e) => setCount(e.target.value)} className="w-28" aria-invalid={!!errors.count} />
            <FieldError errors={errors} name="count" />
          </div>
          {(pillars.data ?? []).length > 0 && (
            <fieldset className="space-y-2">
              <legend className="text-sm font-medium">Pillars <span className="font-normal text-muted-foreground">(optional — defaults to under-served ones)</span></legend>
              <div className="grid grid-cols-2 gap-2">
                {pillars.data?.map((p) => (
                  <label key={p.id} className="flex items-center gap-2 text-sm">
                    <Checkbox checked={selPillars.includes(p.id)} onCheckedChange={(c) => setSelPillars((s) => (c ? [...s, p.id] : s.filter((x) => x !== p.id)))} />{p.name}
                  </label>
                ))}
              </div>
            </fieldset>
          )}
          <fieldset className="space-y-2">
            <legend className="text-sm font-medium">Platforms <span className="font-normal text-muted-foreground">(optional)</span></legend>
            <div className="flex flex-wrap gap-2">
              {PLATFORMS.map((p) => {
                const on = platforms.includes(p.id);
                return (
                  <button key={p.id} type="button" aria-pressed={on} onClick={() => setPlatforms((s) => (on ? s.filter((x) => x !== p.id) : [...s, p.id]))}
                          className={`flex items-center gap-1 rounded-full border px-2 py-1 text-xs ${on ? "border-primary bg-primary/10" : "hover:bg-accent"}`}>
                    <PlatformIcon platform={p.id} size={14} />{p.label}
                  </button>
                );
              })}
            </div>
          </fieldset>
          <div className="space-y-1">
            <Label htmlFor="gi-prompt">Goals or angle <span className="font-normal text-muted-foreground">(optional)</span></Label>
            <Textarea id="gi-prompt" rows={3} value={prompt} onChange={(e) => setPrompt(e.target.value)} placeholder="e.g. Drive sign-ups for the October webinar; practical, no hype" />
          </div>
          {isNotAvailable(generate.error) ? <p className="text-sm text-muted-foreground">Idea generation isn&apos;t available on this install yet. You can still add ideas manually.</p> : <FormError error={Object.keys(errors).length ? null : generate.error} />}
        </form>
        <DialogFooter>
          <Button variant="outline" onClick={() => onOpenChange(false)}>Cancel</Button>
          <Button type="submit" form="gen-ideas" disabled={!brandId || generate.isPending}>{generate.isPending ? "Starting…" : "Generate"}</Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}

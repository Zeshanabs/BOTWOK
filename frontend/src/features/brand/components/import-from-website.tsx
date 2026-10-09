"use client";
/**
 * Website import (doc 25 flow B2): POST /brands/{id}/import-from-website → poll the AI run → per-field proposals with
 * confirm checkboxes → apply via PUT /brands/{id}/settings (+ PATCH brand fields, POST pillars). Nothing is stored
 * until the user accepts it. 404/501 ("AI not available") degrades to a calm skip.
 */
import { useState } from "react";
import { useQueryClient } from "@tanstack/react-query";
import { toast } from "sonner";
import { Globe, Sparkles } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Checkbox } from "@/components/ui/checkbox";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { NotAvailable, errorMessage, isNotAvailable } from "@/components/data/async-states";
import { FormError } from "@/components/data/form-errors";
import { humanize, truncate } from "@/lib/formatters";
import { RunProgress } from "@/features/ai/components/run-progress";
import type { AiRun } from "@/features/ai/types";
import { brandApi } from "../api";
import { brandKeys } from "../hooks";
import { SETTINGS_SECTIONS, type BrandSettingsUpdate, type SettingsSection } from "../types";

const BRAND_FIELDS = ["description", "industry", "sub_industry", "timezone", "languages", "geography"];

interface Proposal {
  key: string;
  kind: "settings" | "brand" | "pillar";
  section?: SettingsSection;
  field: string;
  label: string;
  value: unknown;
  confidence?: number;
  sources?: string[];
}

function unwrap(v: unknown): { value: unknown; confidence?: number; sources?: string[] } {
  if (v && typeof v === "object" && !Array.isArray(v) && "value" in (v as Record<string, unknown>)) {
    const o = v as { value: unknown; confidence?: number; source_ids?: string[]; sources?: string[] };
    return { value: o.value, confidence: o.confidence, sources: o.source_ids ?? o.sources };
  }
  return { value: v };
}

function preview(v: unknown): string {
  if (v === null || v === undefined) return "—";
  if (typeof v === "string") return truncate(v, 220);
  if (typeof v === "number" || typeof v === "boolean") return String(v);
  if (Array.isArray(v)) {
    if (v.every((x) => typeof x === "string")) return truncate((v as string[]).join(", "), 220);
    return truncate(v.map((x) => (x && typeof x === "object" ? String((x as Record<string, unknown>).name ?? (x as Record<string, unknown>).text ?? (x as Record<string, unknown>).title ?? JSON.stringify(x)) : String(x))).join(" · "), 220);
  }
  return truncate(Object.entries(v as Record<string, unknown>).filter(([, x]) => x !== null && x !== undefined && x !== "").map(([k, x]) => `${humanize(k)}: ${typeof x === "object" ? JSON.stringify(x) : String(x)}`).join(" · "), 220);
}

export function proposalsFromRun(run: AiRun): Proposal[] {
  const result = (run.result ?? {}) as Record<string, unknown>;
  const deliverables = result.deliverables as Record<string, unknown> | undefined;
  const proposed = (deliverables && !Array.isArray(deliverables) ? (deliverables.proposed_settings ?? deliverables) : result.proposed_settings) as Record<string, unknown> | undefined;
  if (!proposed || typeof proposed !== "object") return [];
  const out: Proposal[] = [];
  for (const [k, raw] of Object.entries(proposed)) {
    const { value, confidence, sources } = unwrap(raw);
    if (value === null || value === undefined) continue;
    if ((SETTINGS_SECTIONS as string[]).includes(k) && typeof value === "object" && !Array.isArray(value)) {
      for (const [f, rawF] of Object.entries(value as Record<string, unknown>)) {
        const u = unwrap(rawF);
        if (u.value === null || u.value === undefined || (Array.isArray(u.value) && !u.value.length)) continue;
        out.push({ key: `${k}.${f}`, kind: "settings", section: k as SettingsSection, field: f, label: `${humanize(k)} › ${humanize(f)}`, value: u.value, confidence: u.confidence ?? confidence, sources: u.sources ?? sources });
      }
    } else if (BRAND_FIELDS.includes(k)) {
      out.push({ key: `brand.${k}`, kind: "brand", field: k, label: humanize(k), value, confidence, sources });
    } else if (k === "pillars" && Array.isArray(value)) {
      value.forEach((p, i) => {
        const u = unwrap(p);
        const pv = u.value as Record<string, unknown>;
        if (pv && typeof pv === "object" && pv.name) out.push({ key: `pillar.${i}`, kind: "pillar", field: "pillar", label: `Pillar › ${String(pv.name)}`, value: pv, confidence: u.confidence ?? confidence, sources: u.sources });
      });
    }
  }
  return out;
}

type Phase = { name: "form" } | { name: "running"; runId: string } | { name: "review"; proposals: Proposal[]; runId: string } | { name: "failed"; message: string } | { name: "unavailable" } | { name: "done"; count: number };

export function ImportFromWebsite({ brandId, defaultUrl, onDone, onSkip, skipLabel = "Skip this step" }: {
  brandId: string;
  defaultUrl?: string | null;
  onDone?: (appliedCount: number) => void;
  onSkip?: () => void;
  skipLabel?: string;
}) {
  const qc = useQueryClient();
  const [url, setUrl] = useState(defaultUrl ?? "");
  const [phase, setPhase] = useState<Phase>({ name: "form" });
  const [checked, setChecked] = useState<Record<string, boolean>>({});
  const [startError, setStartError] = useState<unknown>(null);
  const [busy, setBusy] = useState(false);

  async function start(e?: React.FormEvent) {
    e?.preventDefault();
    const u = url.trim();
    if (!u) return;
    setBusy(true); setStartError(null);
    try {
      const d = await brandApi.importFromWebsite(brandId, /^https?:\/\//i.test(u) ? u : `https://${u}`);
      setPhase({ name: "running", runId: d.run_id });
    } catch (err) {
      if (isNotAvailable(err)) setPhase({ name: "unavailable" });
      else setStartError(err);
    } finally { setBusy(false); }
  }

  function onFinished(run: AiRun) {
    if (run.status !== "completed") { setPhase({ name: "failed", message: run.error || `The import ${run.status === "cancelled" ? "was cancelled" : "failed"}.` }); return; }
    const proposals = proposalsFromRun(run);
    setChecked(Object.fromEntries(proposals.map((p) => [p.key, p.confidence === undefined || p.confidence >= 0.6])));
    setPhase({ name: "review", proposals, runId: run.id });
  }

  async function apply(proposals: Proposal[]) {
    const accepted = proposals.filter((p) => checked[p.key]);
    if (!accepted.length) { onDone?.(0); setPhase({ name: "done", count: 0 }); return; }
    setBusy(true);
    try {
      const settingsProps = accepted.filter((p) => p.kind === "settings");
      if (settingsProps.length) {
        const current = await brandApi.settings(brandId).catch(() => ({}) as Record<string, unknown>);
        const body: BrandSettingsUpdate = {};
        for (const p of settingsProps) {
          const section = p.section as SettingsSection;
          const base = (body[section] ?? (current as Record<string, unknown>)[section] ?? {}) as Record<string, unknown>;
          (body as Record<string, unknown>)[section] = { ...base, [p.field]: p.value };
        }
        await brandApi.putSettings(brandId, body);
      }
      const brandProps = accepted.filter((p) => p.kind === "brand");
      if (brandProps.length) await brandApi.update(brandId, Object.fromEntries(brandProps.map((p) => [p.field, p.value])));
      for (const p of accepted.filter((x) => x.kind === "pillar")) {
        const v = p.value as Record<string, unknown>;
        await brandApi.createPillar(brandId, { name: String(v.name), description: (v.description as string) ?? null, share_target: typeof v.share_target === "number" ? v.share_target : null, examples: Array.isArray(v.examples) ? (v.examples as string[]) : [] });
      }
      qc.invalidateQueries({ queryKey: ["brands"] });
      toast.success(`Applied ${accepted.length} field${accepted.length === 1 ? "" : "s"} from your website`);
      setPhase({ name: "done", count: accepted.length });
      onDone?.(accepted.length);
    } catch (err) {
      toast.error(errorMessage(err, "Couldn't apply the selected fields"));
      qc.invalidateQueries({ queryKey: brandKeys.settings(brandId) });
    } finally { setBusy(false); }
  }

  if (phase.name === "unavailable") {
    return (
      <div className="space-y-3">
        <NotAvailable title="AI import isn't available yet" description="No AI provider is configured on this install. You can fill these fields by hand in Brand Settings at any time." />
        {onSkip && <div className="flex justify-end"><Button onClick={onSkip}>{skipLabel}</Button></div>}
      </div>
    );
  }

  if (phase.name === "form" || phase.name === "failed") {
    return (
      <form onSubmit={start} className="space-y-3">
        <p className="text-sm text-muted-foreground">We read public pages of your site (robots.txt respected) and propose brand fields. Nothing is saved until you accept it.</p>
        <div className="space-y-1">
          <Label htmlFor="imp-url">Website URL</Label>
          <div className="flex gap-2">
            <Input id="imp-url" value={url} onChange={(e) => setUrl(e.target.value)} placeholder="https://acme.com" inputMode="url" />
            <Button type="submit" disabled={!url.trim() || busy}><Globe className="h-4 w-4" /> {busy ? "Starting…" : phase.name === "failed" ? "Try again" : "Import"}</Button>
          </div>
        </div>
        {phase.name === "failed" && <p role="alert" className="text-sm text-destructive">Couldn&apos;t read that site: {phase.message} Try another URL, or fill these later in Brand Settings.</p>}
        <FormError error={startError} />
        {onSkip && <div className="flex justify-end"><Button type="button" variant="ghost" onClick={onSkip}>{skipLabel}</Button></div>}
      </form>
    );
  }

  if (phase.name === "running") {
    return (
      <div className="space-y-3">
        <RunProgress runId={phase.runId} title="Reading your website" onFinished={onFinished} />
        {onSkip && <div className="flex justify-end"><Button variant="ghost" onClick={onSkip}>{skipLabel}</Button></div>}
      </div>
    );
  }

  if (phase.name === "done") {
    return (
      <div className="space-y-3 text-sm">
        <p>{phase.count ? `Applied ${phase.count} proposed field${phase.count === 1 ? "" : "s"}. They're marked as coming from your website until edited.` : "Nothing was applied."}</p>
        <Button variant="outline" size="sm" onClick={() => setPhase({ name: "form" })}>Import again</Button>
      </div>
    );
  }

  const proposals = phase.proposals;
  const n = proposals.filter((p) => checked[p.key]).length;
  return (
    <div className="space-y-3">
      <div className="flex items-center justify-between gap-2">
        <p className="flex items-center gap-1 text-sm font-medium"><Sparkles className="h-4 w-4 text-ai" /> Proposed fields ({proposals.length})</p>
        {proposals.length > 0 && <Button size="xs" variant="ghost" onClick={() => setChecked(Object.fromEntries(proposals.map((p) => [p.key, n < proposals.length])))}>{n < proposals.length ? "Select all" : "Select none"}</Button>}
      </div>
      {!proposals.length ? <p className="rounded-lg border border-dashed p-4 text-sm text-muted-foreground">The import finished but didn&apos;t propose any fields. You can fill these later in Brand Settings.</p> : (
        <ul className="max-h-[50vh] divide-y overflow-y-auto rounded-lg border">
          {proposals.map((p) => (
            <li key={p.key} className="flex items-start gap-3 p-3">
              <Checkbox id={`prop-${p.key}`} checked={!!checked[p.key]} onCheckedChange={(c) => setChecked((s) => ({ ...s, [p.key]: !!c }))} className="mt-0.5" />
              <label htmlFor={`prop-${p.key}`} className="min-w-0 flex-1 cursor-pointer text-sm">
                <span className="font-medium">{p.label}</span>
                {p.confidence !== undefined && <span className={`ml-2 text-xs ${p.confidence < 0.6 ? "text-amber-700 dark:text-amber-300" : "text-muted-foreground"}`}>confidence {Math.round(p.confidence * 100)}%</span>}
                <span className="mt-0.5 block break-words text-muted-foreground">{preview(p.value)}</span>
                {p.sources?.length ? <span className="mt-0.5 block text-xs text-muted-foreground">{p.sources.length} source{p.sources.length === 1 ? "" : "s"}</span> : null}
              </label>
            </li>
          ))}
        </ul>
      )}
      <div className="flex flex-wrap justify-end gap-2">
        {onSkip && <Button variant="ghost" onClick={onSkip}>{skipLabel}</Button>}
        <Button disabled={busy} onClick={() => apply(proposals)}>{busy ? "Applying…" : n ? `Accept ${n} & continue` : "Continue without applying"}</Button>
      </div>
    </div>
  );
}

"use client";
/** Visual Identity, Keywords·Hashtags·CTAs and Goals editors (doc 24 §21). */
import { useRef, useState } from "react";
import { useQueryClient } from "@tanstack/react-query";
import { toast } from "sonner";
import { Upload } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { Textarea } from "@/components/ui/textarea";
import { TagInput } from "@/components/data/tag-input";
import { PlatformIcon } from "@/components/data/platform-icon";
import { errorMessage, isNotAvailable } from "@/components/data/async-states";
import { PLATFORMS } from "@/lib/platforms";
import { uploadBrandAsset } from "../api";
import { brandKeys } from "../hooks";
import type { CTA, Goals, Objective, Visual } from "../types";
import { Field, RowList, SaveBar, useSectionSave, type SectionProps } from "./section-kit";

const HEX = /^#(?:[0-9a-fA-F]{3}|[0-9a-fA-F]{6}|[0-9a-fA-F]{8})$/;

function ColorField({ id, label, value, onChange, disabled }: { id: string; label: string; value: string; onChange: (v: string) => void; disabled: boolean }) {
  const valid = !value || HEX.test(value);
  return (
    <Field label={label} htmlFor={id}>
      <div className="flex items-center gap-2">
        <input type="color" aria-label={`${label} picker`} value={HEX.test(value) && value.length === 7 ? value : "#ffffff"} onChange={(e) => onChange(e.target.value.toUpperCase())} disabled={disabled} className="h-9 w-10 cursor-pointer rounded border bg-transparent p-0.5" />
        <Input id={id} value={value} onChange={(e) => onChange(e.target.value)} placeholder="#0B2545" disabled={disabled} aria-invalid={!valid} className="font-mono" />
      </div>
      {!valid && <p className="text-xs text-destructive">Use a hex color like #0B2545</p>}
    </Field>
  );
}

export function VisualSection({ brand, settings, readOnly }: SectionProps) {
  const qc = useQueryClient();
  const { save, pending, error } = useSectionSave(brand.id);
  const v: Visual = settings.visual ?? {};
  const fileRef = useRef<HTMLInputElement>(null);
  const [primary, setPrimary] = useState(v.colors?.primary ?? "");
  const [secondary, setSecondary] = useState(v.colors?.secondary ?? "");
  const [accent, setAccent] = useState(v.colors?.accent ?? "");
  const [neutral, setNeutral] = useState<string[]>(v.colors?.neutral ?? []);
  const [heading, setHeading] = useState(v.fonts?.heading ?? "");
  const [body, setBody] = useState(v.fonts?.body ?? "");
  const [imagery, setImagery] = useState(v.imagery_style ?? "");
  const [dos, setDos] = useState<string[]>(v.dos ?? []);
  const [donts, setDonts] = useState<string[]>(v.donts ?? []);
  const [logos, setLogos] = useState<string[]>(v.logo_asset_ids ?? []);
  const [uploading, setUploading] = useState(false);
  const allValid = [primary, secondary, accent, ...neutral].every((c) => !c || HEX.test(c));

  async function onFile(file: File | undefined) {
    if (!file) return;
    if (!/^image\/(png|jpe?g|webp)$/.test(file.type)) { toast.error("Upload a PNG, JPEG or WebP logo (SVG is not accepted)"); return; }
    setUploading(true);
    try {
      const { assetId } = await uploadBrandAsset(brand.id, file, "logo");
      const next = [...logos, assetId];
      setLogos(next);
      save({ visual: { ...v, logo_asset_ids: next } });
      qc.invalidateQueries({ queryKey: brandKeys.detail(brand.id) });
    } catch (e) {
      toast.error(isNotAvailable(e) ? "Media uploads aren't available on this install yet." : errorMessage(e, "Logo upload failed"));
    } finally {
      setUploading(false);
      if (fileRef.current) fileRef.current.value = "";
    }
  }

  return (
    <div className="space-y-5">
      <section className="space-y-2">
        <h3 className="text-sm font-semibold">Logo</h3>
        <p className="text-xs text-muted-foreground">{logos.length ? `${logos.length} logo file${logos.length === 1 ? "" : "s"} on file.` : "No logo uploaded yet."} PNG, JPEG or WebP; EXIF is stripped on upload.</p>
        {!readOnly && (
          <>
            <input ref={fileRef} type="file" accept="image/png,image/jpeg,image/webp" className="sr-only" id="logo-file" onChange={(e) => onFile(e.target.files?.[0])} />
            <Button variant="outline" size="sm" disabled={uploading} onClick={() => fileRef.current?.click()}><Upload className="h-3 w-3" /> {uploading ? "Uploading…" : "Upload logo"}</Button>
          </>
        )}
      </section>
      <section className="space-y-3">
        <h3 className="text-sm font-semibold">Colors</h3>
        <div className="grid gap-4 sm:grid-cols-3">
          <ColorField id="c-primary" label="Primary" value={primary} onChange={setPrimary} disabled={readOnly} />
          <ColorField id="c-secondary" label="Secondary" value={secondary} onChange={setSecondary} disabled={readOnly} />
          <ColorField id="c-accent" label="Accent" value={accent} onChange={setAccent} disabled={readOnly} />
        </div>
        <Field label="Neutrals" htmlFor="c-neutral" hint="Hex codes, Enter to add">
          <TagInput id="c-neutral" value={neutral} onChange={setNeutral} disabled={readOnly} transform={(s) => (s.startsWith("#") ? s : `#${s}`).toUpperCase()} />
        </Field>
        <div className="flex gap-1" aria-hidden>{[primary, secondary, accent, ...neutral].filter((c) => HEX.test(c)).map((c, i) => <span key={`${c}-${i}`} className="h-6 w-6 rounded border" style={{ background: c }} />)}</div>
      </section>
      <section className="grid gap-4 sm:grid-cols-2">
        <Field label="Heading font" htmlFor="f-head"><Input id="f-head" value={heading} onChange={(e) => setHeading(e.target.value)} disabled={readOnly} /></Field>
        <Field label="Body font" htmlFor="f-body"><Input id="f-body" value={body} onChange={(e) => setBody(e.target.value)} disabled={readOnly} /></Field>
      </section>
      <Field label="Image style" htmlFor="v-img"><Textarea id="v-img" rows={2} value={imagery} onChange={(e) => setImagery(e.target.value)} disabled={readOnly} placeholder="e.g. warm natural light, real customers, no stock-photo handshakes" /></Field>
      <div className="grid gap-4 sm:grid-cols-2">
        <Field label="Visual do's" htmlFor="v-dos"><TagInput id="v-dos" value={dos} onChange={setDos} disabled={readOnly} /></Field>
        <Field label="Visual don'ts" htmlFor="v-donts"><TagInput id="v-donts" value={donts} onChange={setDonts} disabled={readOnly} /></Field>
      </div>
      <SaveBar readOnly={readOnly} pending={pending} error={error} dirty={false}
               onSave={() => { if (!allValid) { toast.error("Fix the invalid colors first"); return; } save({ visual: { ...v, colors: { primary: primary || null, secondary: secondary || null, accent: accent || null, neutral }, fonts: { heading: heading || null, body: body || null }, imagery_style: imagery || null, dos, donts, logo_asset_ids: logos } }); }} />
    </div>
  );
}

const hashtag = (s: string) => `#${s.replace(/^#+/, "").replace(/\s+/g, "")}`;

export function KeywordsSection({ brand, settings, readOnly }: SectionProps) {
  const { save, pending, error } = useSectionSave(brand.id);
  const t = settings.topics ?? {};
  const [keywords, setKeywords] = useState<string[]>(t.keywords ?? []);
  const [core, setCore] = useState<string[]>(t.hashtags?.core ?? []);
  const [campaign, setCampaign] = useState<string[]>(t.hashtags?.campaign ?? []);
  const [banned, setBanned] = useState<string[]>(t.hashtags?.banned ?? []);
  const [ctas, setCtas] = useState<CTA[]>(t.ctas ?? []);
  return (
    <div className="space-y-4">
      <Field label="Keywords" htmlFor="k-kw" hint="Also used by trend scanning and research suggestions."><TagInput id="k-kw" value={keywords} onChange={setKeywords} disabled={readOnly} /></Field>
      <div className="grid gap-4 sm:grid-cols-3">
        <Field label="Core hashtags" htmlFor="k-core"><TagInput id="k-core" value={core} onChange={setCore} transform={hashtag} disabled={readOnly} /></Field>
        <Field label="Campaign hashtags" htmlFor="k-camp"><TagInput id="k-camp" value={campaign} onChange={setCampaign} transform={hashtag} disabled={readOnly} /></Field>
        <Field label="Banned hashtags" htmlFor="k-ban"><TagInput id="k-ban" value={banned} onChange={setBanned} transform={hashtag} disabled={readOnly} /></Field>
      </div>
      <h3 className="pt-2 text-sm font-semibold">CTA library</h3>
      <RowList<CTA> items={ctas} onChange={setCtas} readOnly={readOnly} empty="No CTAs yet." addLabel="Add CTA" make={() => ({ text: "", goal: "", url: "" })}
        render={(c, update, i) => (
          <div className="grid gap-2 sm:grid-cols-3">
            <Input aria-label={`CTA ${i + 1} text`} placeholder="Text, e.g. Book a demo" value={c.text} onChange={(e) => update({ text: e.target.value })} disabled={readOnly} />
            <Input aria-label={`CTA ${i + 1} goal`} placeholder="Goal, e.g. leads" value={c.goal ?? ""} onChange={(e) => update({ goal: e.target.value })} disabled={readOnly} />
            <Input aria-label={`CTA ${i + 1} URL`} placeholder="https://…" value={c.url ?? ""} onChange={(e) => update({ url: e.target.value })} disabled={readOnly} />
          </div>
        )} />
      <SaveBar readOnly={readOnly} pending={pending} error={error} dirty={false}
               onSave={() => save({ topics: { ...t, keywords, hashtags: { core, campaign, banned }, ctas: ctas.filter((c) => c.text.trim()).map((c) => ({ text: c.text.trim(), goal: c.goal || null, url: c.url || null })) } })} />
    </div>
  );
}

const FUNNEL = ["awareness", "consideration", "conversion", "retention", "advocacy"];
const NONE = "__none";

export function GoalsSection({ brand, settings, readOnly }: SectionProps) {
  const { save, pending, error } = useSectionSave(brand.id);
  const g: Goals = settings.goals ?? {};
  const [objectives, setObjectives] = useState<Objective[]>(g.objectives ?? []);
  const [priority, setPriority] = useState<string[]>(g.priority_platforms ?? []);
  const [funnel, setFunnel] = useState<string>(g.funnel_focus ?? NONE);
  const [cadence, setCadence] = useState<Record<string, string>>(
    Object.fromEntries(Object.entries(settings.platforms ?? {}).filter(([, v]) => v?.cadence_per_week != null).map(([k, v]) => [k, String(v?.cadence_per_week)])),
  );

  function onSave() {
    const platforms = { ...(settings.platforms ?? {}) };
    for (const p of priority) {
      const n = cadence[p];
      if (n !== undefined && n !== "") platforms[p] = { ...(platforms[p] ?? {}), cadence_per_week: Math.max(0, Math.min(100, Number(n) || 0)) };
    }
    save({
      goals: { ...g, objectives: objectives.filter((o) => o.name.trim()).map((o) => ({ ...o, target: o.target === "" ? null : o.target })), priority_platforms: priority, funnel_focus: funnel === NONE ? null : funnel },
      platforms,
    });
  }

  return (
    <div className="space-y-5">
      <section className="space-y-2">
        <h3 className="text-sm font-semibold">Objectives & KPIs</h3>
        <RowList<Objective> items={objectives} onChange={setObjectives} readOnly={readOnly} empty="No objectives yet — e.g. Grow LinkedIn followers to 5k by Q4." addLabel="Add objective" make={() => ({ name: "", metric: "", target: "", by: "" })}
          render={(o, update, i) => (
            <div className="grid gap-2 sm:grid-cols-4">
              <Input aria-label={`Objective ${i + 1}`} placeholder="Objective" value={o.name} onChange={(e) => update({ name: e.target.value })} disabled={readOnly} className="sm:col-span-2" />
              <Input aria-label={`Objective ${i + 1} metric`} placeholder="Metric" value={o.metric ?? ""} onChange={(e) => update({ metric: e.target.value })} disabled={readOnly} />
              <div className="flex gap-2">
                <Input aria-label={`Objective ${i + 1} target`} placeholder="Target" value={o.target == null ? "" : String(o.target)} onChange={(e) => update({ target: e.target.value })} disabled={readOnly} />
                <Input aria-label={`Objective ${i + 1} by`} placeholder="By" value={o.by ?? ""} onChange={(e) => update({ by: e.target.value })} disabled={readOnly} />
              </div>
            </div>
          )} />
      </section>
      <section className="space-y-2">
        <h3 className="text-sm font-semibold">Priority platforms & posts per week</h3>
        <div className="flex flex-wrap gap-2">
          {PLATFORMS.map((p) => {
            const on = priority.includes(p.id);
            return (
              <button key={p.id} type="button" disabled={readOnly} aria-pressed={on} onClick={() => setPriority((s) => (on ? s.filter((x) => x !== p.id) : [...s, p.id]))}
                      className={`flex items-center gap-1 rounded-full border px-2 py-1 text-xs ${on ? "border-primary bg-primary/10" : "hover:bg-accent"}`}>
                <PlatformIcon platform={p.id} size={14} />{p.label}
              </button>
            );
          })}
        </div>
        {priority.length > 0 && (
          <div className="grid gap-2 sm:grid-cols-3">
            {priority.map((p) => (
              <label key={p} className="flex items-center gap-2 text-sm">
                <PlatformIcon platform={p} size={18} />
                <Input type="number" min={0} max={100} className="h-8 w-20" aria-label={`Posts per week on ${p}`} value={cadence[p] ?? ""} onChange={(e) => setCadence((c) => ({ ...c, [p]: e.target.value }))} disabled={readOnly} />
                <span className="text-xs text-muted-foreground">/ week</span>
              </label>
            ))}
          </div>
        )}
      </section>
      <Field label="Funnel focus" htmlFor="g-funnel">
        <Select value={funnel} onValueChange={setFunnel} disabled={readOnly}>
          <SelectTrigger id="g-funnel" className="w-full sm:w-64"><SelectValue /></SelectTrigger>
          <SelectContent><SelectItem value={NONE}>Not set</SelectItem>{FUNNEL.map((f) => <SelectItem key={f} value={f}>{f}</SelectItem>)}</SelectContent>
        </Select>
      </Field>
      <SaveBar readOnly={readOnly} pending={pending} error={error} dirty={false} onSave={onSave} />
    </div>
  );
}

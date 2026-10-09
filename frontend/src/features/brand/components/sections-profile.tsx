"use client";
/** Profile, Audience and Voice & Style editors (doc 24 §21). */
import { useState } from "react";
import { toast } from "sonner";
import { Input } from "@/components/ui/input";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { Textarea } from "@/components/ui/textarea";
import { TagInput } from "@/components/data/tag-input";
import { FieldError, problemFieldErrors } from "@/components/data/form-errors";
import { errorMessage } from "@/components/data/async-states";
import { useUpdateBrand } from "../hooks";
import type { Audience, Persona, Tone, Voice, WritingSample } from "../types";
import { Field, RowList, SaveBar, useSectionSave, type SectionProps } from "./section-kit";
import { TimezoneInput } from "./timezone-input";

const NONE = "__none";

export function ProfileSection({ brand, settings, readOnly }: SectionProps) {
  const updateBrand = useUpdateBrand(brand.id);
  const sectionSave = useSectionSave(brand.id);
  const [name, setName] = useState(brand.name);
  const [description, setDescription] = useState(brand.description ?? "");
  const [industry, setIndustry] = useState(brand.industry ?? "");
  const [website, setWebsite] = useState(brand.website ?? "");
  const [timezone, setTimezone] = useState(brand.timezone ?? "UTC");
  const [languages, setLanguages] = useState<string[]>(brand.languages ?? []);
  const [services, setServices] = useState<string[]>(settings.offering?.services ?? []);
  const [differentiators, setDifferentiators] = useState<string[]>(settings.offering?.differentiators ?? []);
  const [proof, setProof] = useState<string[]>(settings.offering?.proof_points ?? []);
  const errors = problemFieldErrors(updateBrand.error);

  function save() {
    updateBrand.mutate(
      { name: name.trim(), description: description.trim() || null, industry: industry.trim() || null, website: website.trim() ? (/^https?:\/\//.test(website.trim()) ? website.trim() : `https://${website.trim()}`) : null, timezone: timezone.trim() || "UTC", languages },
      {
        onSuccess: () => sectionSave.save({ offering: { ...(settings.offering ?? {}), services, differentiators, proof_points: proof } }),
        onError: (e) => toast.error(errorMessage(e, "Couldn't save the profile")),
      },
    );
  }

  return (
    <div className="space-y-4">
      <div className="grid gap-4 sm:grid-cols-2">
        <Field label="Name" htmlFor="p-name"><Input id="p-name" value={name} onChange={(e) => setName(e.target.value)} disabled={readOnly} aria-invalid={!!errors.name} /><FieldError errors={errors} name="name" /></Field>
        <Field label="Industry" htmlFor="p-ind"><Input id="p-ind" value={industry} onChange={(e) => setIndustry(e.target.value)} disabled={readOnly} /></Field>
        <Field label="Website" htmlFor="p-web"><Input id="p-web" value={website} onChange={(e) => setWebsite(e.target.value)} disabled={readOnly} aria-invalid={!!errors.website} /><FieldError errors={errors} name="website" /></Field>
        <Field label="Timezone" htmlFor="p-tz"><TimezoneInput id="p-tz" value={timezone} onChange={setTimezone} disabled={readOnly} invalid={!!errors.timezone} /><FieldError errors={errors} name="timezone" /></Field>
      </div>
      <Field label="Description" htmlFor="p-desc"><Textarea id="p-desc" rows={3} value={description} onChange={(e) => setDescription(e.target.value)} disabled={readOnly} /></Field>
      <Field label="Languages" htmlFor="p-lang" hint="ISO codes, e.g. en, de"><TagInput id="p-lang" value={languages} onChange={setLanguages} disabled={readOnly} /></Field>
      <h3 className="pt-2 text-sm font-semibold">Offering</h3>
      <Field label="Products & services" htmlFor="p-svc"><TagInput id="p-svc" value={services} onChange={setServices} disabled={readOnly} /></Field>
      <Field label="Differentiators" htmlFor="p-diff"><TagInput id="p-diff" value={differentiators} onChange={setDifferentiators} disabled={readOnly} /></Field>
      <Field label="Proof points" htmlFor="p-proof" hint="Awards, numbers, customers — the AI only cites what's listed here."><TagInput id="p-proof" value={proof} onChange={setProof} disabled={readOnly} /></Field>
      <SaveBar onSave={save} pending={updateBrand.isPending || sectionSave.pending} error={sectionSave.error} readOnly={readOnly} dirty={false} />
    </div>
  );
}

export function AudienceSection({ brand, settings, readOnly }: SectionProps) {
  const { save, pending, error } = useSectionSave(brand.id);
  const a: Audience = settings.audience ?? {};
  const [summary, setSummary] = useState(a.summary ?? "");
  const [market, setMarket] = useState<string>(a.market ?? NONE);
  const [demographics, setDemographics] = useState(a.demographics ?? "");
  const [geography, setGeography] = useState<string[]>(a.geography ?? []);
  const [personas, setPersonas] = useState<Persona[]>(a.personas ?? []);

  return (
    <div className="space-y-4">
      <Field label="Audience summary" htmlFor="a-sum"><Textarea id="a-sum" rows={3} value={summary} onChange={(e) => setSummary(e.target.value)} disabled={readOnly} placeholder="Who you're talking to, in one or two sentences" /></Field>
      <div className="grid gap-4 sm:grid-cols-2">
        <Field label="Market" htmlFor="a-mkt">
          <Select value={market} onValueChange={setMarket} disabled={readOnly}>
            <SelectTrigger id="a-mkt" className="w-full"><SelectValue /></SelectTrigger>
            <SelectContent><SelectItem value={NONE}>Not set</SelectItem><SelectItem value="b2b">B2B</SelectItem><SelectItem value="b2c">B2C</SelectItem><SelectItem value="b2b2c">B2B2C</SelectItem><SelectItem value="both">Both</SelectItem></SelectContent>
          </Select>
        </Field>
        <Field label="Geography" htmlFor="a-geo"><TagInput id="a-geo" value={geography} onChange={setGeography} disabled={readOnly} /></Field>
      </div>
      <Field label="Demographics" htmlFor="a-demo"><Textarea id="a-demo" rows={2} value={demographics} onChange={(e) => setDemographics(e.target.value)} disabled={readOnly} /></Field>
      <h3 className="pt-2 text-sm font-semibold">Segments / personas</h3>
      <RowList<Persona> items={personas} onChange={setPersonas} readOnly={readOnly} empty="No personas yet." addLabel="Add persona" make={() => ({ name: "", role: "", pains: [], goals: [] })}
        render={(p, update, i) => (
          <>
            <div className="grid gap-2 sm:grid-cols-2">
              <Input aria-label={`Persona ${i + 1} name`} placeholder="Name, e.g. Home barista" value={p.name} onChange={(e) => update({ name: e.target.value })} disabled={readOnly} />
              <Input aria-label={`Persona ${i + 1} role`} placeholder="Role" value={p.role ?? ""} onChange={(e) => update({ role: e.target.value })} disabled={readOnly} />
            </div>
            <TagInput ariaLabel="Pains" placeholder="Pains (Enter to add)" value={p.pains ?? []} onChange={(v) => update({ pains: v })} disabled={readOnly} />
            <TagInput ariaLabel="Goals" placeholder="Goals (Enter to add)" value={p.goals ?? []} onChange={(v) => update({ goals: v })} disabled={readOnly} />
          </>
        )} />
      <SaveBar readOnly={readOnly} pending={pending} error={error} dirty={false}
               onSave={() => save({ audience: { ...a, summary: summary.trim() || null, market: market === NONE ? null : (market as Audience["market"]), demographics: demographics.trim() || null, geography, personas: personas.filter((p) => p.name.trim()) } })} />
    </div>
  );
}

const TONES: { key: keyof Tone; low: string; high: string }[] = [
  { key: "formal", low: "Casual", high: "Formal" },
  { key: "playful", low: "Serious", high: "Playful" },
  { key: "concise", low: "Detailed", high: "Concise" },
  { key: "bold", low: "Measured", high: "Bold" },
];

export function VoiceSection({ brand, settings, readOnly }: SectionProps) {
  const { save, pending, error } = useSectionSave(brand.id);
  const v: Voice = settings.voice ?? {};
  const [tone, setTone] = useState<Tone>({ formal: 50, playful: 50, concise: 50, bold: 50, ...(v.tone ?? {}) });
  const [samples, setSamples] = useState<WritingSample[]>(v.writing_samples ?? []);
  const [preferred, setPreferred] = useState<string[]>(v.vocabulary?.preferred ?? []);
  const [avoid, setAvoid] = useState<string[]>(v.vocabulary?.avoid ?? []);
  const [rules, setRules] = useState<string[]>(v.style_rules ?? []);
  const [emoji, setEmoji] = useState(v.emoji_policy ?? "");
  const [person, setPerson] = useState<string>(v.person ?? NONE);
  const [forbidden, setForbidden] = useState<string[]>(settings.policies?.forbidden_topics ?? []);
  const [preferredTopics, setPreferredTopics] = useState<string[]>(settings.topics?.preferred_topics ?? []);
  const [claims, setClaims] = useState(settings.policies?.claims_policy ?? "");

  function onSave() {
    save({
      voice: { ...v, tone, writing_samples: samples.filter((s) => s.text.trim()), vocabulary: { preferred, avoid }, style_rules: rules, emoji_policy: emoji.trim() || null, person: person === NONE ? null : (person as Voice["person"]) },
      policies: { ...(settings.policies ?? {}), forbidden_topics: forbidden, claims_policy: claims.trim() || null },
      topics: { ...(settings.topics ?? {}), preferred_topics: preferredTopics },
    });
  }

  return (
    <div className="space-y-5">
      <fieldset className="space-y-3">
        <legend className="text-sm font-semibold">Tone</legend>
        {TONES.map((t) => (
          <div key={t.key} className="grid grid-cols-[5rem_1fr_5rem_2.5rem] items-center gap-2 text-xs">
            <span className="text-right text-muted-foreground">{t.low}</span>
            <input type="range" min={0} max={100} step={5} value={tone[t.key] ?? 50} disabled={readOnly} aria-label={`${t.low} to ${t.high}`}
                   onChange={(e) => setTone((s) => ({ ...s, [t.key]: Number(e.target.value) }))} className="w-full accent-[var(--primary)]" />
            <span className="text-muted-foreground">{t.high}</span>
            <span className="tabular-nums">{tone[t.key] ?? 50}</span>
          </div>
        ))}
      </fieldset>
      <div className="grid gap-4 sm:grid-cols-2">
        <Field label="Words to use" htmlFor="v-pref"><TagInput id="v-pref" value={preferred} onChange={setPreferred} disabled={readOnly} /></Field>
        <Field label="Words to avoid" htmlFor="v-avoid"><TagInput id="v-avoid" value={avoid} onChange={setAvoid} disabled={readOnly} /></Field>
        <Field label="Forbidden topics" htmlFor="v-forb" hint="The critic flags drafts that touch these."><TagInput id="v-forb" value={forbidden} onChange={setForbidden} disabled={readOnly} /></Field>
        <Field label="Preferred topics" htmlFor="v-ptop"><TagInput id="v-ptop" value={preferredTopics} onChange={setPreferredTopics} disabled={readOnly} /></Field>
        <Field label="Emoji policy" htmlFor="v-emoji"><Input id="v-emoji" value={emoji} onChange={(e) => setEmoji(e.target.value)} disabled={readOnly} placeholder="e.g. sparing — max one per post" /></Field>
        <Field label="Point of view" htmlFor="v-person">
          <Select value={person} onValueChange={setPerson} disabled={readOnly}>
            <SelectTrigger id="v-person" className="w-full"><SelectValue /></SelectTrigger>
            <SelectContent><SelectItem value={NONE}>Not set</SelectItem>{["we", "i", "you", "they", "brand"].map((p) => <SelectItem key={p} value={p}>{p === "i" ? "I" : p}</SelectItem>)}</SelectContent>
          </Select>
        </Field>
      </div>
      <Field label="Style rules" htmlFor="v-rules"><TagInput id="v-rules" value={rules} onChange={setRules} disabled={readOnly} placeholder="e.g. Sentence case headlines" /></Field>
      <Field label="Claims policy" htmlFor="v-claims"><Textarea id="v-claims" rows={2} value={claims} onChange={(e) => setClaims(e.target.value)} disabled={readOnly} placeholder="e.g. No health claims; cite a source for every statistic" /></Field>
      <div className="space-y-2">
        <h3 className="text-sm font-semibold">Writing samples ({samples.length})</h3>
        <RowList<WritingSample> items={samples} onChange={setSamples} readOnly={readOnly} empty="Add 2–3 posts that sound exactly like you." addLabel="Add sample" make={() => ({ text: "", note: "" })}
          render={(s, update, i) => (
            <>
              <Textarea aria-label={`Sample ${i + 1}`} rows={3} value={s.text} onChange={(e) => update({ text: e.target.value })} disabled={readOnly} />
              <Input aria-label={`Sample ${i + 1} note`} placeholder="Note (optional), e.g. best-performing LinkedIn post" value={s.note ?? ""} onChange={(e) => update({ note: e.target.value })} disabled={readOnly} />
            </>
          )} />
      </div>
      <SaveBar readOnly={readOnly} pending={pending} error={error} dirty={false} onSave={onSave} />
    </div>
  );
}

"use client";
/** Onboarding steps (doc 24 §3, doc 25 flow A). Each step persists on Continue. */
import { useState } from "react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { toast } from "sonner";
import { Check, ExternalLink, Lightbulb } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { PlatformIcon } from "@/components/shared/platform-icon";
import { FieldError, FormError, problemFieldErrors } from "@/components/shared/form-errors";
import { errorMessage, isNotAvailable } from "@/components/shared/async-states";
import { PLATFORMS } from "@/lib/platforms";
import { cn } from "@/lib/utils";
import { useSession } from "@/stores/session";
import { BrandBasicsForm } from "@/features/brand/components/brand-basics-form";
import { ImportFromWebsite } from "@/features/brand/components/import-from-website";
import { TimezoneInput, browserTimezone } from "@/features/brand/components/timezone-input";
import { useBrand, useBrands, useSaveSettings } from "@/features/brand/hooks";
import { useSocialAccounts } from "@/features/social/hooks";
import { REQUIREMENTS } from "@/features/social/requirements";
import { useStartRun } from "@/features/ai/hooks";
import { onboardingApi, slugify } from "../api";

export interface StepProps { onNext: () => void; onBack?: () => void }

export function WorkspaceStep({ onNext }: StepProps) {
  const { accessToken, user, memberships, workspaceId, setAuth, setWorkspace } = useSession();
  const current = memberships.find((m) => m.workspace.id === workspaceId) ?? memberships[0];
  const [name, setName] = useState(user?.full_name ? `${user.full_name.split(" ")[0]}'s workspace` : "");
  const [slug, setSlug] = useState("");
  const [timezone, setTimezone] = useState(browserTimezone);
  const [error, setError] = useState<unknown>(null);
  const [busy, setBusy] = useState(false);
  const errors = problemFieldErrors(error);
  const effectiveSlug = slug || slugify(name);

  if (current) {
    return (
      <div className="space-y-4">
        <p className="text-sm">You&apos;re in <span className="font-medium">{current.workspace.name}</span> <span className="font-mono text-xs text-muted-foreground">/w/{current.workspace.slug}</span> as <span className="font-medium">{current.role}</span>.</p>
        <div className="flex justify-end"><Button onClick={onNext}>Continue</Button></div>
      </div>
    );
  }

  async function submit(e: React.FormEvent) {
    e.preventDefault();
    setBusy(true); setError(null);
    try {
      const ws = await onboardingApi.createWorkspace({ name: name.trim(), slug: effectiveSlug || undefined });
      if (accessToken && user) setAuth(accessToken, user, [...memberships, { workspace: { id: ws.id, name: ws.name, slug: ws.slug }, role: ws.role ?? "owner" }]);
      setWorkspace(ws.slug);
      await onboardingApi.setWorkspaceTimezone(timezone).catch(() => undefined);
      onNext();
    } catch (err) { setError(err); } finally { setBusy(false); }
  }

  return (
    <form onSubmit={submit} className="space-y-4">
      <div className="grid gap-4 sm:grid-cols-2">
        <div className="space-y-1"><Label htmlFor="ws-name">Workspace name</Label><Input id="ws-name" value={name} onChange={(e) => setName(e.target.value)} required aria-invalid={!!errors.name} /><FieldError errors={errors} name="name" /></div>
        <div className="space-y-1">
          <Label htmlFor="ws-slug">URL</Label>
          <div className="flex items-center gap-1"><span className="text-sm text-muted-foreground">/w/</span><Input id="ws-slug" value={effectiveSlug} onChange={(e) => setSlug(slugify(e.target.value))} aria-invalid={!!errors.slug} className="font-mono" /></div>
          <FieldError errors={errors} name="slug" />
        </div>
        <div className="space-y-1"><Label htmlFor="ws-tz">Timezone</Label><TimezoneInput id="ws-tz" value={timezone} onChange={setTimezone} /></div>
      </div>
      <FormError error={Object.keys(errors).length ? null : error} />
      <div className="flex justify-end"><Button type="submit" disabled={busy || !name.trim()}>{busy ? "Creating…" : "Create workspace"}</Button></div>
    </form>
  );
}

export function BrandStep({ onNext, onBack }: StepProps) {
  const brands = useBrands();
  const { brandId, setBrand } = useSession();
  const [creating, setCreating] = useState(false);
  const existing = brands.data ?? [];
  const selected = existing.find((b) => b.id === brandId) ?? existing[0];

  if (existing.length && !creating) {
    return (
      <div className="space-y-4">
        <p className="text-sm text-muted-foreground">This workspace already has {existing.length === 1 ? "a brand" : `${existing.length} brands`}. Continue with one, or create another.</p>
        <ul className="grid gap-2 sm:grid-cols-2">
          {existing.map((b) => (
            <li key={b.id}>
              <button type="button" onClick={() => setBrand(b.id)} className={cn("w-full rounded-lg border p-3 text-left text-sm", selected?.id === b.id && "border-primary bg-primary/5")} aria-pressed={selected?.id === b.id}>
                <span className="font-medium">{b.name}</span><span className="block text-xs text-muted-foreground">{b.website ?? b.industry ?? ""}</span>
              </button>
            </li>
          ))}
        </ul>
        <div className="flex flex-wrap justify-between gap-2">
          <div className="flex gap-2">{onBack && <Button variant="ghost" onClick={onBack}>Back</Button>}<Button variant="outline" onClick={() => setCreating(true)}>Create a new brand</Button></div>
          <Button onClick={() => { if (selected) setBrand(selected.id); onNext(); }} disabled={!selected}>Continue</Button>
        </div>
      </div>
    );
  }
  return (
    <BrandBasicsForm submitLabel="Create brand & continue" onCreated={(b) => { setBrand(b.id); toast.success(`${b.name} created`); onNext(); }}
                     footer={<>{onBack && <Button type="button" variant="ghost" onClick={onBack}>Back</Button>}{existing.length > 0 && <Button type="button" variant="ghost" onClick={() => setCreating(false)}>Use an existing brand</Button>}</>} />
  );
}

export function ImportStep({ onNext, onBack, brandId }: StepProps & { brandId: string | null }) {
  const brand = useBrand(brandId);
  if (!brandId) return <p className="text-sm text-muted-foreground">Create a brand first.</p>;
  return (
    <div className="space-y-3">
      {brand.isLoading ? null : <ImportFromWebsite key={brandId} brandId={brandId} defaultUrl={brand.data?.website} onDone={() => onNext()} onSkip={onNext} />}
      {onBack && <Button variant="ghost" size="sm" onClick={onBack}>Back</Button>}
    </div>
  );
}

export function ConnectStep({ onNext, onBack, brandId }: StepProps & { brandId: string | null }) {
  const slug = useSession((s) => s.workspaceSlug);
  const accounts = useSocialAccounts(brandId);
  const connected = (accounts.data ?? []).filter((a) => a.status === "active");
  return (
    <div className="space-y-4">
      <p className="text-sm text-muted-foreground">Connecting happens on each platform&apos;s own sign-in page. Here is what each one requires — you can connect now or later from Settings › Social Accounts.</p>
      {connected.length > 0 && <p className="flex items-center gap-1 text-sm text-success"><Check className="h-4 w-4" /> {connected.length} account{connected.length === 1 ? "" : "s"} connected</p>}
      <ul className="grid gap-2 sm:grid-cols-2">
        {PLATFORMS.map((p) => {
          const r = REQUIREMENTS[p.id];
          const isConnected = connected.some((a) => a.platform === p.id);
          return (
            <li key={p.id} className="rounded-lg border p-3 text-sm">
              <p className="flex items-center gap-2 font-medium"><PlatformIcon platform={p.id} size={20} /> {p.label}{isConnected && <Check className="h-4 w-4 text-success" aria-label="Connected" />}</p>
              <p className="mt-1 text-xs text-muted-foreground">{r?.summary}</p>
              {r?.notes?.[0] && <p className="mt-1 text-xs text-warning">{r.notes[0]}</p>}
            </li>
          );
        })}
      </ul>
      <div className="flex flex-wrap justify-between gap-2">
        {onBack ? <Button variant="ghost" onClick={onBack}>Back</Button> : <span />}
        <div className="flex gap-2">
          <Button variant="outline" asChild><Link href={`/w/${slug}/settings/social`}>Open Social Accounts <ExternalLink className="h-3 w-3" /></Link></Button>
          <Button onClick={onNext}>{connected.length ? "Continue" : "Skip for now"}</Button>
        </div>
      </div>
    </div>
  );
}

const GOALS = [
  { name: "Brand awareness", metric: "reach" }, { name: "Leads & sign-ups", metric: "clicks" }, { name: "Community engagement", metric: "engagement_rate" },
  { name: "Sales", metric: "conversions" }, { name: "Thought leadership", metric: "followers" }, { name: "Hiring", metric: "applications" },
];

export function GoalsStep({ onNext, onBack, brandId }: StepProps & { brandId: string | null }) {
  const save = useSaveSettings(brandId ?? "");
  const [goals, setGoals] = useState<string[]>([]);
  const [platforms, setPlatforms] = useState<string[]>([]);
  const [cadence, setCadence] = useState<Record<string, string>>({});
  function submit() {
    if (!brandId) { onNext(); return; }
    const platformsSection: Record<string, { cadence_per_week: number }> = {};
    for (const p of platforms) if (cadence[p]) platformsSection[p] = { cadence_per_week: Math.max(0, Math.min(100, Number(cadence[p]) || 0)) };
    save.mutate({
      goals: { objectives: GOALS.filter((g) => goals.includes(g.name)).map((g) => ({ name: g.name, metric: g.metric })), priority_platforms: platforms },
      ...(Object.keys(platformsSection).length ? { platforms: platformsSection } : {}),
    }, { onSuccess: onNext, onError: (e) => { if (isNotAvailable(e)) onNext(); else toast.error(errorMessage(e)); } });
  }
  return (
    <div className="space-y-5">
      <fieldset>
        <legend className="mb-2 text-sm font-medium">What should social do for you?</legend>
        <div className="grid gap-2 sm:grid-cols-3">
          {GOALS.map((g) => {
            const on = goals.includes(g.name);
            return <button key={g.name} type="button" aria-pressed={on} onClick={() => setGoals((s) => (on ? s.filter((x) => x !== g.name) : [...s, g.name]))}
                           className={cn("rounded-lg border p-3 text-left text-sm", on ? "border-primary bg-primary/5 font-medium" : "hover:bg-accent")}>{g.name}</button>;
          })}
        </div>
      </fieldset>
      <fieldset>
        <legend className="mb-2 text-sm font-medium">Priority platforms and posts per week</legend>
        <div className="flex flex-wrap gap-2">
          {PLATFORMS.map((p) => {
            const on = platforms.includes(p.id);
            return <button key={p.id} type="button" aria-pressed={on} onClick={() => setPlatforms((s) => (on ? s.filter((x) => x !== p.id) : [...s, p.id]))}
                           className={cn("flex items-center gap-1 rounded-full border px-2 py-1 text-xs", on ? "border-primary bg-primary/10" : "hover:bg-accent")}><PlatformIcon platform={p.id} size={14} />{p.label}</button>;
          })}
        </div>
        {platforms.length > 0 && (
          <div className="mt-3 grid gap-2 sm:grid-cols-3">
            {platforms.map((p) => (
              <label key={p} className="flex items-center gap-2 text-sm"><PlatformIcon platform={p} size={18} />
                <Input type="number" min={0} max={100} className="h-8 w-20" aria-label={`Posts per week on ${p}`} value={cadence[p] ?? ""} onChange={(e) => setCadence((c) => ({ ...c, [p]: e.target.value }))} />
                <span className="text-xs text-muted-foreground">/ week</span></label>
            ))}
          </div>
        )}
      </fieldset>
      <FormError error={isNotAvailable(save.error) ? null : save.error} />
      <div className="flex flex-wrap justify-between gap-2">
        {onBack ? <Button variant="ghost" onClick={onBack}>Back</Button> : <span />}
        <div className="flex gap-2"><Button variant="ghost" onClick={onNext}>Skip</Button><Button onClick={submit} disabled={save.isPending}>{save.isPending ? "Saving…" : "Save & continue"}</Button></div>
      </div>
    </div>
  );
}

export function DoneStep({ brandId }: { brandId: string | null }) {
  const router = useRouter();
  const slug = useSession((s) => s.workspaceSlug);
  const brand = useBrand(brandId);
  const accounts = useSocialAccounts(brandId);
  const start = useStartRun();
  const items = [
    { label: "Workspace created", done: !!slug },
    { label: `Brand${brand.data ? `: ${brand.data.name}` : ""}`, done: !!brandId },
    { label: "Social account connected", done: (accounts.data ?? []).some((a) => a.status === "active") },
  ];
  function generate() {
    start.mutate({ message: "/ideas Generate a first week of post ideas for my priority platforms", mode: "task", agent: "ideation", brand_id: brandId }, {
      onSuccess: (d) => router.push(`/w/${slug}/command-center/${d.run_id}`),
      onError: (e) => toast.error(isNotAvailable(e) ? "AI isn't configured yet — add a provider in Settings › AI." : errorMessage(e)),
    });
  }
  return (
    <div className="space-y-5">
      <ul className="space-y-2 text-sm">
        {items.map((i) => <li key={i.label} className="flex items-center gap-2">{i.done ? <Check className="h-4 w-4 text-success" /> : <span className="h-4 w-4 rounded-full border" aria-hidden />}<span className={i.done ? "" : "text-muted-foreground"}>{i.label}{!i.done && " — you can finish this later"}</span></li>)}
      </ul>
      <div className="flex flex-wrap justify-end gap-2">
        <Button variant="outline" onClick={() => router.push(`/w/${slug}/dashboard`)}>Go to dashboard</Button>
        <Button onClick={generate} disabled={!brandId || start.isPending}><Lightbulb className="h-4 w-4" /> {start.isPending ? "Starting…" : "Generate my first week of ideas"}</Button>
      </div>
    </div>
  );
}

"use client";
import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Check, ChevronLeft, ChevronRight, Loader2, Sparkles } from "lucide-react";
import { toast } from "sonner";
import { Button } from "@/components/ui/button";
import { Checkbox } from "@/components/ui/checkbox";
import { Dialog, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle } from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { Textarea } from "@/components/ui/textarea";
import { PlatformIcon } from "@/components/shared/platform-icon";
import { QueryError } from "@/features/common/components/query-state";
import { useActiveBrand, useBrands, useCampaigns } from "@/features/common/hooks";
import type { ListResponse } from "@/features/common/types";
import { timezoneOptions } from "@/features/common/tz";
import { fieldErrors, toItems } from "@/features/common/utils";
import { api, qs } from "@/lib/api";
import { PLATFORMS } from "@/lib/platforms";
import { cn } from "@/lib/utils";
import { CUSTOM_SECTIONS, REPORT_KINDS, reportsApi, type CreateReportBody, type ReportKind } from "../api";

const STEPS = ["Type", "Scope", "Recipients", "Schedule"];
const iso = (d: Date) => d.toISOString().slice(0, 10);

/** Generate report wizard (doc 24 §18): type → scope → recipients → schedule, with cost/freshness note. External delivery is confirmed here. */
export function GenerateReportWizard({ open, onOpenChange, initialKind, onCreated }: { open: boolean; onOpenChange: (o: boolean) => void; initialKind?: ReportKind; onCreated: (id: string | null) => void }) {
  const qc = useQueryClient();
  const { brandId, timezone } = useActiveBrand();
  const brands = toItems(useBrands().data);
  const [step, setStep] = useState(0);
  const [kind, setKind] = useState<ReportKind>(initialKind ?? "weekly_performance");
  const [brand, setBrand] = useState<string>(brandId ?? "");
  const [days, setDays] = useState("7");
  const [from, setFrom] = useState(() => iso(new Date(new Date().getTime() - 7 * 86_400_000)));
  const [to, setTo] = useState(() => iso(new Date()));
  const [platforms, setPlatforms] = useState<string[]>([]);
  const [campaign, setCampaign] = useState("");
  const [competitors, setCompetitors] = useState<string[]>([]);
  const [sections, setSections] = useState<string[]>(["summary", "kpis", "top_posts", "recommendations"]);
  const [brief, setBrief] = useState("");
  const [title, setTitle] = useState("");
  const [emails, setEmails] = useState("");
  const [slack, setSlack] = useState("");
  const [format, setFormat] = useState<"pdf" | "markdown" | "link">("pdf");
  const [recurring, setRecurring] = useState(false);
  const [tz, setTz] = useState(timezone);
  const campaigns = toItems(useCampaigns(brand || null).data);
  const comps = useQuery({ queryKey: ["competitors", "picker", brand], queryFn: () => api.get<ListResponse<{ id: string; name: string }>>(`/competitors${qs({ brand_id: brand || undefined })}`), enabled: open && kind === "competitor", retry: false });

  const applyDays = (d: string) => { setDays(d); if (d !== "custom") { const n = Number(d); setFrom(iso(new Date(new Date().getTime() - n * 86_400_000))); setTo(iso(new Date())); } };
  const recipients = [
    ...emails.split(/[,\s]+/).map((e) => e.trim()).filter(Boolean).map((value) => ({ type: "email", value })),
    ...(slack.trim() ? [{ type: "slack", value: slack.trim() }] : []),
  ];
  const create = useMutation({
    mutationFn: () => {
      const body: CreateReportBody = {
        kind, brand_id: brand || null, title: title.trim() || undefined, period_start: from, period_end: to, platforms: platforms.length ? platforms : undefined,
        campaign_id: kind === "campaign" && campaign ? campaign : undefined, competitor_ids: kind === "competitor" && competitors.length ? competitors : undefined,
        sections: kind === "custom" ? sections : undefined, brief: brief.trim() || undefined, recipients, format,
        schedule: recurring ? { rrule: "FREQ=WEEKLY;BYDAY=MO;BYHOUR=8;BYMINUTE=0", timezone: tz } : null,
      };
      return reportsApi.create(body);
    },
    onSuccess: (r) => {
      toast.success(recurring ? "Report scheduled weekly — the first one is generating" : "Report is generating");
      void qc.invalidateQueries({ queryKey: ["reports"] });
      onOpenChange(false);
      const id = ("id" in r && typeof r.id === "string" ? r.id : null) ?? ("report_id" in r && typeof r.report_id === "string" ? r.report_id : null);
      onCreated(id);
    },
  });
  const errs = fieldErrors(create.error);
  const invalidEmails = emails.split(/[,\s]+/).filter((e) => e.trim() && !/^[^@\s]+@[^@\s]+\.[^@\s]+$/.test(e.trim()));
  const canNext = step === 0 ? true : step === 1 ? !!brand && !!from && !!to && from <= to && (kind !== "custom" || sections.length > 0) : step === 2 ? invalidEmails.length === 0 : true;

  return (
    <Dialog open={open} onOpenChange={(o) => { if (!o) setStep(0); onOpenChange(o); }}>
      <DialogContent className="max-h-[90vh] overflow-y-auto sm:max-w-xl">
        <DialogHeader>
          <DialogTitle className="flex items-center gap-2"><Sparkles className="h-4 w-4 text-ai" /> Generate report</DialogTitle>
          <DialogDescription>Composed by the report agent from stored data — every AI section cites its data or sources.</DialogDescription>
        </DialogHeader>
        <ol className="flex gap-2 text-xs" aria-label="Steps">
          {STEPS.map((s, i) => <li key={s} className={cn("flex items-center gap-1", i === step ? "font-medium text-foreground" : "text-muted-foreground")}><span className={cn("flex h-5 w-5 items-center justify-center rounded-full border", i < step && "bg-primary text-primary-foreground", i === step && "border-primary")}>{i < step ? <Check className="h-3 w-3" /> : i + 1}</span>{s}</li>)}
        </ol>

        {step === 0 && (
          <div className="grid gap-2 sm:grid-cols-2" role="radiogroup" aria-label="Report type">
            {REPORT_KINDS.map((k) => (
              <button key={k.id} type="button" role="radio" aria-checked={kind === k.id} onClick={() => setKind(k.id)} className={cn("rounded-lg border p-3 text-left hover:bg-accent", kind === k.id && "border-primary bg-primary/5")}>
                <p className="text-sm font-medium">{k.label}</p><p className="mt-0.5 text-xs text-muted-foreground">{k.description}</p>
              </button>
            ))}
          </div>
        )}
        {step === 1 && (
          <div className="space-y-3">
            <div className="grid gap-3 sm:grid-cols-2">
              <div className="space-y-1.5"><Label>Brand</Label><Select value={brand} onValueChange={setBrand}><SelectTrigger className="w-full"><SelectValue placeholder="Choose brand" /></SelectTrigger><SelectContent>{brands.map((b) => <SelectItem key={b.id} value={b.id}>{b.name}</SelectItem>)}</SelectContent></Select></div>
              <div className="space-y-1.5"><Label>Period</Label><Select value={days} onValueChange={applyDays}><SelectTrigger className="w-full"><SelectValue /></SelectTrigger><SelectContent><SelectItem value="7">Last 7 days</SelectItem><SelectItem value="30">Last 30 days</SelectItem><SelectItem value="90">Last 90 days</SelectItem><SelectItem value="custom">Custom</SelectItem></SelectContent></Select></div>
            </div>
            {days === "custom" && <div className="grid grid-cols-2 gap-3"><div className="space-y-1.5"><Label htmlFor="r-from">From</Label><Input id="r-from" type="date" value={from} onChange={(e) => setFrom(e.target.value)} /></div><div className="space-y-1.5"><Label htmlFor="r-to">To</Label><Input id="r-to" type="date" value={to} onChange={(e) => setTo(e.target.value)} /></div></div>}
            <div className="space-y-1.5"><Label>Platforms <span className="text-muted-foreground">(all if none)</span></Label>
              <div className="flex flex-wrap gap-1.5">{PLATFORMS.map((p) => { const on = platforms.includes(p.id); return <button key={p.id} type="button" aria-pressed={on} onClick={() => setPlatforms((s) => (on ? s.filter((x) => x !== p.id) : [...s, p.id]))} className={cn("flex items-center gap-1 rounded-full border px-2 py-1 text-xs", on && "border-primary bg-primary/5")}><PlatformIcon platform={p.id} size={14} />{p.label}</button>; })}</div></div>
            {kind === "campaign" && <div className="space-y-1.5"><Label>Campaign</Label><Select value={campaign} onValueChange={setCampaign}><SelectTrigger className="w-full"><SelectValue placeholder={campaigns.length ? "Choose campaign" : "No campaigns"} /></SelectTrigger><SelectContent>{campaigns.map((c) => <SelectItem key={c.id} value={c.id}>{c.name}</SelectItem>)}</SelectContent></Select></div>}
            {kind === "competitor" && (
              <div className="space-y-1.5"><Label>Competitors</Label>
                {comps.error ? <QueryError error={comps.error} notAvailableText="Competitors aren't available yet." /> : toItems(comps.data).length === 0 ? <p className="text-xs text-muted-foreground">No competitors tracked for this brand.</p> : (
                  <div className="flex flex-wrap gap-2">{toItems(comps.data).map((c) => <label key={c.id} className="flex items-center gap-1.5 text-sm"><Checkbox checked={competitors.includes(c.id)} onCheckedChange={(v) => setCompetitors((s) => (v === true ? [...s, c.id] : s.filter((x) => x !== c.id)))} />{c.name}</label>)}</div>
                )}</div>
            )}
            {kind === "custom" && (
              <div className="space-y-1.5"><Label>Sections</Label>
                <div className="grid grid-cols-2 gap-1.5">{CUSTOM_SECTIONS.map((s) => <label key={s} className="flex items-center gap-1.5 text-sm"><Checkbox checked={sections.includes(s)} onCheckedChange={(v) => setSections((cur) => (v === true ? [...cur, s] : cur.filter((x) => x !== s)))} />{s.replace(/_/g, " ")}</label>)}</div></div>
            )}
            <div className="space-y-1.5"><Label htmlFor="r-brief">Brief <span className="text-muted-foreground">(optional)</span></Label><Textarea id="r-brief" rows={2} value={brief} onChange={(e) => setBrief(e.target.value)} placeholder="Focus on LinkedIn carousels vs single images" /></div>
            <div className="space-y-1.5"><Label htmlFor="r-title">Title <span className="text-muted-foreground">(optional)</span></Label><Input id="r-title" value={title} onChange={(e) => setTitle(e.target.value)} /></div>
            {errs.period_start && <p className="text-xs text-destructive">{errs.period_start}</p>}
          </div>
        )}
        {step === 2 && (
          <div className="space-y-3">
            <div className="space-y-1.5"><Label htmlFor="r-emails">Email recipients</Label><Input id="r-emails" value={emails} onChange={(e) => setEmails(e.target.value)} placeholder="sam@acme.com, dana@acme.com" aria-invalid={invalidEmails.length > 0} />
              {invalidEmails.length > 0 && <p className="text-xs text-destructive">Invalid: {invalidEmails.join(", ")}</p>}{errs.recipients && <p className="text-xs text-destructive">{errs.recipients}</p>}</div>
            <div className="space-y-1.5"><Label htmlFor="r-slack">Slack channel <span className="text-muted-foreground">(if Slack is connected)</span></Label><Input id="r-slack" value={slack} onChange={(e) => setSlack(e.target.value)} placeholder="#marketing" /></div>
            <div className="space-y-1.5"><Label>Format</Label><Select value={format} onValueChange={(v) => setFormat(v as typeof format)}><SelectTrigger className="w-40"><SelectValue /></SelectTrigger><SelectContent><SelectItem value="pdf">PDF</SelectItem><SelectItem value="markdown">Markdown</SelectItem><SelectItem value="link">Link only</SelectItem></SelectContent></Select></div>
            <p className="text-xs text-muted-foreground">Leave empty to only keep the report in Botwok.</p>
          </div>
        )}
        {step === 3 && (
          <div className="space-y-3">
            <div className="flex gap-2" role="radiogroup" aria-label="When">
              {[{ v: false, l: "Once, now" }, { v: true, l: "Every Monday 08:00" }].map((o) => <button key={String(o.v)} type="button" role="radio" aria-checked={recurring === o.v} onClick={() => setRecurring(o.v)} className={cn("rounded-md border px-3 py-1.5 text-sm", recurring === o.v && "border-primary bg-primary/5")}>{o.l}</button>)}
            </div>
            {recurring && <div className="space-y-1.5"><Label>Timezone</Label><Select value={tz} onValueChange={setTz}><SelectTrigger className="w-56"><SelectValue /></SelectTrigger><SelectContent>{timezoneOptions([timezone, tz]).map((z) => <SelectItem key={z} value={z}>{z}</SelectItem>)}</SelectContent></Select></div>}
            <div className="rounded-md bg-muted p-3 text-xs">
              <p className="font-medium">Summary</p>
              <p>{REPORT_KINDS.find((k) => k.id === kind)?.label} · {brands.find((b) => b.id === brand)?.name ?? "—"} · {from} → {to}{platforms.length ? ` · ${platforms.join(", ")}` : ""}</p>
              <p>{recipients.length ? `Will be sent to: ${recipients.map((r) => r.value).join(", ")} (${format})` : "Not sent externally"}</p>
              <p className="mt-1 text-muted-foreground">report agent · balanced tier · est. ~$0.03–0.10 per report. Uses stored analytics/competitor data — sync first for the freshest numbers.</p>
            </div>
          </div>
        )}
        {create.error && <QueryError error={create.error} title="Report was not created" notAvailableText="Report generation isn't available on this backend yet." />}
        <DialogFooter>
          {step > 0 && <Button variant="ghost" onClick={() => setStep((s) => s - 1)}><ChevronLeft /> Back</Button>}
          <Button variant="outline" onClick={() => onOpenChange(false)}>Cancel</Button>
          {step < STEPS.length - 1
            ? <Button onClick={() => setStep((s) => s + 1)} disabled={!canNext}>Next <ChevronRight /></Button>
            : <Button onClick={() => create.mutate()} disabled={create.isPending || !brand}>{create.isPending ? <Loader2 className="animate-spin" /> : <Sparkles />} {recurring ? "Schedule" : "Generate"}{recipients.length ? " & send" : ""}</Button>}
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}

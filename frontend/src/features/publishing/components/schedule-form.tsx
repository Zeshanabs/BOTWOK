"use client";
import { useState } from "react";
import Link from "next/link";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { CalendarClock, Clock, Loader2, Lock, Send, Sparkles } from "lucide-react";
import { toast } from "sonner";
import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { StatusChip } from "@/components/shared/status-chip";
import { PlatformIcon } from "@/components/shared/platform-icon";
import { ConfirmDialog } from "@/features/common/components/confirm-dialog";
import { usePermissions, useSocialAccounts, useWorkspacePath } from "@/features/common/hooks";
import { fromLocalInput, timezoneOptions, toLocalInput, tzParts } from "@/features/common/tz";
import { errorMessage, fieldErrors, fmtDateTime, isNotAvailable, toItems, validationIssues } from "@/features/common/utils";
import { platformMeta } from "@/lib/platforms";
import { schedulingApi, publishingApi, type BestTimesResult, type ScheduledPost } from "../api";

export interface SchedulableVariant { id: string; platform: string; format?: string; status: string; social_account_id?: string | null; scheduled_posts?: { id: string; status: string; scheduled_at: string }[] }

/**
 * Schedule a variant (flow L): account for the variant's platform, date/time + timezone, best-time chips with their basis,
 * Schedule / Publish now. 422 errors are shown per field. Never enabled for unapproved content.
 */
export function ScheduleForm({ variant, contentApproved, brandId, defaultTz, defaultAt, onDone }: {
  variant: SchedulableVariant; contentApproved: boolean; brandId: string | null; defaultTz: string; defaultAt?: string; onDone?: (post: ScheduledPost | null) => void;
}) {
  const qc = useQueryClient();
  const ws = useWorkspacePath();
  const { canSchedule } = usePermissions();
  const accountsQ = useSocialAccounts(brandId);
  const accounts = toItems(accountsQ.data).filter((a) => a.platform === variant.platform);
  const [accountId, setAccountId] = useState<string>(variant.social_account_id ?? "");
  const effectiveAccount = accountId || (accounts.length === 1 ? accounts[0].id : "");
  const account = accounts.find((a) => a.id === effectiveAccount);
  const [tz, setTz] = useState(defaultTz);
  const [when, setWhen] = useState(() => (defaultAt ? toLocalInput(defaultAt, defaultTz) : ""));
  const [bestResult, setBestResult] = useState<BestTimesResult | null>(null);
  const slots = bestResult?.slots ?? null;
  const [confirmNow, setConfirmNow] = useState(false);
  const approved = contentApproved || variant.status === "approved";

  const invalidate = () => {
    void qc.invalidateQueries({ queryKey: ["calendar"] });
    void qc.invalidateQueries({ queryKey: ["publishing"] });
    void qc.invalidateQueries({ queryKey: ["content"] });
  };
  const schedule = useMutation({
    mutationFn: () => {
      const at = fromLocalInput(when, tz);
      if (!at) throw new Error("Pick a date and time");
      return schedulingApi.create({ content_variant_id: variant.id, social_account_id: effectiveAccount, scheduled_at: at, timezone: tz });
    },
    onSuccess: (post) => {
      const warnings = validationIssues(post.validation).warnings;
      toast.success(`Scheduled for ${fmtDateTime(post.scheduled_at, tz)}`, { description: warnings.map((w) => w.message).join(" · ") || undefined });
      invalidate();
      onDone?.(post);
    },
  });
  const publishNow = useMutation({
    mutationFn: () => publishingApi.publishNow({ content_variant_id: variant.id, social_account_id: effectiveAccount }),
    onSuccess: () => { toast.success("Queued to publish now"); setConfirmNow(false); invalidate(); onDone?.(null); },
    onError: (e) => { setConfirmNow(false); toast.error(errorMessage(e)); },
  });
  const best = useMutation({
    mutationFn: () => {
      const now = new Date();
      return schedulingApi.bestTimes({ brand_id: brandId, platform: variant.platform, social_account_id: effectiveAccount || undefined, from: now.toISOString(), to: new Date(now.getTime() + 14 * 86_400_000).toISOString(), count: 5 });
    },
    onSuccess: (r) => setBestResult({ ...r, slots: r.slots ?? [] }),
    onError: (e) => toast.error(isNotAvailable(e) ? "Best-time suggestions are not available yet" : errorMessage(e)),
  });
  const errs = fieldErrors(schedule.error);
  const generalErrs = Object.entries(errs).filter(([k]) => !["scheduled_at", "social_account_id", "timezone"].includes(k));
  const disabled = !approved || !canSchedule;
  const nowMin = toLocalInput(new Date(), tz);

  return (
    <div className="space-y-4">
      {!approved && (
        <Alert>
          <Lock />
          <AlertTitle>Scheduling unlocks after approval</AlertTitle>
          <AlertDescription>This {platformMeta(variant.platform).label} version is “{variant.status.replace(/_/g, " ")}”. Nothing is scheduled without an approved version and an explicit action.</AlertDescription>
        </Alert>
      )}
      {!canSchedule && approved && <p className="text-sm text-muted-foreground">Viewers can’t schedule. Ask an editor or approver.</p>}
      {(variant.scheduled_posts ?? []).length > 0 && (
        <div className="space-y-1">
          <p className="text-xs font-medium text-muted-foreground">Already planned</p>
          {(variant.scheduled_posts ?? []).map((p) => (
            <div key={p.id} className="flex items-center gap-2 text-sm"><CalendarClock className="h-4 w-4 text-muted-foreground" />{fmtDateTime(p.scheduled_at, tz)}<StatusChip status={p.status} /></div>
          ))}
        </div>
      )}
      <div className="space-y-1.5">
        <Label htmlFor={`acct-${variant.id}`}>Account</Label>
        {accountsQ.isLoading ? <p className="text-sm text-muted-foreground">Loading accounts…</p> : accounts.length === 0 ? (
          <p className="text-sm text-muted-foreground">No connected {platformMeta(variant.platform).label} account. <Link className="text-primary hover:underline" href={ws("settings/social-accounts")}>Connect one</Link></p>
        ) : (
          <Select value={effectiveAccount} onValueChange={setAccountId} disabled={disabled}>
            <SelectTrigger id={`acct-${variant.id}`} className="w-full" aria-invalid={!!errs.social_account_id}><SelectValue placeholder="Choose account" /></SelectTrigger>
            <SelectContent>
              {accounts.map((a) => (
                <SelectItem key={a.id} value={a.id} disabled={a.status !== "active"}>
                  <PlatformIcon platform={a.platform} size={16} /> {a.display_name}{a.handle ? ` (@${a.handle.replace(/^@/, "")})` : ""}{a.status !== "active" ? ` · ${a.status}` : ""}
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
        )}
        {account && account.status !== "active" && <p className="text-xs text-destructive">Account is {account.status}. <Link className="underline" href={ws("settings/social-accounts")}>Reconnect</Link></p>}
        {errs.social_account_id && <p className="text-xs text-destructive">{errs.social_account_id}</p>}
      </div>
      <div className="grid gap-3 sm:grid-cols-2">
        <div className="space-y-1.5">
          <Label htmlFor={`when-${variant.id}`}>Date & time</Label>
          <Input id={`when-${variant.id}`} type="datetime-local" value={when} min={nowMin} onChange={(e) => setWhen(e.target.value)} disabled={disabled} aria-invalid={!!errs.scheduled_at} />
          {errs.scheduled_at && <p className="text-xs text-destructive">{errs.scheduled_at}</p>}
        </div>
        <div className="space-y-1.5">
          <Label>Timezone</Label>
          <Select value={tz} onValueChange={(z) => { const iso = fromLocalInput(when, tz); setTz(z); if (iso) setWhen(toLocalInput(iso, z)); }} disabled={disabled}>
            <SelectTrigger className="w-full"><SelectValue /></SelectTrigger>
            <SelectContent>{timezoneOptions([defaultTz, tz]).map((z) => <SelectItem key={z} value={z}>{z}</SelectItem>)}</SelectContent>
          </Select>
          {errs.timezone && <p className="text-xs text-destructive">{errs.timezone}</p>}
        </div>
      </div>
      <div className="space-y-2">
        <Button type="button" size="sm" variant="outline" onClick={() => best.mutate()} disabled={disabled || best.isPending}>
          {best.isPending ? <Loader2 className="animate-spin" /> : <Sparkles className="text-ai" />} Best times
        </Button>
        {slots && slots.length === 0 && <p className="text-xs text-muted-foreground">No free slots found in the next 14 days.</p>}
        {slots && slots.length > 0 && (
          <div className="flex flex-wrap gap-1.5">
            {slots.map((s) => {
              const p = tzParts(new Date(s.at), tz);
              const day = new Intl.DateTimeFormat("en-US", { timeZone: tz, weekday: "short" }).format(new Date(s.at));
              return (
                <button key={s.at} type="button" onClick={() => setWhen(toLocalInput(s.at, tz))}
                        className="rounded-full border px-2.5 py-1 text-xs hover:bg-accent" title={s.basis ?? undefined}>
                  <Clock className="mr-1 inline h-3 w-3" />{day} {String(p.hour).padStart(2, "0")}:{String(p.minute).padStart(2, "0")}
                  {s.lift != null && ` · ${s.lift > 0 ? "+" : ""}${Math.round(s.lift * (Math.abs(s.lift) <= 1 ? 100 : 1))}%`}
                  {s.n != null ? ` · n=${s.n}` : s.basis ? ` · ${s.basis}` : ""}
                </button>
              );
            })}
          </div>
        )}
        {slots && slots.length > 0 && <p className="text-[11px] text-muted-foreground">Basis: {bestResult?.evidence ?? (Array.from(new Set(slots.map((s) => s.basis).filter(Boolean))).join(" · ") || "engagement by weekday × hour")}{bestResult?.min_gap_minutes ? ` · min gap ${bestResult.min_gap_minutes} min` : ""}</p>}
        {bestResult?.token_expires_at && <p className="text-[11px] text-warning">Token expires {fmtDateTime(bestResult.token_expires_at, tz)} — slots after that are excluded.</p>}
      </div>
      {generalErrs.length > 0 && (
        <Alert variant="destructive">
          <AlertTitle>Platform validation failed</AlertTitle>
          <AlertDescription><ul className="list-disc pl-4">{generalErrs.map(([k, v]) => <li key={k}><span className="font-mono text-xs">{k === "_" ? "" : `${k}: `}</span>{v}</li>)}</ul></AlertDescription>
        </Alert>
      )}
      {schedule.error && generalErrs.length === 0 && Object.keys(errs).length === 0 && <p className="text-sm text-destructive">{errorMessage(schedule.error)}</p>}
      <div className="flex flex-wrap gap-2">
        <Button onClick={() => schedule.mutate()} disabled={disabled || !effectiveAccount || !when || schedule.isPending || account?.status !== "active"}>
          {schedule.isPending ? <Loader2 className="animate-spin" /> : <CalendarClock />} Schedule
        </Button>
        <Button variant="outline" onClick={() => setConfirmNow(true)} disabled={disabled || !effectiveAccount || account?.status !== "active"}><Send /> Publish now</Button>
      </div>
      <ConfirmDialog open={confirmNow} onOpenChange={setConfirmNow} title={`Publish to ${platformMeta(variant.platform).label} now?`} confirmLabel="Publish now" pending={publishNow.isPending}
                     onConfirm={() => publishNow.mutate()}
                     description={<p>This posts the approved {platformMeta(variant.platform).label} version to <strong>{account?.display_name ?? "the selected account"}</strong> immediately. It goes through the same validation and publishing queue as scheduled posts.</p>} />
    </div>
  );
}

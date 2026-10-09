"use client";
import { useState } from "react";
import { AlertTriangle, CheckCircle2, Loader2, XCircle } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Dialog, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle } from "@/components/ui/dialog";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { Label } from "@/components/ui/label";
import { Textarea } from "@/components/ui/textarea";
import { errorMessage, fieldErrors, validationIssues } from "@/features/common/utils";
import { platformMeta } from "@/lib/platforms";
import { isUnsupported, policyFlags, type ContentItem } from "../api";
import { budgetFor } from "../platform-rules";
import { normalizeScore } from "./panels/critic-panel";

export interface PrecheckRow { ok: boolean; warn?: boolean; label: string }

export function approvalPrecheck(content: ContentItem, liveText: (variantId: string) => { text: string; segments?: string[]; metadata?: Record<string, unknown>; hashtags?: string[] }): { rows: PrecheckRow[]; blocking: boolean } {
  const rows: PrecheckRow[] = [];
  let blocking = false;
  const overall = normalizeScore(content.critique?.overall ?? null);
  rows.push(overall == null ? { ok: true, warn: true, label: "Critic has not scored this content yet" } : { ok: overall >= 60, warn: overall < 70, label: `Critic quality ${Math.round(overall)}/100` });
  for (const v of content.variants ?? []) {
    const { errors } = validationIssues(v.validation);
    const live = liveText(v.id);
    const over = budgetFor(v.platform, live.text, live).filter((l) => l.over);
    if (errors.length || over.length) {
      blocking = true;
      rows.push({ ok: false, label: `${platformMeta(v.platform).label}: ${[...errors.map((e) => e.message), ...over.map((o) => `${o.label} ${o.used}/${o.limit}`)].join(" · ")}` });
    }
  }
  const claims = [...(content.factcheck?.claims ?? []), ...(content.variants ?? []).flatMap((v) => v.factcheck?.claims ?? [])];
  const unsupported = claims.filter(isUnsupported);
  if (claims.length) rows.push({ ok: unsupported.length === 0, warn: unsupported.length > 0, label: unsupported.length ? `${unsupported.length} claim(s) unverified or contradicted` : `${claims.length} claims supported` });
  const assets = [...(content.assets ?? []), ...(content.variants ?? []).flatMap((v) => v.assets ?? [])].filter((a) => (a.media?.kind ?? "image") === "image");
  const missingAlt = assets.filter((a) => !(a.alt_text ?? a.media?.alt_text ?? "").trim()).length;
  if (assets.length) rows.push({ ok: missingAlt === 0, warn: missingAlt > 0, label: missingAlt ? `${missingAlt} image(s) missing alt text` : "All images have alt text" });
  const flags = policyFlags(content.critique);
  if (flags.length) rows.push({ ok: false, warn: true, label: `${flags.length} policy flag(s) — approver must acknowledge: ${flags.map((f) => f.message).join("; ")}` });
  return { rows, blocking };
}

/** Request approval with pre-check (flow K step 1). Constraint violations block the request. */
export function RequestApprovalDialog({ open, onOpenChange, content, precheck, onSubmit, pending, error }: {
  open: boolean; onOpenChange: (o: boolean) => void; content: ContentItem; precheck: { rows: PrecheckRow[]; blocking: boolean };
  onSubmit: (b: { comment?: string; expires_in_hours?: number }) => void; pending?: boolean; error?: unknown;
}) {
  const [note, setNote] = useState("");
  const [expires, setExpires] = useState("72");
  const errs = fieldErrors(error);
  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent>
        <DialogHeader>
          <DialogTitle>Request approval</DialogTitle>
          <DialogDescription>“{content.title}” and its {content.variants?.length ?? 0} platform version(s) go to the approvers’ inbox. The approval covers these exact versions.</DialogDescription>
        </DialogHeader>
        <ul className="space-y-1.5 text-sm" aria-label="Pre-check">
          {precheck.rows.map((r, i) => (
            <li key={i} className="flex items-start gap-2">
              {!r.ok ? <XCircle className="mt-0.5 h-4 w-4 shrink-0 text-red-600" /> : r.warn ? <AlertTriangle className="mt-0.5 h-4 w-4 shrink-0 text-amber-600" /> : <CheckCircle2 className="mt-0.5 h-4 w-4 shrink-0 text-emerald-600" />}
              <span>{r.label}</span>
            </li>
          ))}
        </ul>
        {precheck.blocking && <p className="text-sm text-red-600">Fix the platform limit/validation errors before requesting approval.</p>}
        <div className="space-y-1.5"><Label htmlFor="ra-note">Note for approvers</Label><Textarea id="ra-note" value={note} onChange={(e) => setNote(e.target.value)} rows={3} placeholder="Ready for Tuesday’s launch" />{errs.comment && <p className="text-xs text-red-600">{errs.comment}</p>}</div>
        <div className="space-y-1.5"><Label>Request expires after</Label>
          <Select value={expires} onValueChange={setExpires}><SelectTrigger className="w-48"><SelectValue /></SelectTrigger>
            <SelectContent><SelectItem value="24">24 hours</SelectItem><SelectItem value="72">3 days</SelectItem><SelectItem value="168">7 days</SelectItem><SelectItem value="336">14 days</SelectItem></SelectContent></Select>
          {errs.expires_in_hours && <p className="text-xs text-red-600">{errs.expires_in_hours}</p>}</div>
        {!!error && !Object.keys(errs).length && <p className="text-sm text-red-600">{errorMessage(error)}</p>}
        {!!errs._ && <p className="text-sm text-red-600">{errs._}</p>}
        <DialogFooter>
          <Button variant="outline" onClick={() => onOpenChange(false)}>Cancel</Button>
          <Button disabled={precheck.blocking || pending} onClick={() => onSubmit({ comment: note.trim() || undefined, expires_in_hours: Number(expires) })}>
            {pending && <Loader2 className="animate-spin" />} Request approval
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}

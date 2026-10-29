"use client";
/** Right-hand run panels: Actions (approval gate), Generated content, Sources, Reasoning summary (doc 24 §6). */
import { useState } from "react";
import Link from "next/link";
import { toast } from "sonner";
import { Check, ExternalLink, FileText, PauseCircle, Send, X } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Textarea } from "@/components/ui/textarea";
import { StatusChip } from "@/components/shared/status-chip";
import { PlatformIcon } from "@/components/shared/platform-icon";
import { errorMessage } from "@/components/shared/async-states";
import { domainOf, fmtDate, truncate } from "@/lib/formatters";
import { useCan } from "@/lib/permissions";
import { useSession } from "@/stores/session";
import { CredibilityBadge, Favicon, InjectionBadge, RelevanceBadge } from "@/features/research/components/source-badges";
import { useApprovalDecision, useRequestContentApproval } from "../hooks";
import type { RunAction, RunDeliverable, RunSource } from "../types";

function Empty({ children }: { children: React.ReactNode }) {
  return <p className="rounded-lg border border-dashed p-4 text-center text-sm text-muted-foreground">{children}</p>;
}

export function ActionsPanel({ actions }: { actions: RunAction[] }) {
  const can = useCan();
  const { approve, reject } = useApprovalDecision();
  const [rejecting, setRejecting] = useState<string | null>(null);
  const [reason, setReason] = useState("");
  if (!actions.length) return <Empty>No side effects proposed. Anything that posts, schedules or changes settings waits here for approval.</Empty>;
  return (
    <ul className="space-y-3">
      {actions.map((a) => {
        const pending = a.status === "pending";
        return (
          <li key={a.approval_id} className={pending ? "rounded-lg border border-warning/40 bg-warning/[0.08]/60 p-3" : "rounded-lg border p-3"}>
            <div className="flex items-start gap-2">
              {pending && <PauseCircle className="mt-0.5 h-4 w-4 shrink-0 text-warning" aria-hidden />}
              <div className="min-w-0 flex-1">
                <p className="text-sm font-medium">{a.description}</p>
                <p className="mt-0.5 text-xs text-muted-foreground">
                  {a.tool && <span className="font-mono">{a.tool}</span>}{a.task_key && <> · step {a.task_key}</>}
                </p>
                {a.scope && Object.keys(a.scope).length > 0 && (
                  <dl className="mt-1 grid grid-cols-[auto_1fr] gap-x-2 text-xs">
                    {Object.entries(a.scope).slice(0, 6).map(([k, v]) => (
                      <div key={k} className="contents"><dt className="text-muted-foreground">{k.replace(/_/g, " ")}</dt><dd className="truncate">{Array.isArray(v) ? v.join(", ") : String(v)}</dd></div>
                    ))}
                  </dl>
                )}
              </div>
              <StatusChip status={a.status} />
            </div>
            {pending && (can.approve ? (
              rejecting === a.approval_id ? (
                <div className="mt-2 space-y-2">
                  <Textarea value={reason} onChange={(e) => setReason(e.target.value)} placeholder="Reason (required) — the agent sees this" rows={2} aria-label="Rejection reason" />
                  <div className="flex gap-2">
                    <Button size="sm" variant="destructive" disabled={!reason.trim() || reject.isPending}
                            onClick={() => reject.mutate({ id: a.approval_id, comment: reason.trim() }, {
                              onSuccess: () => { toast.success("Rejected"); setRejecting(null); setReason(""); },
                              onError: (e) => toast.error(errorMessage(e)),
                            })}>Reject</Button>
                    <Button size="sm" variant="ghost" onClick={() => setRejecting(null)}>Cancel</Button>
                  </div>
                </div>
              ) : (
                <div className="mt-2 flex gap-2">
                  <Button size="sm" disabled={approve.isPending}
                          onClick={() => approve.mutate({ id: a.approval_id }, { onSuccess: () => toast.success("Approved — the run will resume"), onError: (e) => toast.error(errorMessage(e)) })}>
                    <Check className="h-3 w-3" /> Approve
                  </Button>
                  <Button size="sm" variant="outline" onClick={() => { setRejecting(a.approval_id); setReason(""); }}><X className="h-3 w-3" /> Reject</Button>
                </div>
              )
            ) : <p className="mt-2 text-xs text-muted-foreground">Needs approver (owner, admin or approver role).</p>)}
          </li>
        );
      })}
    </ul>
  );
}

export function OutputPanel({ deliverables }: { deliverables: RunDeliverable[] }) {
  const slug = useSession((s) => s.workspaceSlug);
  const can = useCan();
  const request = useRequestContentApproval();
  if (!deliverables.length) return <Empty>Generated content will appear here.</Empty>;
  return (
    <ul className="space-y-3">
      {deliverables.map((d, i) => {
        const contentId = d.content_id ?? (d.type === "content" || d.kind === "content" || !d.type ? d.id : undefined);
        return (
          <li key={d.id ?? i} className="rounded-lg border p-3">
            <div className="flex items-start gap-2">
              {d.platform ? <PlatformIcon platform={d.platform} size={18} /> : <FileText className="h-4 w-4 text-muted-foreground" aria-hidden />}
              <div className="min-w-0 flex-1">
                <p className="text-sm font-medium"><span className="mr-1 text-ai" aria-label="AI generated">✦</span>{d.title || truncate(d.summary || d.text, 80) || "Untitled"}</p>
                {(d.summary || d.text) && d.title && <p className="mt-0.5 line-clamp-3 text-xs text-muted-foreground">{d.summary || d.text}</p>}
                <div className="mt-1 flex flex-wrap items-center gap-2 text-xs text-muted-foreground">
                  {d.status && <StatusChip status={d.status} />}
                  {d.critic_score != null && <span>critic {Math.round(d.critic_score)}</span>}
                  {d.type && <span>{d.type.replace(/_/g, " ")}</span>}
                </div>
              </div>
            </div>
            {contentId && (
              <div className="mt-2 flex flex-wrap gap-2">
                <Button asChild size="sm" variant="outline"><Link href={`/w/${slug}/studio/${contentId}`}><ExternalLink className="h-3 w-3" /> Open in Studio</Link></Button>
                {can.create && (
                  <Button size="sm" variant="ghost" disabled={request.isPending}
                          onClick={() => request.mutate(contentId, { onSuccess: () => toast.success("Approval requested"), onError: (e) => toast.error(errorMessage(e)) })}>
                    <Send className="h-3 w-3" /> Request approval
                  </Button>
                )}
              </div>
            )}
            {!contentId && d.url && <a href={d.url} className="mt-2 inline-flex items-center gap-1 text-xs text-primary hover:underline">Open <ExternalLink className="h-3 w-3" /></a>}
          </li>
        );
      })}
    </ul>
  );
}

export function SourcesPanel({ sources, onOpen }: { sources: RunSource[]; onOpen?: (id: string) => void }) {
  const [sort, setSort] = useState<"relevance" | "credibility">("relevance");
  if (!sources.length) return <Empty>No sources were used yet.</Empty>;
  const sorted = [...sources].sort((a, b) => Number(b[sort] ?? 0) - Number(a[sort] ?? 0));
  return (
    <div className="space-y-2">
      <div className="flex justify-end gap-1 text-xs">
        <span className="self-center text-muted-foreground">Sort</span>
        {(["relevance", "credibility"] as const).map((k) => (
          <Button key={k} size="xs" variant={sort === k ? "secondary" : "ghost"} onClick={() => setSort(k)}>{k}</Button>
        ))}
      </div>
      <ul className="space-y-2">
        {sorted.map((s, i) => {
          const domain = s.domain || domainOf(s.url);
          const id = s.id ?? s.source_id;
          return (
            <li key={id ?? i} className="rounded-lg border p-3">
              <div className="flex items-start gap-2">
                <Favicon domain={domain} className="mt-0.5" />
                <div className="min-w-0 flex-1">
                  {s.url ? <a href={s.url} target="_blank" rel="noreferrer noopener" className="text-sm font-medium hover:underline">{s.title || s.url}</a> : <p className="text-sm font-medium">{s.title || "Untitled source"}</p>}
                  <p className="text-xs text-muted-foreground">{domain}{s.published_at && <> · {fmtDate(s.published_at)}</>}{s.steps?.length ? <> · steps {s.steps.join(", ")}</> : null}</p>
                  <div className="mt-1 flex flex-wrap gap-1">
                    <RelevanceBadge value={s.relevance} />
                    <CredibilityBadge value={s.credibility} />
                    {s.injection_flag && <InjectionBadge />}
                  </div>
                  {s.summary && <p className="mt-1 line-clamp-3 text-xs text-muted-foreground">{s.summary}</p>}
                  {id && onOpen && <Button size="xs" variant="link" className="px-0" onClick={() => onOpen(id)}>Details</Button>}
                </div>
              </div>
            </li>
          );
        })}
      </ul>
    </div>
  );
}

export function ReasoningPanel({ lines }: { lines: string[] }) {
  if (!lines.length) return <Empty>The planner&apos;s reasoning summary appears when the plan is ready.</Empty>;
  return (
    <div className="space-y-2 rounded-lg border p-3 text-sm">
      <p className="text-xs text-muted-foreground"><span className="text-ai">✦</span> Planner-written summary (goal, assumptions, decisions) — not raw model reasoning.</p>
      {lines.map((l, i) => <p key={i} className="whitespace-pre-wrap">{l}</p>)}
    </div>
  );
}

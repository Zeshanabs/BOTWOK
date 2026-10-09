"use client";
import { useState } from "react";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { CheckCircle2, Loader2, MessageSquareWarning, Send, ShieldAlert, XCircle } from "lucide-react";
import { toast } from "sonner";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Label } from "@/components/ui/label";
import { Textarea } from "@/components/ui/textarea";
import { StatusChip } from "@/components/data/status-chip";
import { QueryError, SkeletonRows } from "@/features/common/components/query-state";
import { usePermissions } from "@/features/common/hooks";
import type { ContentStatus } from "@/features/common/types";
import { errorMessage, errorStatus, relTime, toItems } from "@/features/common/utils";
import { api } from "@/lib/api";
import { cn } from "@/lib/utils";
import { policyFlags, type ContentItem } from "../../api";
import { useApprovalHistory, contentKeys } from "../../hooks";
import { useAllowedTransitions } from "../status-menu";

const RISK: Record<string, string> = { low: "bg-emerald-100 text-emerald-800 dark:bg-emerald-900/40 dark:text-emerald-200", medium: "bg-amber-100 text-amber-800 dark:bg-amber-900/40 dark:text-amber-200", high: "bg-red-100 text-red-800 dark:bg-red-900/40 dark:text-red-200" };

/** Approval tab: status, risk, request approval, role-gated transitions, decision on a pending approval, history. */
export function ApprovalPanel({ content, onRequestApproval, onTransition, transitionPending }: {
  content: ContentItem; onRequestApproval: () => void; onTransition: (to: ContentStatus) => void; transitionPending: boolean;
}) {
  const qc = useQueryClient();
  const { canCreate, canApprove } = usePermissions();
  const history = useApprovalHistory(content.id);
  const items = toItems(history.data).sort((a, b) => (a.created_at < b.created_at ? 1 : -1));
  const pending = items.find((a) => a.status === "pending");
  const [comment, setComment] = useState("");
  const allowed = useAllowedTransitions(content.status);
  const flags = policyFlags(content.critique);
  const [ack, setAck] = useState(false);

  const decide = useMutation({
    mutationFn: ({ kind }: { kind: "approve" | "rejected" | "changes_requested" }) => kind === "approve"
      ? api.post(`/approvals/${pending?.id}/approve`, { comment: comment.trim() || undefined, acknowledged_flags: ack ? flags.map((f) => f.code ?? f.message) : [] })
      : api.post(`/approvals/${pending?.id}/reject`, { comment: comment.trim(), decision: kind === "rejected" ? "reject" : "request_changes" }),
    onSuccess: (_r, v) => {
      toast.success(v.kind === "approve" ? "Approved" : v.kind === "rejected" ? "Rejected" : "Changes requested");
      setComment("");
      void qc.invalidateQueries({ queryKey: contentKeys.detail(content.id) });
      void qc.invalidateQueries({ queryKey: ["approvals"] });
    },
    onError: (e) => toast.error(errorStatus(e) === 409 ? `Already decided: ${errorMessage(e)}` : errorMessage(e)),
  });
  const canRequest = canCreate && ["draft", "ai_generated", "rejected", "idea"].includes(content.status);

  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-center gap-2">
        <StatusChip status={content.status} />
        {content.risk_level && <Badge className={cn("border-0", RISK[content.risk_level])}>risk: {content.risk_level}</Badge>}
        {content.approval_required !== false && <Badge variant="outline">approval required</Badge>}
      </div>
      {canRequest && <Button size="sm" onClick={onRequestApproval}><Send /> Request approval <kbd className="ml-1 rounded border px-1 text-[10px]">⌘↵</kbd></Button>}
      {allowed.length > 0 && (
        <div className="flex flex-wrap gap-1.5">
          {allowed.filter((t) => !(pending && (t.to === "approved" || t.to === "rejected"))).map((t) => (
            <Button key={t.to + t.label} size="xs" variant="outline" disabled={transitionPending} onClick={() => onTransition(t.to)}>{t.label}</Button>
          ))}
        </div>
      )}
      {pending && (
        <div className="space-y-2 rounded-md border border-amber-300 bg-amber-50/50 p-3 dark:border-amber-800 dark:bg-amber-900/10">
          <p className="text-sm font-medium">Waiting for approval</p>
          <p className="text-xs text-muted-foreground">Requested {relTime(pending.created_at)}{pending.requested_by_name ? ` by ${pending.requested_by_name}` : ""}{pending.expires_at ? ` · expires ${relTime(pending.expires_at)}` : ""}</p>
          {typeof (pending.payload?.comment ?? pending.payload?.note) === "string" && <p className="text-xs italic">“{String(pending.payload?.comment ?? pending.payload?.note)}”</p>}
          {canApprove ? (
            <>
              {flags.length > 0 && (
                <label className="flex items-start gap-2 text-xs text-red-700 dark:text-red-300">
                  <input type="checkbox" checked={ack} onChange={(e) => setAck(e.target.checked)} className="mt-0.5" />
                  <span><ShieldAlert className="mr-1 inline h-3.5 w-3.5" />I acknowledge {flags.length} policy flag(s): {flags.map((f) => f.message).join("; ")}</span>
                </label>
              )}
              <Label htmlFor="appr-comment" className="text-xs">Comment <span className="text-muted-foreground">(required to reject or request changes)</span></Label>
              <Textarea id="appr-comment" rows={2} value={comment} onChange={(e) => setComment(e.target.value)} />
              <div className="flex flex-wrap gap-1.5">
                <Button size="sm" disabled={decide.isPending || (flags.length > 0 && !ack)} onClick={() => decide.mutate({ kind: "approve" })}>{decide.isPending ? <Loader2 className="animate-spin" /> : <CheckCircle2 />} Approve</Button>
                <Button size="sm" variant="outline" disabled={decide.isPending || !comment.trim()} onClick={() => decide.mutate({ kind: "changes_requested" })}><MessageSquareWarning /> Request changes</Button>
                <Button size="sm" variant="outline" disabled={decide.isPending || !comment.trim()} onClick={() => decide.mutate({ kind: "rejected" })}><XCircle /> Reject</Button>
              </div>
            </>
          ) : <p className="text-xs text-muted-foreground">Only approvers, admins and owners can decide.</p>}
        </div>
      )}
      <section aria-labelledby="hist-h">
        <h3 id="hist-h" className="mb-2 text-xs font-semibold uppercase tracking-wide text-muted-foreground">Decision history</h3>
        {history.isLoading && <SkeletonRows rows={2} />}
        {history.error && <QueryError error={history.error} onRetry={() => history.refetch()} notAvailableText="Approval history isn't available yet." />}
        {history.data && items.length === 0 && <p className="text-xs text-muted-foreground">No approval requests yet.</p>}
        <ol className="space-y-2">
          {items.map((a) => (
            <li key={a.id} className="rounded-md border p-2 text-xs">
              <div className="flex items-center gap-2"><StatusChip status={a.status} /><span className="text-muted-foreground">{relTime(a.decided_at ?? a.created_at)}</span></div>
              {(a.decided_by_name || a.decided_by) && <p className="mt-1">by {a.decided_by_name ?? a.decided_by}</p>}
              {a.decision_comment && <p className="mt-1 italic">“{a.decision_comment}”</p>}
              {typeof (a.payload?.decision ?? a.payload?.resolution) === "string" && <p className="mt-1 text-muted-foreground">decision: {String(a.payload?.decision ?? a.payload?.resolution).replace(/_/g, " ")}</p>}
            </li>
          ))}
        </ol>
      </section>
    </div>
  );
}

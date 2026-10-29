"use client";
import { useState } from "react";
import Link from "next/link";
import { useQuery } from "@tanstack/react-query";
import { ArrowLeft, ChevronDown, ChevronLeft, ChevronRight, ExternalLink, ShieldAlert, Sparkles } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Skeleton } from "@/components/ui/skeleton";
import { Textarea } from "@/components/ui/textarea";
import { PlatformIcon } from "@/components/shared/platform-icon";
import { StatusChip } from "@/components/shared/status-chip";
import { AiBadge, CostPill } from "@/features/common/components/ai-badge";
import { QueryError } from "@/features/common/components/query-state";
import { useWorkspacePath } from "@/features/common/hooks";
import { fmtUsd, relTime, validationIssues } from "@/features/common/utils";
import { contentApi, issueText, policyFlags, sourceView, type ContentItem } from "@/features/studio/api";
import { composeMaster } from "@/features/studio/platform-rules";
import { ClaimVerdicts, normalizeScore, ScoreBars } from "@/features/studio/components/panels/critic-panel";
import { PlatformPreview } from "@/features/studio/components/platform-preview";
import { toSegs } from "@/features/studio/segments";
import { platformMeta } from "@/lib/platforms";
import { cn } from "@/lib/utils";
import { approvalComment, approvalTitle, approvalsApi, type Approval } from "../api";

export type Decision = "approve" | "request_changes" | "reject";

/** Everything needed to decide one approval: previews per platform, critic, fact-check, sources, AI provenance + decision bar. */
export function ApprovalDetail({ id, onDecide, deciding, canDecide, position, onPrev, onNext, onBack, decideError }: {
  id: string; onDecide: (a: Approval, d: Decision, comment: string, ack: string[]) => void; deciding: boolean; canDecide: boolean;
  position?: { index: number; total: number }; onPrev?: () => void; onNext?: () => void; onBack?: () => void; decideError?: string | null;
}) {
  const ws = useWorkspacePath();
  const q = useQuery({ queryKey: ["approvals", id], queryFn: () => approvalsApi.get(id) });
  const a = q.data;
  const isContent = !!a && (a.target_type.includes("content") || a.kind === "content");
  const contentQ = useQuery({ queryKey: ["content", a?.target_id ?? ""], queryFn: () => contentApi.get(a!.target_id), enabled: isContent && !a?.target?.item && a?.target_type === "content_item" && !a?.target?.missing });
  const content: ContentItem | null | undefined = a?.target?.item ?? contentQ.data;
  const [tab, setTab] = useState<string>("auto");
  const [mode, setMode] = useState<"preview" | "text">("preview");
  const [comment, setComment] = useState("");
  const [ack, setAck] = useState(false);
  const [showSources, setShowSources] = useState(false);
  const [showClaims, setShowClaims] = useState(false);

  if (q.isLoading) return <div className="space-y-3" aria-busy="true"><Skeleton className="h-7 w-2/3" /><Skeleton className="h-64" /><Skeleton className="h-24" /></div>;
  if (q.error) return <QueryError error={q.error} onRetry={() => q.refetch()} title="Couldn't load this approval" />;
  if (!a) return null;

  const variants = a.target?.variants?.length ? a.target.variants : content?.variants ?? [];
  const current = tab === "auto" ? a.target?.variant_id ?? variants[0]?.id ?? "master" : tab;
  const v = variants.find((x) => x.id === current) ?? null;
  const itemCritique = a.target?.critique ?? content?.critique ?? null;
  const critique = v?.critique ?? itemCritique;
  const claims = [...(a.target?.factcheck?.claims ?? content?.factcheck?.claims ?? []), ...variants.flatMap((x) => x.factcheck?.claims ?? [])];
  const count = (k: string) => claims.filter((c) => (k === "unverifiable" ? !["supported", "contradicted", "opinion"].includes(c.verdict) : c.verdict === k)).length;
  const flagMap = new Map([...policyFlags(itemCritique), ...variants.flatMap((x) => policyFlags(x.critique))].map((f) => [f.code ?? f.message, f]));
  const flags = Array.from(flagMap.values());
  const sources = (a.target?.sources ?? content?.sources ?? []).map(sourceView);
  const meta = a.target?.generation_metadata ?? content?.generation_metadata ?? null;
  const runs = a.runs ?? [];
  const runCost = runs.reduce((s, r) => s + Number(r.cost_usd ?? 0), 0);
  const pending = a.status === "pending";
  const media = [...(v?.assets ?? []), ...(content?.assets ?? []).filter((x) => !x.variant_id)].map((x) => ({ id: x.media_asset_id, ...(x.media ?? {}), alt_text: x.alt_text ?? x.media?.alt_text }));
  const text = v ? (v.text ?? "") : content ? composeMaster({ ...content.body, hashtags: [] }) : "";
  const segs = v ? toSegs(v.segments).segs.map((s) => s.text) : [];
  const valErrors = variants.flatMap((x) => validationIssues(x.validation).errors.map((e) => `${platformMeta(x.platform).label}: ${e.message}`));
  const title = approvalTitle(a);

  const approveNow = () => { if (canDecide && pending && !deciding && !(flags.length > 0 && !ack) && valErrors.length === 0) onDecide(a, "approve", comment, ack ? flags.map((f) => f.code ?? f.message) : []); };
  return (
    <div className="space-y-4" onKeyDown={(e) => { if ((e.metaKey || e.ctrlKey) && e.key === "Enter") { e.preventDefault(); approveNow(); } }}>
      <div className="flex flex-wrap items-start gap-2">
        {onBack && <Button size="icon-sm" variant="ghost" aria-label="Back to inbox" onClick={onBack}><ArrowLeft /></Button>}
        <div className="min-w-0 flex-1">
          <h2 className="text-lg font-semibold">“{title}”{v && <span className="font-normal text-muted-foreground"> · {platformMeta(v.platform).label} variant</span>}{content && <span className="font-normal text-muted-foreground"> · v{v?.current_version ?? content.current_version}</span>}</h2>
          <p className="text-sm text-muted-foreground">
            Requested by {a.requested_by_name ?? (a.requested_by.startsWith("agent:") || a.requested_by.startsWith("automation") ? `✦ ${a.requested_by}` : a.requested_by)} · {relTime(a.created_at)}
            {a.due_at && ` · due ${relTime(a.due_at)}`}{a.expires_at && pending && ` · expires ${relTime(a.expires_at)}`}
          </p>
          {approvalComment(a) && <p className="mt-1 text-sm italic">“{approvalComment(a)}”</p>}
          {typeof a.payload?.risk_level === "string" && <p className="mt-1 text-xs text-muted-foreground">Risk: {a.payload.risk_level}{a.payload.risk_level === "high" ? " — admins/owners decide" : ""}</p>}
        </div>
        <StatusChip status={a.status} />
        {isContent && <Button asChild size="sm" variant="outline"><Link href={ws(`studio/${a.target_id}`)}>Open in Studio <ExternalLink /></Link></Button>}
      </div>

      {a.target?.missing ? <p className="rounded-md border p-3 text-sm text-muted-foreground">The content for this request no longer exists.</p> : isContent ? (
        <>
          {contentQ.isLoading && <Skeleton className="h-48" />}
          {contentQ.error && <QueryError error={contentQ.error} onRetry={() => contentQ.refetch()} title="Couldn't load the content" />}
          {content && (
            <>
              <div className="flex flex-wrap items-center gap-2">
                <div className="flex flex-wrap gap-1" role="tablist" aria-label="Versions to review">
                  {variants.map((x) => <button key={x.id} type="button" role="tab" aria-selected={current === x.id} onClick={() => setTab(x.id)} className={cn("flex items-center gap-1 rounded-md border px-2 py-1 text-xs", current === x.id && "border-primary bg-primary/5")}><PlatformIcon platform={x.platform} size={16} />{platformMeta(x.platform).label}</button>)}
                  <button type="button" role="tab" aria-selected={current === "master"} onClick={() => setTab("master")} className={cn("rounded-md border px-2 py-1 text-xs", current === "master" && "border-primary bg-primary/5")}>Master</button>
                </div>
                <div className="ml-auto flex rounded-md border p-0.5 text-xs" role="radiogroup" aria-label="Display">
                  {(["preview", "text"] as const).map((m) => <button key={m} type="button" role="radio" aria-checked={mode === m} onClick={() => setMode(m)} className={cn("rounded px-2 py-1 capitalize", mode === m && "bg-secondary")}>{m}</button>)}
                </div>
              </div>
              {mode === "preview"
                ? <div className="mx-auto max-w-[520px]"><PlatformPreview platform={v?.platform ?? "linkedin"} format={v?.format} text={text} hashtags={v?.hashtags ?? content.body?.hashtags} segments={segs.length && v?.format !== "carousel" ? segs : undefined} media={media} title={typeof v?.platform_metadata?.title === "string" ? v.platform_metadata.title : content.title} /></div>
                : <pre className="whitespace-pre-wrap rounded-md border bg-muted/40 p-3 font-sans text-sm">{segs.length ? segs.join("\n\n— — —\n\n") : text}{(v?.hashtags ?? []).length ? `\n\n${v?.hashtags?.join(" ")}` : ""}</pre>}
              {(v?.changes_made ?? []).length > 0 && <p className="text-xs text-muted-foreground"><Sparkles className="mr-1 inline h-3 w-3 text-ai" />Changes from master: {v?.changes_made?.join("; ")}</p>}
              {valErrors.length > 0 && <ul className="rounded-md border border-destructive/40 bg-destructive/[0.06] p-2 text-xs text-destructive">{valErrors.map((e, i) => <li key={i}>✗ {e}</li>)}</ul>}

              <div className="grid gap-4 md:grid-cols-2">
                <section className="rounded-lg border p-3">
                  <div className="mb-2 flex items-center gap-2"><h3 className="text-sm font-medium">Critic</h3>{critique?.model && <span className="text-xs text-muted-foreground">{critique.model}</span>}{critique && normalizeScore(critique.overall) != null && <span className="ml-auto text-sm font-semibold tabular-nums">{Math.round(normalizeScore(critique.overall) ?? 0)}</span>}</div>
                  {critique ? <ScoreBars critique={critique} /> : <p className="text-xs text-muted-foreground">Not scored.</p>}
                  {critique?.recommend && <p className="mt-2 text-xs">Recommends <span className="font-medium">{critique.recommend}</span>{critique.risk_level ? ` · risk ${critique.risk_level}` : ""}</p>}
                  {(critique?.issues ?? []).length > 0 && <ul className="mt-2 list-disc pl-4 text-xs">{critique?.issues?.slice(0, 4).map((x, i) => <li key={i}>{issueText(x)}</li>)}</ul>}
                </section>
                <section className="rounded-lg border p-3">
                  <h3 className="mb-2 text-sm font-medium">Fact-check</h3>
                  {claims.length === 0 ? <p className="text-xs text-muted-foreground">No claims checked.</p> : (
                    <>
                      <p className="text-sm"><span className="text-success">{count("supported")} ✓</span> · <span className="text-warning">{count("unverifiable")} ? unverified</span> · <span className="text-destructive">{count("contradicted")} ✗ contradicted</span></p>
                      <Button size="xs" variant="ghost" className="mt-1" onClick={() => setShowClaims((s) => !s)}><ChevronDown className={cn(showClaims && "rotate-180")} /> {showClaims ? "Hide" : "View"} claims</Button>
                      {showClaims && <div className="mt-2"><ClaimVerdicts claims={claims} /></div>}
                    </>
                  )}
                </section>
              </div>
              <section className="rounded-lg border p-3 text-sm">
                <button type="button" className="flex w-full items-center gap-2 text-left" onClick={() => setShowSources((s) => !s)} aria-expanded={showSources}>
                  <ChevronDown className={cn("h-4 w-4", showSources && "rotate-180")} /> Sources ({sources.length})
                  <span className="ml-auto flex items-center gap-2 text-xs text-muted-foreground">
                    {meta && (meta.agent || meta.model) && <AiBadge meta={meta} label={meta.agent ?? "AI"} />}
                    {runs.length > 0 && `${runs.length} run${runs.length === 1 ? "" : "s"}`}<CostPill usd={runs.length ? runCost : meta?.cost_usd} />
                  </span>
                </button>
                {showSources && (
                  <ol className="mt-2 space-y-1 text-xs">
                    {sources.length === 0 && <li className="text-muted-foreground">No sources attached.</li>}
                    {sources.map((s, i) => <li key={s.id + i}>[{i + 1}] {s.url ? <a className="text-primary hover:underline" href={s.url} target="_blank" rel="noreferrer">{s.title ?? s.url}</a> : s.title} {s.domain && <span className="text-muted-foreground">· {s.domain}</span>}</li>)}
                  </ol>
                )}
                {(meta || runs.length > 0) && (
                  <div className="mt-2 border-t pt-2 text-xs text-muted-foreground">
                    {meta && <p>Generation: {[meta.agent, meta.provider, meta.model].filter(Boolean).join(" · ")}{meta.prompt_version ? ` · prompt ${meta.prompt_version}` : ""}{meta.cost_usd != null ? ` · ${fmtUsd(meta.cost_usd)}` : ""}</p>}
                    {runs.map((r) => <p key={r.id}><Link className="hover:underline" href={ws(`command-center/${r.id}`)}>✦ {r.agent ?? "run"}{r.model ? ` · ${r.model}` : ""}{r.prompt_version ? ` · ${r.prompt_version}` : ""} · {fmtUsd(r.cost_usd)} ↗</Link></p>)}
                  </div>
                )}
              </section>
            </>
          )}
        </>
      ) : (
        <section className="rounded-lg border p-3 text-sm">
          <p className="mb-2 font-medium">{a.kind === "ai_action" ? "✦ Proposed AI action" : a.kind === "automation_step" ? "Automation step waiting" : a.kind}</p>
          {typeof a.payload?.description === "string" && <p>{a.payload.description}</p>}
          <pre className="mt-2 max-h-64 overflow-auto rounded bg-muted p-2 text-xs">{JSON.stringify(a.payload, null, 2)}</pre>
          {runs.map((r) => <p key={r.id} className="mt-1 text-xs"><Link className="text-primary hover:underline" href={ws(`command-center/${r.id}`)}>Run {r.id.slice(0, 8)} ↗</Link></p>)}
        </section>
      )}

      {!pending && (
        <div className="rounded-md border p-3 text-sm"><StatusChip status={a.status} /> {a.decided_by_name ?? a.decided_by ? `by ${a.decided_by_name ?? a.decided_by}` : ""} {a.decided_at && relTime(a.decided_at)}{a.decision_comment && <p className="mt-1 italic">“{a.decision_comment}”</p>}{typeof a.payload?.decision === "string" && <p className="text-xs text-muted-foreground">decision: {a.payload.decision.replace(/_/g, " ")}</p>}</div>
      )}

      {pending && (
        <div className="sticky bottom-0 z-10 space-y-2 border-t bg-background/95 py-3 backdrop-blur">
          {flags.length > 0 && canDecide && (
            <label className="flex items-start gap-2 text-sm text-destructive">
              <input type="checkbox" className="mt-1" checked={ack} onChange={(e) => setAck(e.target.checked)} />
              <span><ShieldAlert className="mr-1 inline h-4 w-4" />I acknowledge {flags.length} policy flag(s): {flags.map((f) => f.message).join("; ")}</span>
            </label>
          )}
          {canDecide ? (
            <>
              <Textarea id="decision-comment" rows={2} value={comment} onChange={(e) => setComment(e.target.value)} placeholder="Comment — optional to approve, required to request changes or reject" aria-label="Decision comment" />
              {decideError && <p className="text-sm text-destructive">{decideError}</p>}
              <div className="flex flex-wrap items-center gap-2">
                <Button onClick={() => onDecide(a, "approve", comment, ack ? flags.map((f) => f.code ?? f.message) : [])} disabled={deciding || (flags.length > 0 && !ack) || valErrors.length > 0} title={valErrors.length ? "Validation errors must be fixed first" : undefined}>Approve <kbd className="ml-1 hidden rounded border border-primary-foreground/40 px-1 text-[10px] sm:inline">⌘↵</kbd></Button>
                <Button variant="outline" onClick={() => onDecide(a, "request_changes", comment, [])} disabled={deciding || !comment.trim()}>Request changes</Button>
                <Button variant="outline" onClick={() => onDecide(a, "reject", comment, [])} disabled={deciding || !comment.trim()}>Reject</Button>
                {position && (
                  <span className="ml-auto flex items-center gap-1 text-xs text-muted-foreground">
                    <Button size="icon-xs" variant="ghost" aria-label="Previous" onClick={onPrev} disabled={!onPrev}><ChevronLeft /></Button>
                    {position.index + 1} of {position.total}
                    <Button size="icon-xs" variant="ghost" aria-label="Next" onClick={onNext} disabled={!onNext}><ChevronRight /></Button>
                  </span>
                )}
              </div>
            </>
          ) : <p className="text-sm text-muted-foreground">You can view this request; approvers, admins and owners decide.</p>}
        </div>
      )}
    </div>
  );
}

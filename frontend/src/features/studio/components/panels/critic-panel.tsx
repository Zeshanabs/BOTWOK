"use client";
import { useState } from "react";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { AlertTriangle, CheckCircle2, HelpCircle, Loader2, ShieldAlert, Sparkles, XCircle } from "lucide-react";
import { toast } from "sonner";
import { Button } from "@/components/ui/button";
import { CostPill } from "@/features/common/components/ai-badge";
import { QueryError } from "@/features/common/components/query-state";
import { RunCard } from "@/features/common/components/run-card";
import { usePermissions } from "@/features/common/hooks";
import { cn } from "@/lib/utils";
import { contentApi, critiqueSuggestions, isRunAccepted, issueText, policyFlags, type ClaimVerdict, type ContentItem, type ContentVariant, type Critique, type FactCheck } from "../../api";
import { contentKeys } from "../../hooks";

/** Scores may come as 0–1, 0–10 or 0–100; normalize to 0–100. */
export function normalizeScore(v: number | null | undefined): number | null {
  if (v == null || Number.isNaN(Number(v))) return null;
  const n = Number(v);
  if (n <= 1) return n * 100;
  if (n <= 10) return n * 10;
  return Math.min(100, n);
}
const label = (k: string) => k.replace(/_/g, " ").replace(/\b\w/g, (c) => c.toUpperCase());

export function ScoreBars({ critique }: { critique: Critique }) {
  const entries = Object.entries(critique.scores ?? {}).filter(([, v]) => v != null);
  const overall = normalizeScore(critique.overall ?? null);
  return (
    <div className="space-y-2">
      {overall != null && <ScoreRow name="Quality (overall)" value={overall} strong />}
      {entries.map(([k, v]) => {
        const s = normalizeScore(v);
        if (s == null) return null;
        // policy_risk: higher = riskier → invert display color
        return <ScoreRow key={k} name={label(k)} value={s} invert={/risk/.test(k)} />;
      })}
    </div>
  );
}
function ScoreRow({ name, value, strong, invert }: { name: string; value: number; strong?: boolean; invert?: boolean }) {
  const good = invert ? value < 30 : value >= 75;
  const mid = invert ? value < 60 : value >= 55;
  return (
    <div>
      <div className="flex justify-between text-xs"><span className={cn(strong && "font-medium")}>{name}</span><span className="tabular-nums">{Math.round(value)}</span></div>
      <div className="mt-0.5 h-1.5 overflow-hidden rounded-full bg-muted" role="meter" aria-valuemin={0} aria-valuemax={100} aria-valuenow={Math.round(value)} aria-label={name}>
        <div className={cn("h-full rounded-full", good ? "bg-emerald-500" : mid ? "bg-amber-500" : "bg-red-500")} style={{ width: `${value}%` }} />
      </div>
    </div>
  );
}

const SEV: Record<string, string> = { blocker: "text-red-600", high: "text-red-600", error: "text-red-600", medium: "text-amber-600", warning: "text-amber-600", low: "text-muted-foreground", info: "text-muted-foreground" };

export function VerdictIcon({ verdict }: { verdict: string }) {
  if (verdict === "supported") return <CheckCircle2 className="h-4 w-4 shrink-0 text-emerald-600" aria-label="supported" />;
  if (verdict === "opinion") return <CheckCircle2 className="h-4 w-4 shrink-0 text-muted-foreground" aria-label="opinion" />;
  if (verdict === "contradicted") return <XCircle className="h-4 w-4 shrink-0 text-red-600" aria-label="contradicted" />;
  return <HelpCircle className="h-4 w-4 shrink-0 text-amber-600" aria-label="unverifiable" />;
}

/** Per-claim fact-check verdicts with evidence and sources. */
export function ClaimVerdicts({ claims }: { claims: ClaimVerdict[] }) {
  if (!claims.length) return <p className="text-xs text-muted-foreground">No factual claims were found.</p>;
  return (
    <ul className="space-y-2">
      {claims.map((c, i) => (
        <li key={i} className={cn("rounded-md border p-2 text-xs", c.verdict === "contradicted" && "border-red-300 dark:border-red-800", !["supported", "contradicted", "opinion"].includes(c.verdict) && "border-amber-300 dark:border-amber-800")}>
          <div className="flex items-start gap-2"><VerdictIcon verdict={c.verdict} /><p className="font-medium">“{c.claim ?? c.text}”</p></div>
          <p className="mt-1 pl-6 capitalize text-muted-foreground">{c.verdict}{c.confidence != null ? ` · confidence ${Math.round(normalizeScore(c.confidence) ?? 0)}%` : ""}</p>
          {typeof c.evidence === "string" && c.evidence && <p className="mt-1 pl-6">{c.evidence}</p>}
          {Array.isArray(c.evidence) && c.evidence.length > 0 && (
            <ul className="mt-1 space-y-0.5 pl-6">{c.evidence.map((ev, j) => <li key={j} className="italic text-muted-foreground">{ev.quote ? `“${ev.quote}”` : "source"}{ev.source_id && <span className="ml-1 font-mono not-italic">[{ev.source_id.slice(0, 8)}]</span>}</li>)}</ul>
          )}
          {c.regulated_domain && <p className="mt-1 pl-6 text-amber-700 dark:text-amber-300">Regulated domain: {c.regulated_domain}</p>}
          {(c.sources ?? []).length > 0 && (
            <ul className="mt-1 space-y-0.5 pl-6">
              {(c.sources ?? []).map((s, j) => <li key={s.id ?? j}>{s.url ? <a className="text-primary hover:underline" href={s.url} target="_blank" rel="noreferrer">{s.title ?? s.domain ?? s.url}</a> : s.title}</li>)}
            </ul>
          )}
        </li>
      ))}
    </ul>
  );
}

/** Critic tab: scores, issues, suggestions, policy flags, fact-check; re-run buttons with run transparency. */
export function CriticPanel({ content, variant, onApplySuggestion }: { content: ContentItem; variant: ContentVariant | null; onApplySuggestion?: (text: string, field?: string | null) => void }) {
  const qc = useQueryClient();
  const { canCreate } = usePermissions();
  const [runs, setRuns] = useState<{ id: string; kind: string }[]>([]);
  const critique = variant?.critique ?? content.critique ?? null;
  const fact: FactCheck | null = variant?.factcheck ?? content.factcheck ?? null;
  const refresh = () => void qc.invalidateQueries({ queryKey: contentKeys.detail(content.id) });
  const handle = (kind: string) => (r: unknown) => {
    if (isRunAccepted(r)) setRuns((s) => [{ id: r.run_id, kind }, ...s]);
    else { refresh(); toast.success(`${kind} updated`); }
  };
  const runCritic = useMutation({ mutationFn: () => contentApi.critique(content.id, { variant_id: variant?.id }), onSuccess: handle("Critic") });
  const runFact = useMutation({ mutationFn: () => contentApi.factCheck(content.id, { variant_id: variant?.id }), onSuccess: handle("Fact-check") });
  const suggestions = critiqueSuggestions(critique);
  const flags = policyFlags(critique);

  return (
    <div className="space-y-4">
      <div className="flex flex-wrap gap-2">
        <Button size="sm" variant="outline" onClick={() => runCritic.mutate()} disabled={!canCreate || runCritic.isPending}>{runCritic.isPending ? <Loader2 className="animate-spin" /> : <Sparkles className="text-ai" />} Run critic</Button>
        <Button size="sm" variant="outline" onClick={() => runFact.mutate()} disabled={!canCreate || runFact.isPending}>{runFact.isPending ? <Loader2 className="animate-spin" /> : <ShieldAlert />} Run fact-check</Button>
      </div>
      {runCritic.error && <QueryError error={runCritic.error} title="Critic not started" notAvailableText="The critic endpoint isn't available on this backend yet." />}
      {runFact.error && <QueryError error={runFact.error} title="Fact-check not started" notAvailableText="Fact-checking isn't available on this backend yet." />}
      {runs.map((r) => <RunCard key={r.id} runId={r.id} title={r.kind} compact onDone={refresh} />)}

      <section aria-labelledby="critic-h">
        <div className="mb-2 flex items-center gap-2">
          <h3 id="critic-h" className="text-xs font-semibold uppercase tracking-wide text-muted-foreground">✦ Critic {variant ? `(${variant.platform})` : "(master)"}</h3>
          <CostPill usd={critique?.cost_usd} className="ml-auto" />
        </div>
        {!critique ? <p className="text-sm text-muted-foreground">Not scored yet. The critic runs automatically after AI generation, or run it now.</p> : (
          <div className="space-y-3">
            <ScoreBars critique={critique} />
            <p className="text-[11px] text-muted-foreground">
              {critique.agent ?? "critic"}{critique.model ? ` · ${critique.model}` : ""}{critique.same_model ? " · same-model critique (reduced independence)" : " · different model than the writer"}
            </p>
            {critique.recommend && <p className="text-xs">Critic recommends: <span className={cn("font-medium", critique.recommend === "approve" ? "text-emerald-700 dark:text-emerald-300" : critique.recommend === "reject" ? "text-red-700 dark:text-red-300" : "text-amber-700 dark:text-amber-300")}>{critique.recommend}</span>{critique.risk_level ? ` · risk ${critique.risk_level}` : ""}</p>}
            {flags.length > 0 && (
              <div className="rounded-md border border-red-300 bg-red-50 p-2 text-xs dark:border-red-800 dark:bg-red-900/20">
                <p className="flex items-center gap-1 font-medium text-red-700 dark:text-red-200"><ShieldAlert className="h-3.5 w-3.5" /> Policy flags — approvers must acknowledge</p>
                <ul className="mt-1 list-disc pl-4">{flags.map((f, i) => <li key={i}>{f.message}{f.code && f.code !== f.message && <span className="ml-1 font-mono text-muted-foreground">{f.code}</span>}</li>)}</ul>
              </div>
            )}
            {(critique.issues ?? []).length > 0 && (
              <div>
                <p className="mb-1 text-xs font-medium">Issues</p>
                <ul className="space-y-1 text-xs">
                  {critique.issues?.map((iss, i) => (
                    <li key={i} className="flex gap-2"><AlertTriangle className={cn("mt-0.5 h-3.5 w-3.5 shrink-0", SEV[iss.severity ?? "info"] ?? "text-muted-foreground")} /><span><span className="mr-1 uppercase text-muted-foreground">{iss.severity}</span>{issueText(iss)}{iss.suggestion && <span className="block text-muted-foreground">→ {iss.suggestion}</span>}</span></li>
                  ))}
                </ul>
              </div>
            )}
            {suggestions.length > 0 && (
              <div>
                <p className="mb-1 text-xs font-medium">Rewrite suggestions</p>
                <ul className="space-y-1.5 text-xs">
                  {suggestions.map((s, i) => (
                    <li key={i} className="rounded-md bg-muted p-2">
                      <p>{s.text ?? s.message}</p>
                      {s.rationale && <p className="mt-0.5 text-muted-foreground">{s.rationale}</p>}
                      {s.replacement && onApplySuggestion && canCreate && <Button size="xs" variant="outline" className="mt-1" onClick={() => onApplySuggestion(s.replacement as string, s.field)}>Apply</Button>}
                    </li>
                  ))}
                </ul>
              </div>
            )}
          </div>
        )}
      </section>
      <section aria-labelledby="fact-h">
        <div className="mb-2 flex items-center gap-2">
          <h3 id="fact-h" className="text-xs font-semibold uppercase tracking-wide text-muted-foreground">Fact-check {fact?.claims ? `(${fact.claims.length} claims)` : ""}</h3>
          <CostPill usd={fact?.cost_usd} className="ml-auto" />
        </div>
        {!fact ? <p className="text-sm text-muted-foreground">No fact-check yet.</p> : <ClaimVerdicts claims={fact.claims ?? []} />}
        {fact?.model && <p className="mt-1 text-[11px] text-muted-foreground">fact_check · {fact.model}</p>}
      </section>
    </div>
  );
}

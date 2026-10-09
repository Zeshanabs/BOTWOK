"use client";
import { useState } from "react";
import Link from "next/link";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Check, HelpCircle, Lightbulb, Sparkles, X } from "lucide-react";
import { toast } from "sonner";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Popover, PopoverContent, PopoverTrigger } from "@/components/ui/popover";
import { Sheet, SheetContent, SheetDescription, SheetHeader, SheetTitle } from "@/components/ui/sheet";
import { QueryError, SkeletonRows } from "@/features/common/components/query-state";
import { usePermissions, useWorkspacePath } from "@/features/common/hooks";
import { errorMessage, fmtDate, isNotAvailable, toItems } from "@/features/common/utils";
import { analyticsApi, coverageText, normalizeInsights, type Insight, type Recommendation } from "../api";

/** Load open recommendations: GET /insights/recommendations, falling back to GET /insights when that route is absent. */
export function useRecommendations(brandId: string | null) {
  return useQuery({
    queryKey: ["insights", "recommendations", brandId],
    queryFn: async (): Promise<{ recommendations: Recommendation[]; insights: Insight[] }> => {
      try {
        const r = await analyticsApi.recommendations({ brand_id: brandId, status: "proposed" });
        return { recommendations: toItems(r), insights: [] };
      } catch (e) {
        if (!isNotAvailable(e)) throw e;
        const r = await analyticsApi.insights({ brand_id: brandId });
        return normalizeInsights(r);
      }
    },
    enabled: !!brandId,
    retry: false,
  });
}

const OPEN = ["proposed", "open", "new"];
const ACTION_LABEL: Record<string, string> = { generate_ideas: "Generate ideas", adjust_pillar_mix: "Adjust pillar mix", change_posting_times: "Change posting times", test_format: "Test a format", update_strategy: "Update strategy", reuse_top_post: "Reuse top post" };

/** Recommendation cards with Accept / Dismiss (reason) / evidence. Accepting never edits schedules directly. */
export function RecommendationList({ brandId, recommendations, insights, limit, emptyText = "No open recommendations." }: {
  brandId: string | null; recommendations: Recommendation[]; insights: Insight[]; limit?: number; emptyText?: string;
}) {
  const qc = useQueryClient();
  const ws = useWorkspacePath();
  const { canCreate } = usePermissions();
  const [evidence, setEvidence] = useState<Recommendation | null>(null);
  const [reason, setReason] = useState("");
  const key = ["insights", "recommendations", brandId];
  const decide = useMutation({
    mutationFn: ({ id, status, reason: why }: { id: string; status: "accepted" | "rejected"; reason?: string }) => analyticsApi.decide(id, { status, reason: why }),
    onMutate: async ({ id, status }) => {
      await qc.cancelQueries({ queryKey: key });
      const prev = qc.getQueryData(key);
      qc.setQueryData(key, (old: { recommendations: Recommendation[]; insights: Insight[] } | undefined) => old && { ...old, recommendations: old.recommendations.map((r) => (r.id === id ? { ...r, status } : r)) });
      return { prev };
    },
    onError: (e, _v, ctx) => { qc.setQueryData(key, ctx?.prev); toast.error(`Not saved: ${errorMessage(e)}`); },
    onSuccess: (_r, v) => { toast.success(v.status === "accepted" ? "Accepted — a proposal is being prepared for your review" : "Dismissed — the analyst won’t repeat it for 30 days"); setReason(""); },
    onSettled: () => { void qc.invalidateQueries({ queryKey: ["insights"] }); },
  });
  const open = recommendations.filter((r) => OPEN.includes(r.status)).slice(0, limit ?? 50);
  const insightOf = (r: Recommendation) => insights.find((i) => i.id === r.insight_id) ?? null;
  if (open.length === 0) return <p className="text-sm text-muted-foreground">{emptyText}</p>;
  return (
    <>
      <ul className="space-y-2">
        {open.map((r) => {
          const ins = insightOf(r);
          return (
            <li key={r.id} className="rounded-md border p-3 text-sm">
              <p className="flex items-start gap-2"><Lightbulb className="mt-0.5 h-4 w-4 shrink-0 text-ai" /><span className="font-medium">{r.title ?? ins?.statement ?? ACTION_LABEL[r.action] ?? r.action}</span></p>
              {r.rationale && <p className="mt-1 pl-6 text-xs text-muted-foreground">{r.rationale}</p>}
              <p className="mt-1 pl-6 text-[11px] text-muted-foreground">
                {ACTION_LABEL[r.action] ?? r.action}{r.expected_impact ? ` · expected ${r.expected_impact}` : ""}{ins?.n != null ? ` · n=${ins.n}` : ""}{ins?.confidence != null ? ` · ${ins.confidence} confidence` : ""}{ins?.directional ? " · early signal" : ""}
              </p>
              {canCreate && (
                <div className="mt-2 flex flex-wrap gap-1.5 pl-6">
                  <Button size="xs" onClick={() => decide.mutate({ id: r.id, status: "accepted" })} disabled={decide.isPending}><Check /> Accept</Button>
                  <Popover>
                    <PopoverTrigger asChild><Button size="xs" variant="outline"><X /> Dismiss</Button></PopoverTrigger>
                    <PopoverContent className="w-72" align="start">
                      <form className="space-y-2" onSubmit={(e) => { e.preventDefault(); decide.mutate({ id: r.id, status: "rejected", reason: reason.trim() || undefined }); }}>
                        <p className="text-xs text-muted-foreground">Why? (helps the analyst learn)</p>
                        <Input autoFocus value={reason} onChange={(e) => setReason(e.target.value)} placeholder="Not relevant this quarter" />
                        <Button size="xs" type="submit">Dismiss</Button>
                      </form>
                    </PopoverContent>
                  </Popover>
                  <Button size="xs" variant="ghost" onClick={() => setEvidence(r)}><HelpCircle /> Evidence</Button>
                </div>
              )}
            </li>
          );
        })}
      </ul>
      <Sheet open={!!evidence} onOpenChange={(o) => !o && setEvidence(null)}>
        <SheetContent className="w-full overflow-y-auto sm:max-w-md">
          <SheetHeader><SheetTitle className="flex items-center gap-2"><Sparkles className="h-4 w-4 text-ai" /> How we know</SheetTitle><SheetDescription>performance_analyst · numbers come from tool results, not model text</SheetDescription></SheetHeader>
          {evidence && <EvidenceBody rec={evidence} insight={insightOf(evidence)} runHref={(id) => ws(`command-center/${id}`)} />}
        </SheetContent>
      </Sheet>
    </>
  );
}

function EvidenceBody({ rec, insight, runHref }: { rec: Recommendation; insight: Insight | null; runHref: (id: string) => string }) {
  const ev = insight?.evidence ?? {};
  return (
    <div className="space-y-3 px-4 pb-6 text-sm">
      {insight ? (
        <>
          <p className="font-medium">{insight.statement}</p>
          <dl className="grid grid-cols-[auto_1fr] gap-x-3 gap-y-1 text-xs">
            {insight.metric && <><dt className="text-muted-foreground">Metric</dt><dd>{insight.metric}</dd></>}
            {insight.effect_size != null && <><dt className="text-muted-foreground">Effect size</dt><dd>{insight.effect_size}</dd></>}
            {insight.n != null && <><dt className="text-muted-foreground">Sample</dt><dd>n = {insight.n}</dd></>}
            {insight.confidence != null && <><dt className="text-muted-foreground">Confidence</dt><dd>{String(insight.confidence)}{insight.directional ? " (directional)" : ""}</dd></>}
            {(insight.period_start || insight.period_end) && <><dt className="text-muted-foreground">Data window</dt><dd>{fmtDate(insight.period_start)} – {fmtDate(insight.period_end)}</dd></>}
            {coverageText(insight.coverage) && <><dt className="text-muted-foreground">Coverage</dt><dd>{coverageText(insight.coverage)}</dd></>}
            {(insight.excluded_platforms ?? []).length > 0 && <><dt className="text-muted-foreground">Excluded</dt><dd>{insight.excluded_platforms?.join(", ")}</dd></>}
          </dl>
          {Object.keys(ev).length > 0 && <details><summary className="cursor-pointer text-xs text-muted-foreground">Evidence data</summary><pre className="mt-1 max-h-64 overflow-auto rounded bg-muted p-2 text-[11px]">{JSON.stringify(ev, null, 2)}</pre></details>}
          {insight.ai_run_id && <Link className="text-xs text-primary hover:underline" href={runHref(insight.ai_run_id)}>Open analysis run ↗</Link>}
        </>
      ) : <p className="text-muted-foreground">Evidence details weren’t included for this recommendation.</p>}
      {rec.rationale && <p className="text-xs"><span className="text-muted-foreground">Rationale: </span>{rec.rationale}</p>}
      {rec.target && Object.keys(rec.target).length > 0 && <pre className="max-h-40 overflow-auto rounded bg-muted p-2 text-[11px]">{JSON.stringify(rec.target, null, 2)}</pre>}
    </div>
  );
}

export function RecommendationsWidget({ brandId, limit = 3 }: { brandId: string | null; limit?: number }) {
  const q = useRecommendations(brandId);
  if (!brandId) return <p className="text-sm text-muted-foreground">Select a brand.</p>;
  if (q.isLoading) return <SkeletonRows rows={3} />;
  if (q.error) return <QueryError error={q.error} onRetry={() => q.refetch()} notAvailableText="Insights aren't available yet — they appear after analytics sync and the weekly analysis." />;
  return <RecommendationList brandId={brandId} recommendations={q.data?.recommendations ?? []} insights={q.data?.insights ?? []} limit={limit} emptyText="No recommendations yet. They appear after the AI analyses your published posts." />;
}

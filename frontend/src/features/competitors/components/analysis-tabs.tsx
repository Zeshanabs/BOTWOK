"use client";
/** AI-derived tabs (✦ competitor_intel): Pillars & Hooks, Visual & Tone, Gaps & Opportunities. Data comes from
 *  per-post `analysis` and the latest competitor report; nothing is imputed when absent. */
import { useRouter } from "next/navigation";
import { toast } from "sonner";
import { Lightbulb, Sparkles } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { EmptyState } from "@/components/shared/empty-state";
import { ListSkeleton, QueryError, errorMessage } from "@/components/shared/async-states";
import { fmtDate, truncate } from "@/lib/formatters";
import { useCan } from "@/lib/permissions";
import { useSession } from "@/stores/session";
import { useActiveBrandId } from "@/features/brand/hooks";
import { useGenerateIdeas } from "@/features/ideas/hooks";
import { useCompetitorPosts, useCompetitorReports } from "../hooks";
import type { CompetitorPost, CompetitorReport, ReportItem } from "../types";

function str(v: unknown): string | null {
  if (typeof v === "string" && v.trim()) return v.trim();
  return null;
}
function strList(v: unknown): string[] {
  if (Array.isArray(v)) return v.map((x) => (typeof x === "string" ? x : str((x as Record<string, unknown>)?.name) ?? str((x as Record<string, unknown>)?.title) ?? "")).filter(Boolean);
  const s = str(v);
  return s ? [s] : [];
}
function itemTitle(i: ReportItem | string): string {
  return typeof i === "string" ? i : i.title ?? i.topic ?? i.name ?? "Untitled";
}
function itemDetail(i: ReportItem | string): string | undefined {
  return typeof i === "string" ? undefined : i.description ?? i.detail;
}
function latestReport(reports: CompetitorReport[] | undefined): CompetitorReport | undefined {
  return [...(reports ?? [])].sort((a, b) => String(b.created_at ?? "").localeCompare(String(a.created_at ?? ""))).find((r) => r.content);
}

function Provenance({ posts, report }: { posts?: number; report?: CompetitorReport }) {
  return (
    <p className="text-xs text-muted-foreground">
      <Sparkles className="mr-1 inline h-3 w-3 text-ai" /> competitor_intel{posts != null ? ` · ${posts} posts analyzed` : ""}{report ? ` · report ${fmtDate(report.created_at)}` : ""}
    </p>
  );
}

function useAnalysisData(competitorId: string) {
  const posts = useCompetitorPosts(competitorId);
  const reports = useCompetitorReports(competitorId);
  return { posts, reports, analyzed: (posts.data ?? []).filter((p) => p.analysis && Object.keys(p.analysis).length), report: latestReport(reports.data) };
}

function countBy(posts: CompetitorPost[], key: string): [string, number][] {
  const m = new Map<string, number>();
  for (const p of posts) for (const v of strList(p.analysis?.[key])) m.set(v, (m.get(v) ?? 0) + 1);
  return Array.from(m.entries()).sort((a, b) => b[1] - a[1]);
}

export function PillarsHooksTab({ competitorId, onGenerateReport }: { competitorId: string; onGenerateReport: () => void }) {
  const { posts, reports, analyzed, report } = useAnalysisData(competitorId);
  if (posts.isLoading || reports.isLoading) return <ListSkeleton rows={4} />;
  if (posts.error) return <QueryError error={posts.error} onRetry={() => posts.refetch()} />;
  const pillars = countBy(analyzed, "pillar");
  const hooks = countBy(analyzed, "hook_type").length ? countBy(analyzed, "hook_type") : countBy(analyzed, "hook");
  const reportPillars = report?.content?.pillars ?? [];
  const reportHooks = report?.content?.hooks ?? [];
  if (!pillars.length && !hooks.length && !reportPillars.length && !reportHooks.length) {
    return <EmptyState icon={Sparkles} title="No analysis yet" description="Pillars and hooks are inferred by competitor_intel from collected posts. Generate a report to analyze them." action={{ label: "Generate report", onClick: onGenerateReport }} />;
  }
  const total = analyzed.length || 1;
  return (
    <div className="space-y-3">
      <Provenance posts={analyzed.length} report={report} />
      <div className="grid gap-4 lg:grid-cols-2">
        <Card>
          <CardHeader><CardTitle className="text-sm">✦ Inferred pillars</CardTitle></CardHeader>
          <CardContent className="space-y-2 text-sm">
            {pillars.map(([name, n]) => (
              <div key={name}>
                <div className="flex justify-between"><span>{name}</span><span className="tabular-nums text-muted-foreground">{Math.round((n / total) * 100)}% · n={n}</span></div>
                <div className="mt-1 h-1.5 rounded-full bg-muted"><div className="h-1.5 rounded-full bg-primary" style={{ width: `${(n / total) * 100}%` }} /></div>
              </div>
            ))}
            {reportPillars.map((p, i) => <div key={i}><p className="font-medium">{itemTitle(p)}{p.share != null && <span className="ml-1 text-xs text-muted-foreground">{Math.round(p.share <= 1 ? p.share * 100 : p.share)}%</span>}</p>{itemDetail(p) && <p className="text-xs text-muted-foreground">{itemDetail(p)}</p>}</div>)}
          </CardContent>
        </Card>
        <Card>
          <CardHeader><CardTitle className="text-sm">✦ Hook patterns</CardTitle></CardHeader>
          <CardContent className="space-y-3 text-sm">
            {hooks.slice(0, 8).map(([h, n]) => {
              const example = analyzed.find((p) => strList(p.analysis?.hook_type).includes(h) || strList(p.analysis?.hook).includes(h));
              return (
                <div key={h}>
                  <p className="font-medium">{h} <span className="text-xs font-normal text-muted-foreground">n={n}</span></p>
                  {example?.text && <p className="text-xs text-muted-foreground">e.g. “{truncate(example.text, 120)}”{example.url && <> · <a className="text-primary hover:underline" href={example.url} target="_blank" rel="noreferrer noopener">post ↗</a></>}</p>}
                </div>
              );
            })}
            {reportHooks.map((h, i) => <div key={i}><p className="font-medium">{itemTitle(h)}</p>{h.examples?.[0] && <p className="text-xs text-muted-foreground">e.g. “{truncate(h.examples[0], 120)}”</p>}</div>)}
          </CardContent>
        </Card>
      </div>
    </div>
  );
}

export function VisualToneTab({ competitorId, onGenerateReport }: { competitorId: string; onGenerateReport: () => void }) {
  const { posts, reports, analyzed, report } = useAnalysisData(competitorId);
  if (posts.isLoading || reports.isLoading) return <ListSkeleton rows={4} />;
  if (posts.error) return <QueryError error={posts.error} onRetry={() => posts.refetch()} />;
  const tones = countBy(analyzed, "tone");
  const styles = countBy(analyzed, "visual_style").length ? countBy(analyzed, "visual_style") : countBy(analyzed, "image_style");
  const palette = Array.from(new Set([...(report?.content?.palettes ?? []), ...analyzed.flatMap((p) => strList(p.analysis?.palette))])).filter((c) => /^#[0-9a-f]{3,8}$/i.test(c)).slice(0, 12);
  const reportTone = strList(report?.content?.tone);
  const reportVisual = strList(report?.content?.visual);
  if (!tones.length && !styles.length && !palette.length && !reportTone.length && !reportVisual.length) {
    return <EmptyState icon={Sparkles} title="No visual or tone analysis yet" description="Generate a report to have competitor_intel describe palettes, image styles and tone with quotes." action={{ label: "Generate report", onClick: onGenerateReport }} />;
  }
  return (
    <div className="space-y-3">
      <Provenance posts={analyzed.length} report={report} />
      <div className="grid gap-4 lg:grid-cols-2">
        <Card>
          <CardHeader><CardTitle className="text-sm">✦ Tone</CardTitle></CardHeader>
          <CardContent className="space-y-2 text-sm">
            {tones.map(([t, n]) => {
              const quote = analyzed.find((p) => strList(p.analysis?.tone).includes(t))?.text;
              return <div key={t}><p className="font-medium">{t} <span className="text-xs font-normal text-muted-foreground">n={n}</span></p>{quote && <p className="text-xs italic text-muted-foreground">“{truncate(quote, 110)}”</p>}</div>;
            })}
            {reportTone.map((t) => <p key={t}>{t}</p>)}
          </CardContent>
        </Card>
        <Card>
          <CardHeader><CardTitle className="text-sm">✦ Visual identity</CardTitle></CardHeader>
          <CardContent className="space-y-3 text-sm">
            {palette.length > 0 && (
              <div className="flex flex-wrap gap-2">{palette.map((c) => <span key={c} className="flex items-center gap-1 text-xs"><span className="h-5 w-5 rounded border" style={{ background: c }} aria-hidden />{c}</span>)}</div>
            )}
            {styles.map(([s, n]) => <p key={s}>{s} <span className="text-xs text-muted-foreground">n={n}</span></p>)}
            {reportVisual.map((v) => <p key={v}>{v}</p>)}
          </CardContent>
        </Card>
      </div>
    </div>
  );
}

export function GapsTab({ competitorId, onGenerateReport }: { competitorId: string; onGenerateReport: () => void }) {
  const router = useRouter();
  const slug = useSession((s) => s.workspaceSlug);
  const brandId = useActiveBrandId();
  const can = useCan();
  const reports = useCompetitorReports(competitorId);
  const generate = useGenerateIdeas();
  if (reports.isLoading) return <ListSkeleton rows={4} />;
  if (reports.error) return <QueryError error={reports.error} onRetry={() => reports.refetch()} title="Couldn't load gap analysis" />;
  const report = latestReport(reports.data);
  const gaps = report?.content?.gaps ?? [];
  const opps = report?.content?.opportunities ?? [];
  if (!gaps.length && !opps.length) {
    return <EmptyState icon={Lightbulb} title="No gaps analyzed yet" description="A competitor report compares their topics and formats with yours and lists gaps and opportunities." action={{ label: "Generate report", onClick: onGenerateReport }} />;
  }
  function createIdeas(item: ReportItem) {
    if (!brandId) { toast.error("Select a brand first"); return; }
    generate.mutate(
      { brand_id: brandId, count: 5, from: { report_id: report?.report_id ?? report?.id, prompt: `${itemTitle(item)}${itemDetail(item) ? ` — ${itemDetail(item)}` : ""}` } },
      { onSuccess: (d) => router.push(`/w/${slug}/ideas?run=${d.run_id}`), onError: (e) => toast.error(errorMessage(e)) },
    );
  }
  const section = (title: string, items: ReportItem[]) => items.length > 0 && (
    <Card>
      <CardHeader><CardTitle className="text-sm">{title}</CardTitle></CardHeader>
      <CardContent>
        <ul className="space-y-3">
          {items.map((g, i) => (
            <li key={i} className="flex items-start gap-3">
              <div className="min-w-0 flex-1"><p className="text-sm font-medium">{itemTitle(g)}</p>{itemDetail(g) && <p className="text-xs text-muted-foreground">{itemDetail(g)}</p>}</div>
              {can.create && <Button size="xs" variant="outline" disabled={generate.isPending} onClick={() => createIdeas(g)}><Lightbulb className="h-3 w-3" /> Create ideas</Button>}
            </li>
          ))}
        </ul>
      </CardContent>
    </Card>
  );
  return (
    <div className="space-y-3">
      <Provenance report={report} />
      <div className="grid gap-4 lg:grid-cols-2">{section("✦ Gaps — they cover, you don't", gaps)}{section("✦ Opportunities", opps)}</div>
    </div>
  );
}

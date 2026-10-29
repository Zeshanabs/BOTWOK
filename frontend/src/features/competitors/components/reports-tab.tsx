"use client";
import { useState } from "react";
import Link from "next/link";
import { useQueryClient } from "@tanstack/react-query";
import { toast } from "sonner";
import { FileText, Plus } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Checkbox } from "@/components/ui/checkbox";
import { Dialog, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle } from "@/components/ui/dialog";
import { Label } from "@/components/ui/label";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { StatusChip } from "@/components/shared/status-chip";
import { EmptyState } from "@/components/shared/empty-state";
import { FormError } from "@/components/shared/form-errors";
import { ListSkeleton, QueryError } from "@/components/shared/async-states";
import { fmtDate, humanize } from "@/lib/formatters";
import { useCan } from "@/lib/permissions";
import { useSession } from "@/stores/session";
import { RunProgress } from "@/features/ai/components/run-progress";
import { competitorKeys, useCompetitorMutations, useCompetitorReports } from "../hooks";

const SECTIONS = [
  { id: "overview", label: "Overview & cadence" }, { id: "content", label: "Content & formats" }, { id: "pillars_hooks", label: "Pillars & hooks" },
  { id: "visual_tone", label: "Visual & tone" }, { id: "gaps", label: "Gaps & opportunities" }, { id: "website", label: "Website & blog" }, { id: "news", label: "News" },
];

export function GenerateReportDialog({ open, onOpenChange, competitorId }: { open: boolean; onOpenChange: (o: boolean) => void; competitorId: string }) {
  const qc = useQueryClient();
  const { createReport } = useCompetitorMutations();
  const [period, setPeriod] = useState("30d");
  const [sections, setSections] = useState<string[]>(SECTIONS.map((s) => s.id));
  const [runId, setRunId] = useState<string | null>(null);

  function close(o: boolean) { if (!o) { setRunId(null); createReport.reset(); } onOpenChange(o); }

  return (
    <Dialog open={open} onOpenChange={close}>
      <DialogContent>
        <DialogHeader>
          <DialogTitle>✦ Generate competitor report</DialogTitle>
          <DialogDescription>competitor_intel analyzes stored posts, snapshots and sources; report composes the result. Engagement deltas are only shown where both sides have comparable official data.</DialogDescription>
        </DialogHeader>
        {runId ? (
          <RunProgress runId={runId} title="Report run" onFinished={() => qc.invalidateQueries({ queryKey: competitorKeys.reports(competitorId) })} />
        ) : (
          <div className="space-y-4">
            <div className="space-y-1">
              <Label htmlFor="rep-period">Period</Label>
              <Select value={period} onValueChange={setPeriod}>
                <SelectTrigger id="rep-period" className="w-full"><SelectValue /></SelectTrigger>
                <SelectContent><SelectItem value="7d">Last 7 days</SelectItem><SelectItem value="30d">Last 30 days</SelectItem><SelectItem value="90d">Last 90 days</SelectItem></SelectContent>
              </Select>
            </div>
            <fieldset className="space-y-2">
              <legend className="text-sm font-medium">Sections</legend>
              <div className="grid grid-cols-2 gap-2">
                {SECTIONS.map((s) => (
                  <label key={s.id} className="flex items-center gap-2 text-sm">
                    <Checkbox checked={sections.includes(s.id)} onCheckedChange={(c) => setSections((cur) => (c ? [...cur, s.id] : cur.filter((x) => x !== s.id)))} />{s.label}
                  </label>
                ))}
              </div>
            </fieldset>
            <FormError error={createReport.error} />
          </div>
        )}
        <DialogFooter>
          <Button variant="outline" onClick={() => close(false)}>{runId ? "Close" : "Cancel"}</Button>
          {!runId && (
            <Button disabled={!sections.length || createReport.isPending}
                    onClick={() => createReport.mutate({ id: competitorId, period, sections }, {
                      onSuccess: (d) => { if (d?.run_id) setRunId(d.run_id); else { toast.success("Report requested"); close(false); } },
                    })}>
              {createReport.isPending ? "Starting…" : "Generate"}
            </Button>
          )}
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}

export function ReportsTab({ competitorId, onGenerate }: { competitorId: string; onGenerate: () => void }) {
  const slug = useSession((s) => s.workspaceSlug);
  const can = useCan();
  const q = useCompetitorReports(competitorId);
  if (q.isLoading) return <ListSkeleton rows={4} />;
  if (q.error) return <QueryError error={q.error} onRetry={() => q.refetch()} title="Couldn't load reports" />;
  const reports = [...(q.data ?? [])].sort((a, b) => String(b.created_at ?? "").localeCompare(String(a.created_at ?? "")));
  return (
    <div className="space-y-3">
      {can.create && <div className="flex justify-end"><Button size="sm" onClick={onGenerate}><Plus className="h-4 w-4" /> Generate</Button></div>}
      {!reports.length ? <EmptyState icon={FileText} title="No reports yet" description="Reports summarize cadence, content, gaps and data coverage with citations." /> : (
        <ul className="divide-y rounded-lg border">
          {reports.map((r) => (
            <li key={r.id} className="flex flex-wrap items-center gap-3 p-3 text-sm">
              <FileText className="h-4 w-4 text-muted-foreground" />
              <div className="min-w-0 flex-1">
                <p className="font-medium">{r.title ?? humanize(r.kind ?? "competitor report")}</p>
                <p className="text-xs text-muted-foreground">{r.period_start ? `${fmtDate(r.period_start)} – ${fmtDate(r.period_end)}` : ""} · created {fmtDate(r.created_at)}</p>
                {r.content?.summary && <p className="mt-1 line-clamp-2 text-xs text-muted-foreground">{r.content.summary}</p>}
              </div>
              {r.status && <StatusChip status={r.status} />}
              {r.ai_run_id && <Link className="text-xs text-primary hover:underline" href={`/w/${slug}/command-center/${r.ai_run_id}`}>Run ↗</Link>}
              {(r.report_id ?? r.id) && <Link className="text-xs text-primary hover:underline" href={`/w/${slug}/reports/${r.report_id ?? r.id}`}>Open</Link>}
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}

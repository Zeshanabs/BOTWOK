"use client";
import { toast } from "sonner";
import { History, RotateCw } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { StatusChip } from "@/components/data/status-chip";
import { EmptyState } from "@/components/data/empty-state";
import { ListSkeleton, QueryError, errorMessage } from "@/components/data/async-states";
import { fmtDate, fmtUsd } from "@/lib/formatters";
import { useCan } from "@/lib/permissions";
import { useResearchRuns, useStartResearch } from "../hooks";
import type { ResearchDepth, ResearchRun, ResearchScope } from "../types";

export function ResearchHistory({ brandId, onOpen, onNew }: { brandId: string | null; onOpen: (id: string) => void; onNew: () => void }) {
  const can = useCan();
  const runs = useResearchRuns(brandId);
  const start = useStartResearch();

  function rerun(r: ResearchRun) {
    start.mutate(
      { query: r.query, scope: (r.scope ?? ["web"]) as ResearchScope[], depth: (r.depth ?? "standard") as ResearchDepth, recency_days: r.recency_days ?? r.params?.recency_days ?? null, brand_id: r.brand_id ?? brandId, competitor_id: r.competitor_id ?? undefined },
      { onSuccess: (d) => { toast.success("Research re-run started"); onOpen(d.run_id ?? d.id ?? ""); }, onError: (e) => toast.error(errorMessage(e)) },
    );
  }

  if (runs.isLoading) return <ListSkeleton rows={6} />;
  if (runs.error) return <QueryError error={runs.error} onRetry={() => runs.refetch()} title="Couldn't load research history" />;
  if (!runs.data?.length) return <EmptyState icon={History} title="No research yet" description="Runs you start appear here with their cost and sources." action={can.create ? { label: "New research run", onClick: onNew } : undefined} />;

  return (
    <>
      <div className="hidden overflow-x-auto rounded-lg border md:block">
        <Table>
          <TableHeader>
            <TableRow><TableHead>Query</TableHead><TableHead>Scope</TableHead><TableHead>Depth</TableHead><TableHead className="text-right">Sources</TableHead><TableHead>Status</TableHead><TableHead className="text-right">Cost</TableHead><TableHead>Date</TableHead><TableHead /></TableRow>
          </TableHeader>
          <TableBody>
            {runs.data.map((r) => (
              <TableRow key={r.id} className="cursor-pointer" onClick={() => onOpen(r.id)}>
                <TableCell className="max-w-xs truncate font-medium">{r.query}</TableCell>
                <TableCell className="text-xs text-muted-foreground">{(r.scope ?? []).join(", ").replace(/_/g, " ")}</TableCell>
                <TableCell className="text-xs">{r.depth}</TableCell>
                <TableCell className="text-right tabular-nums">{r.source_count ?? r.sources?.length ?? "—"}</TableCell>
                <TableCell><StatusChip status={r.status} /></TableCell>
                <TableCell className="text-right tabular-nums">{fmtUsd(r.cost_usd)}</TableCell>
                <TableCell className="text-xs text-muted-foreground">{fmtDate(r.created_at)}</TableCell>
                <TableCell onClick={(e) => e.stopPropagation()}>
                  {can.create && <Button size="xs" variant="ghost" disabled={start.isPending} onClick={() => rerun(r)} aria-label={`Re-run ${r.query}`}><RotateCw className="h-3 w-3" /> Re-run</Button>}
                </TableCell>
              </TableRow>
            ))}
          </TableBody>
        </Table>
      </div>
      <ul className="space-y-2 md:hidden">
        {runs.data.map((r) => (
          <li key={r.id} className="rounded-lg border p-3">
            <button type="button" className="w-full text-left" onClick={() => onOpen(r.id)}>
              <p className="font-medium">{r.query}</p>
              <div className="mt-1 flex flex-wrap items-center gap-2 text-xs text-muted-foreground"><StatusChip status={r.status} /> {r.source_count ?? 0} sources · {fmtUsd(r.cost_usd)} · {fmtDate(r.created_at)}</div>
            </button>
            {can.create && <Button size="xs" variant="ghost" className="mt-1" onClick={() => rerun(r)}><RotateCw className="h-3 w-3" /> Re-run</Button>}
          </li>
        ))}
      </ul>
    </>
  );
}

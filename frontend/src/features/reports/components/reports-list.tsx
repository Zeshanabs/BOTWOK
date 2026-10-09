"use client";
import { useState } from "react";
import Link from "next/link";
import { useRouter, useSearchParams } from "next/navigation";
import { useQuery } from "@tanstack/react-query";
import { CheckCircle2, FileText, Loader2, Plus, Repeat, XCircle } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { Skeleton } from "@/components/ui/skeleton";
import { PageHeader } from "@/components/data/page-header";
import { StatusChip } from "@/components/data/status-chip";
import { CostPill } from "@/features/common/components/ai-badge";
import { NotAvailable, QueryError } from "@/features/common/components/query-state";
import { useActiveBrand, useBrands, usePermissions, useWorkspacePath } from "@/features/common/hooks";
import { fmtDate, isNotAvailable, relTime, toItems } from "@/features/common/utils";
import { kindLabel, REPORT_KINDS, reportsApi, type ReportKind } from "../api";
import { GenerateReportWizard } from "./generate-wizard";

const ALL = "all";

/** Reports list (doc 24 §18) with filters, scheduled reports, and the generate wizard. */
export function ReportsList() {
  const router = useRouter();
  const params = useSearchParams();
  const ws = useWorkspacePath();
  const { brandId } = useActiveBrand();
  const brands = toItems(useBrands().data);
  const { canCreate } = usePermissions();
  const initial = REPORT_KINDS.find((k) => k.id === params.get("new"))?.id;
  const [wizard, setWizard] = useState<{ open: boolean; kind?: ReportKind }>({ open: !!initial && canCreate, kind: initial });
  const [kind, setKind] = useState(ALL);
  const [brand, setBrand] = useState<string>("current");
  const [status, setStatus] = useState(ALL);
  const f = { kind: kind === ALL ? undefined : kind, brand_id: brand === "current" ? brandId : brand === ALL ? undefined : brand, status: status === ALL ? undefined : status };
  const list = useQuery({
    queryKey: ["reports", "list", f], queryFn: () => reportsApi.list(f), retry: false,
    refetchInterval: (q) => (toItems(q.state.data).some((r) => r.status === "running" || r.status === "queued") ? 4000 : false),
  });
  const items = toItems(list.data);
  const scheduled = items.filter((r) => r.schedule);
  const icon = (s?: string) => (s === "running" || s === "queued" ? <Loader2 className="h-4 w-4 animate-spin text-blue-600" aria-label={s} /> : s === "failed" ? <XCircle className="h-4 w-4 text-red-600" aria-label="failed" /> : <CheckCircle2 className="h-4 w-4 text-emerald-600" aria-label="completed" />);

  return (
    <div>
      <PageHeader title="Reports" description="Composed by the report agent from stored data; every AI section cites its data."
                  actions={canCreate && <Button onClick={() => setWizard({ open: true })}><Plus /> Generate</Button>} />
      <div className="mb-4 flex flex-wrap gap-2">
        <Select value={kind} onValueChange={setKind}><SelectTrigger size="sm" className="w-44" aria-label="Type"><SelectValue /></SelectTrigger>
          <SelectContent><SelectItem value={ALL}>All types</SelectItem>{REPORT_KINDS.map((k) => <SelectItem key={k.id} value={k.id}>{k.label}</SelectItem>)}</SelectContent></Select>
        <Select value={brand} onValueChange={setBrand}><SelectTrigger size="sm" className="w-40" aria-label="Brand"><SelectValue /></SelectTrigger>
          <SelectContent><SelectItem value="current">Current brand</SelectItem><SelectItem value={ALL}>All brands</SelectItem>{brands.map((b) => <SelectItem key={b.id} value={b.id}>{b.name}</SelectItem>)}</SelectContent></Select>
        <Select value={status} onValueChange={setStatus}><SelectTrigger size="sm" className="w-36" aria-label="Status"><SelectValue /></SelectTrigger>
          <SelectContent><SelectItem value={ALL}>Any status</SelectItem><SelectItem value="completed">Completed</SelectItem><SelectItem value="running">Running</SelectItem><SelectItem value="failed">Failed</SelectItem></SelectContent></Select>
      </div>
      {list.isLoading ? <div className="space-y-2">{Array.from({ length: 4 }).map((_, i) => <Skeleton key={i} className="h-14" />)}</div>
        : list.error ? (isNotAvailable(list.error) ? <NotAvailable text="Reports aren't available on this backend yet. You can still prepare one — generation will start once the report service is enabled." /> : <QueryError error={list.error} onRetry={() => list.refetch()} title="Couldn't load reports" />)
        : items.length === 0 ? (
          <div>
            <p className="mb-3 text-sm text-muted-foreground">No reports yet. Pick a type to start:</p>
            <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
              {REPORT_KINDS.map((k) => (
                <button key={k.id} type="button" disabled={!canCreate} onClick={() => setWizard({ open: true, kind: k.id })} className="rounded-xl border p-4 text-left hover:bg-accent disabled:opacity-60">
                  <FileText className="mb-2 h-5 w-5 text-muted-foreground" /><p className="font-medium">{k.label}</p><p className="mt-1 text-xs text-muted-foreground">{k.description}</p>
                </button>
              ))}
            </div>
          </div>
        ) : (
          <div className="grid gap-6 lg:grid-cols-[minmax(0,1fr)_280px]">
            <ul className="space-y-2">
              {items.map((r) => (
                <li key={r.id}>
                  <Link href={ws(`reports/${r.id}`)} className="flex items-center gap-3 rounded-lg border p-3 hover:bg-accent">
                    {icon(r.status)}
                    <div className="min-w-0 flex-1">
                      <p className="truncate font-medium">{r.title}</p>
                      <p className="text-xs text-muted-foreground">{kindLabel(r.kind)}{r.period_start ? ` · ${fmtDate(r.period_start)} – ${fmtDate(r.period_end)}` : ""} · {relTime(r.created_at)}</p>
                      {r.status === "failed" && r.error && <p className="text-xs text-red-600">{r.error}</p>}
                    </div>
                    {r.schedule && <Repeat className="h-4 w-4 text-muted-foreground" aria-label="recurring" />}
                    <CostPill usd={r.cost_usd} />
                    {r.status && r.status !== "completed" && <StatusChip status={r.status} />}
                  </Link>
                </li>
              ))}
            </ul>
            <aside>
              <p className="mb-2 text-xs font-semibold uppercase tracking-wide text-muted-foreground">Scheduled ({scheduled.length})</p>
              {scheduled.length === 0 ? <p className="text-xs text-muted-foreground">No recurring reports.</p> : (
                <ul className="space-y-2 text-sm">{scheduled.map((r) => <li key={r.id} className="rounded-md border p-2"><p className="font-medium">{kindLabel(r.kind)}</p><p className="text-xs text-muted-foreground">{r.schedule?.next_run_at ? `next ${relTime(r.schedule.next_run_at)}` : r.schedule?.rrule}{r.schedule?.timezone ? ` · ${r.schedule.timezone}` : ""}</p>{(r.recipients ?? []).length > 0 && <p className="text-xs text-muted-foreground">→ {r.recipients?.map((x) => x.value).join(", ")}</p>}</li>)}</ul>
              )}
            </aside>
          </div>
        )}
      <GenerateReportWizard key={wizard.open ? `open-${wizard.kind ?? ""}` : "closed"} open={wizard.open} onOpenChange={(o) => setWizard((w) => ({ ...w, open: o }))} initialKind={wizard.kind}
                            onCreated={(id) => { if (id) router.push(ws(`reports/${id}`)); }} />
    </div>
  );
}

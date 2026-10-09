"use client";
/** Admin / Debug (owner/admin): health, jobs, events tail, costs. */
import { useState } from "react";
import { toast } from "sonner";
import { CheckCircle2, XCircle } from "lucide-react";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { StatusChip } from "@/components/shared/status-chip";
import { NotAvailable, ListSkeleton, QueryError, errorMessage } from "@/components/shared/async-states";
import { fmtDateTime, fmtRelative, fmtUsd, humanize, truncate } from "@/lib/formatters";
import { useCan } from "@/lib/permissions";
import { useCosts, useEvents, useHealth, useJobs, useRetryJob } from "../hooks";

export function AdminPanel() {
  const can = useCan();
  const [jobStatus, setJobStatus] = useState("all");
  const health = useHealth(can.manage);
  const jobs = useJobs(can.manage, jobStatus);
  const events = useEvents(can.manage);
  const costs = useCosts(can.manage);
  const retry = useRetryJob();
  if (!can.manage) return null;

  return (
    <div className="space-y-6">
      <section>
        <div className="mb-2 flex items-center gap-2"><h3 className="text-sm font-semibold">Health</h3>{health.data && <StatusChip status={health.data.status === "ok" ? "active" : health.data.status === "down" ? "failed" : "paused"} />}</div>
        {health.isLoading ? <ListSkeleton rows={1} rowClassName="h-24" /> : health.error ? <QueryError error={health.error} onRetry={() => health.refetch()} title="Health check failed" /> : (
          <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3">
            {Object.entries(health.data?.checks ?? {}).map(([name, c]) => (
              <Card key={name} className="gap-1 py-3">
                <CardContent className="space-y-1 px-4 text-sm">
                  <p className="flex items-center gap-1 font-medium">{c.ok ? <CheckCircle2 className="h-4 w-4 text-success" /> : <XCircle className="h-4 w-4 text-destructive" />}{humanize(name)}</p>
                  <p className="text-xs text-muted-foreground">{c.ok ? "OK" : "Problem"}{c.latency_ms != null ? ` · ${c.latency_ms} ms` : ""}</p>
                  {c.detail && <p className="text-xs">{c.detail}</p>}
                </CardContent>
              </Card>
            ))}
          </div>
        )}
        {health.dataUpdatedAt > 0 && <p className="mt-1 text-xs text-muted-foreground">Checked {fmtRelative(new Date(health.dataUpdatedAt))}</p>}
      </section>

      <section>
        <div className="mb-2 flex items-center justify-between gap-2">
          <h3 className="text-sm font-semibold">Jobs</h3>
          <Select value={jobStatus} onValueChange={setJobStatus}>
            <SelectTrigger size="sm" aria-label="Job status"><SelectValue /></SelectTrigger>
            <SelectContent>{["all", "todo", "doing", "succeeded", "failed", "cancelled"].map((s) => <SelectItem key={s} value={s}>{s === "all" ? "All statuses" : s}</SelectItem>)}</SelectContent>
          </Select>
        </div>
        {jobs.isLoading ? <ListSkeleton rows={4} /> : jobs.error ? <QueryError error={jobs.error} onRetry={() => jobs.refetch()} title="Couldn't load jobs" /> : jobs.data?.available === false ? (
          <NotAvailable title="Queue not readable" description={jobs.data.detail ?? "The job queue isn't reachable from the API."} />
        ) : !(jobs.data?.items ?? []).length ? <p className="text-sm text-muted-foreground">No jobs.</p> : (
          <div className="overflow-x-auto rounded-lg border">
            <Table>
              <TableHeader><TableRow><TableHead>ID</TableHead><TableHead>Task</TableHead><TableHead>Queue</TableHead><TableHead>Status</TableHead><TableHead className="text-right">Attempts</TableHead><TableHead>Scheduled</TableHead><TableHead /></TableRow></TableHeader>
              <TableBody>
                {(jobs.data?.items ?? []).map((j) => (
                  <TableRow key={j.id}>
                    <TableCell className="font-mono text-xs">{j.id}</TableCell>
                    <TableCell className="font-mono text-xs">{j.task_name}</TableCell>
                    <TableCell className="text-xs">{j.queue_name}</TableCell>
                    <TableCell><StatusChip status={j.status === "doing" ? "running" : j.status === "todo" ? "pending" : j.status} /></TableCell>
                    <TableCell className="text-right tabular-nums">{j.attempts ?? 0}</TableCell>
                    <TableCell className="text-xs text-muted-foreground">{fmtDateTime(j.scheduled_at)}</TableCell>
                    <TableCell>{j.status === "failed" && <Button size="xs" variant="outline" disabled={retry.isPending} onClick={() => retry.mutate(j.id, { onSuccess: () => toast.success("Job re-queued"), onError: (e) => toast.error(errorMessage(e)) })}>Retry</Button>}</TableCell>
                  </TableRow>
                ))}
              </TableBody>
            </Table>
          </div>
        )}
      </section>

      <section>
        <h3 className="mb-2 text-sm font-semibold">Events (outbox tail)</h3>
        {events.isLoading ? <ListSkeleton rows={4} /> : events.error ? <QueryError error={events.error} onRetry={() => events.refetch()} title="Couldn't load events" /> : !(events.data ?? []).length ? <p className="text-sm text-muted-foreground">No events yet.</p> : (
          <ul className="max-h-80 divide-y overflow-y-auto rounded-lg border font-mono text-xs">
            {(events.data ?? []).map((e) => (
              <li key={e.id} className="grid grid-cols-[9rem_14rem_1fr] gap-2 p-2">
                <span className="text-muted-foreground">{fmtDateTime(e.occurred_at)}</span>
                <span className="font-medium">{e.name}</span>
                <span className="truncate text-muted-foreground" title={JSON.stringify(e.payload)}>{truncate(JSON.stringify(e.payload ?? {}), 140)}{!e.published_at && " · unpublished"}</span>
              </li>
            ))}
          </ul>
        )}
      </section>

      <section>
        <h3 className="mb-2 text-sm font-semibold">Costs</h3>
        {costs.isLoading ? <ListSkeleton rows={2} /> : costs.error ? <QueryError error={costs.error} onRetry={() => costs.refetch()} title="Couldn't load costs" /> : costs.data ? (
          <Card className="py-4"><CardHeader className="px-4"><CardTitle className="text-sm">{fmtUsd(costs.data.total_cost_usd, 2)} <span className="font-normal text-muted-foreground">· {costs.data.period} ({fmtDateTime(costs.data.start)} – {fmtDateTime(costs.data.end)})</span></CardTitle></CardHeader>
            <CardContent className="px-4">
              <ul className="space-y-1 text-sm">{costs.data.by_kind.map((k) => <li key={k.kind} className="flex justify-between"><span>{humanize(k.kind)} <span className="text-xs text-muted-foreground">({k.quantity.toLocaleString()})</span></span><span className="tabular-nums">{fmtUsd(k.cost_usd)}</span></li>)}</ul>
            </CardContent></Card>
        ) : null}
      </section>
    </div>
  );
}

"use client";
/** Cost dashboard: GET /ai/usage grouped by day, agent and model. */
import { useState } from "react";
import { Bar, BarChart, CartesianGrid, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { ListSkeleton, QueryError } from "@/components/shared/async-states";
import { fmtCompact, fmtDate, fmtUsd, toNumber } from "@/lib/formatters";
import { useUsage } from "../hooks";
import { usageKey, usageTokens, type UsageRow } from "../types";

const tooltipStyle = { background: "var(--popover)", border: "1px solid var(--border)", borderRadius: 8, color: "var(--popover-foreground)", fontSize: 12 };

function range(days: number): { from: string; to: string } {
  const to = new Date();
  const from = new Date(to.getTime() - days * 86_400_000);
  return { from: from.toISOString().slice(0, 10), to: to.toISOString().slice(0, 10) };
}

function ByChart({ rows, label, xFormatter }: { rows: UsageRow[]; label: string; xFormatter?: (v: string) => string }) {
  const data = rows.map((r) => ({ key: usageKey(r), cost: toNumber(r.cost_usd) ?? 0 }));
  if (!data.length) return <p className="py-10 text-center text-sm text-muted-foreground">No usage in this period.</p>;
  return (
    <ResponsiveContainer width="100%" height="100%">
      <BarChart data={data} margin={{ left: -8, right: 8 }}>
        <CartesianGrid strokeDasharray="3 3" stroke="var(--border)" vertical={false} />
        <XAxis dataKey="key" fontSize={11} stroke="var(--muted-foreground)" tickFormatter={xFormatter} interval="preserveStartEnd" />
        <YAxis fontSize={11} stroke="var(--muted-foreground)" tickFormatter={(v: number) => `$${v}`} />
        <Tooltip contentStyle={tooltipStyle} formatter={(v) => [fmtUsd(v, 4), label]} labelFormatter={(l) => (xFormatter ? xFormatter(String(l)) : String(l))} />
        <Bar dataKey="cost" fill="var(--chart-1)" radius={[4, 4, 0, 0]} />
      </BarChart>
    </ResponsiveContainer>
  );
}

export function UsageTab() {
  const [days, setDays] = useState("30");
  const [r, setR] = useState(() => range(30));
  const byDay = useUsage(r.from, r.to, "day");
  const byAgent = useUsage(r.from, r.to, "agent");
  const byModel = useUsage(r.from, r.to, "model");
  const total = byDay.data?.total ?? (byDay.data?.rows ?? []).reduce((s, x) => s + (toNumber(x.cost_usd) ?? 0), 0);

  if (byDay.error) return <QueryError error={byDay.error} onRetry={() => byDay.refetch()} title="Couldn't load usage" notAvailableText="The cost dashboard isn't available on this install yet." />;

  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <p className="text-sm">Total <span className="text-lg font-semibold tabular-nums">{byDay.isLoading ? "…" : fmtUsd(total, 2)}</span> <span className="text-muted-foreground">from {fmtDate(r.from)} to {fmtDate(r.to)}</span></p>
        <Select value={days} onValueChange={(v) => { setDays(v); setR(range(Number(v))); }}>
          <SelectTrigger size="sm" aria-label="Period"><SelectValue /></SelectTrigger>
          <SelectContent><SelectItem value="7">Last 7 days</SelectItem><SelectItem value="30">Last 30 days</SelectItem><SelectItem value="90">Last 90 days</SelectItem></SelectContent>
        </Select>
      </div>
      <Card>
        <CardHeader><CardTitle className="text-sm">Cost by day</CardTitle></CardHeader>
        <CardContent className="h-60">{byDay.isLoading ? <ListSkeleton rows={1} rowClassName="h-52" /> : <ByChart rows={byDay.data?.rows ?? []} label="Cost" xFormatter={(v) => fmtDate(v, "MMM d")} />}</CardContent>
      </Card>
      <div className="grid gap-4 lg:grid-cols-2">
        <Card>
          <CardHeader><CardTitle className="text-sm">By agent</CardTitle></CardHeader>
          <CardContent>
            {byAgent.isLoading ? <ListSkeleton rows={5} rowClassName="h-8" /> : byAgent.error ? <QueryError error={byAgent.error} onRetry={() => byAgent.refetch()} /> : (
              <div className="overflow-x-auto">
                <Table>
                  <TableHeader><TableRow><TableHead>Agent</TableHead><TableHead className="text-right">Runs</TableHead><TableHead className="text-right">Tokens</TableHead><TableHead className="text-right">Cost</TableHead><TableHead className="text-right">Avg/run</TableHead><TableHead className="text-right">Failures</TableHead></TableRow></TableHeader>
                  <TableBody>
                    {(byAgent.data?.rows ?? []).map((x) => {
                      const runs = x.runs ?? x.calls ?? 0;
                      const cost = toNumber(x.cost_usd) ?? 0;
                      return (
                        <TableRow key={usageKey(x)}>
                          <TableCell className="font-mono text-xs">{usageKey(x)}</TableCell>
                          <TableCell className="text-right tabular-nums">{runs || "—"}</TableCell>
                          <TableCell className="text-right tabular-nums">{fmtCompact(usageTokens(x))}</TableCell>
                          <TableCell className="text-right tabular-nums">{fmtUsd(cost)}</TableCell>
                          <TableCell className="text-right tabular-nums">{runs ? fmtUsd(cost / runs, 4) : "—"}</TableCell>
                          <TableCell className="text-right tabular-nums">{x.failures ?? "—"}</TableCell>
                        </TableRow>
                      );
                    })}
                  </TableBody>
                </Table>
                {!(byAgent.data?.rows ?? []).length && <p className="p-4 text-center text-sm text-muted-foreground">No usage in this period.</p>}
              </div>
            )}
          </CardContent>
        </Card>
        <Card>
          <CardHeader><CardTitle className="text-sm">By model</CardTitle></CardHeader>
          <CardContent className="h-64">{byModel.isLoading ? <ListSkeleton rows={1} rowClassName="h-56" /> : byModel.error ? <QueryError error={byModel.error} onRetry={() => byModel.refetch()} /> : <ByChart rows={byModel.data?.rows ?? []} label="Cost" />}</CardContent>
        </Card>
      </div>
      <p className="text-xs text-muted-foreground">Costs come from the usage ledger (provider list prices at call time); Admin › Costs reconciles with this.</p>
    </div>
  );
}

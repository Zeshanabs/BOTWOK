"use client";
import { useState } from "react";
import Link from "next/link";
import { usePathname, useRouter, useSearchParams } from "next/navigation";
import { Legend, PolarAngleAxis, PolarGrid, Radar, RadarChart, ResponsiveContainer, Tooltip } from "recharts";
import { ArrowLeft, Users } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Checkbox } from "@/components/ui/checkbox";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { PageHeader } from "@/components/shared/page-header";
import { EmptyState } from "@/components/shared/empty-state";
import { AvailabilityBadge } from "@/components/shared/availability-badge";
import { ListSkeleton, QueryError } from "@/components/shared/async-states";
import { humanize, toNumber } from "@/lib/formatters";
import { useSession } from "@/stores/session";
import { useActiveBrandId } from "@/features/brand/hooks";
import { useCompare, useCompetitors } from "../hooks";
import type { CompareResponse } from "../types";

const CHART = ["var(--chart-1)", "var(--chart-2)", "var(--chart-3)", "var(--chart-4)", "var(--chart-5)"];

function colName(c: CompareResponse["columns"][number], i: number): string {
  if (typeof c === "string") return c;
  return c.name ?? (c.kind === "brand" ? "You" : `Column ${i + 1}`);
}

function Cell({ value, availability }: { value: number | string | null; availability?: string | null }) {
  if (value === null || value === undefined || availability === "not_collected") {
    return <AvailabilityBadge availability="not_collected" />;
  }
  const n = toNumber(value);
  return (
    <div className="flex flex-col items-start gap-1">
      <span className="tabular-nums">{n !== null ? n.toLocaleString(undefined, { maximumFractionDigits: 2 }) : String(value)}</span>
      {availability && <AvailabilityBadge availability={availability} short />}
    </div>
  );
}

export function CompareView() {
  const router = useRouter();
  const pathname = usePathname();
  const sp = useSearchParams();
  const slug = useSession((s) => s.workspaceSlug);
  const brandId = useActiveBrandId();
  const ids = (sp.get("ids") ?? "").split(",").filter(Boolean);
  const [period, setPeriod] = useState("90d");
  const [picked, setPicked] = useState<string[]>(ids);
  const competitors = useCompetitors(brandId);
  const cmp = useCompare(ids, period);

  const picker = (
    <Card>
      <CardHeader><CardTitle className="text-sm">Choose 2–4 competitors</CardTitle></CardHeader>
      <CardContent className="space-y-2">
        {competitors.isLoading ? <ListSkeleton rows={3} rowClassName="h-8" /> : !(competitors.data ?? []).length ? (
          <EmptyState icon={Users} title="No competitors yet" description="Add competitors first, then compare them here." />
        ) : (
          <>
            <div className="grid gap-2 sm:grid-cols-2 lg:grid-cols-3">
              {(competitors.data ?? []).map((c) => (
                <label key={c.id} className="flex items-center gap-2 text-sm">
                  <Checkbox checked={picked.includes(c.id)} onCheckedChange={(v) => setPicked((p) => (v ? [...p, c.id].slice(-4) : p.filter((x) => x !== c.id)))} />{c.name}
                </label>
              ))}
            </div>
            <Button size="sm" disabled={picked.length < 2} onClick={() => router.replace(`${pathname}?ids=${picked.join(",")}`)}>Compare {picked.length}</Button>
          </>
        )}
      </CardContent>
    </Card>
  );

  const data = cmp.data;
  const columns = data?.columns ?? [];
  const numericRows = (data?.rows ?? []).filter((r) => r.values.some((v) => toNumber(v) !== null));
  const radar = numericRows.map((r) => {
    const max = Math.max(...r.values.map((v) => toNumber(v) ?? 0), 0) || 1;
    const row: Record<string, number | string> = { metric: r.label ?? humanize(r.metric) };
    columns.forEach((c, i) => { const n = toNumber(r.values[i]); row[colName(c, i)] = n === null ? 0 : Math.round((n / max) * 100); });
    return row;
  });

  return (
    <div className="space-y-6">
      <Link href={`/w/${slug}/competitors`} className="inline-flex items-center gap-1 text-xs text-muted-foreground hover:text-foreground"><ArrowLeft className="h-3 w-3" /> Competitors</Link>
      <PageHeader title="Compare competitors" description="You vs up to four competitors. Every cell carries its data source; uncollected values are never shown as 0."
                  actions={
                    <Select value={period} onValueChange={setPeriod}>
                      <SelectTrigger size="sm" aria-label="Period"><SelectValue /></SelectTrigger>
                      <SelectContent><SelectItem value="30d">Last 30 days</SelectItem><SelectItem value="90d">Last 90 days</SelectItem></SelectContent>
                    </Select>
                  } />
      {ids.length < 2 ? picker : cmp.isLoading ? <ListSkeleton rows={6} /> : cmp.error ? (
        <QueryError error={cmp.error} onRetry={() => cmp.refetch()} title="Couldn't compare" />
      ) : !data?.rows?.length ? (
        <EmptyState icon={Users} title="Nothing to compare yet" description="Comparison needs at least one sync per competitor." />
      ) : (
        <>
          <div className="overflow-x-auto rounded-lg border">
            <Table>
              <TableHeader><TableRow><TableHead>Metric</TableHead>{columns.map((c, i) => <TableHead key={i}>{colName(c, i)}</TableHead>)}</TableRow></TableHeader>
              <TableBody>
                {data.rows.map((r) => (
                  <TableRow key={r.metric}>
                    <TableCell className="font-medium">{r.label ?? humanize(r.metric)}</TableCell>
                    {columns.map((_, i) => <TableCell key={i}><Cell value={r.values[i] ?? null} availability={r.availability?.[i]} /></TableCell>)}
                  </TableRow>
                ))}
              </TableBody>
            </Table>
          </div>
          {radar.length >= 3 && (
            <Card>
              <CardHeader><CardTitle className="text-sm">Relative profile (each metric scaled to its maximum)</CardTitle></CardHeader>
              <CardContent className="h-80">
                <ResponsiveContainer width="100%" height="100%">
                  <RadarChart data={radar} outerRadius="75%">
                    <PolarGrid stroke="var(--border)" />
                    <PolarAngleAxis dataKey="metric" fontSize={11} stroke="var(--muted-foreground)" />
                    <Tooltip contentStyle={{ background: "var(--popover)", border: "1px solid var(--border)", borderRadius: 8, fontSize: 12 }} />
                    <Legend wrapperStyle={{ fontSize: 12 }} />
                    {columns.map((c, i) => <Radar key={i} name={colName(c, i)} dataKey={colName(c, i)} stroke={CHART[i % CHART.length]} fill={CHART[i % CHART.length]} fillOpacity={0.15} />)}
                  </RadarChart>
                </ResponsiveContainer>
              </CardContent>
            </Card>
          )}
          <details className="text-sm"><summary className="cursor-pointer text-muted-foreground">Change selection</summary><div className="mt-3">{picker}</div></details>
        </>
      )}
    </div>
  );
}

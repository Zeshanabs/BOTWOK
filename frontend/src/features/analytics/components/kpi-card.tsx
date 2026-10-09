"use client";
import Link from "next/link";
import { ArrowDownRight, ArrowUpRight, Info, Minus } from "lucide-react";
import { Line, LineChart, ResponsiveContainer } from "recharts";
import { Card, CardContent } from "@/components/ui/card";
import { Skeleton } from "@/components/ui/skeleton";
import { Hint } from "@/features/common/components/hint";
import { fmtCompact, fmtPct, toPercent } from "@/features/common/utils";
import { cn } from "@/lib/utils";
import type { Kpi } from "../api";

/** Metric card: value, delta vs previous period (pt for rates), sparkline, basis/coverage footnote. n/a is never 0. */
export function KpiCard({ kpi, label, showDelta = true, emptyAction }: { kpi: Kpi | null; label: string; showDelta?: boolean; emptyAction?: { href: string; label: string } }) {
  if (!kpi || kpi.value == null) {
    return (
      <Card className="gap-1 py-4"><CardContent className="px-4">
        <p className="text-xs font-medium text-muted-foreground">{label}</p>
        <p className="mt-1.5 font-display text-[26px] font-bold leading-none tracking-tight text-muted-foreground/60">{kpi ? "n/a" : "—"}</p>
        <p className="mt-2 text-[11px] text-muted-foreground">{kpi ? (kpi.basis ?? "Not provided by the connected platforms") : "No data yet"}</p>
        {emptyAction && <Link className="mt-1 inline-block text-xs font-medium text-primary hover:underline" href={emptyAction.href}>{emptyAction.label} →</Link>}
      </CardContent></Card>
    );
  }
  const isRate = kpi.unit === "rate";
  const value = isRate ? fmtPct(kpi.value) : fmtCompact(kpi.value);
  let deltaText: string | null = null;
  let dir = 0;
  if (showDelta) {
    if (isRate && kpi.previous != null) {
      const pt = (toPercent(kpi.value) ?? 0) - (toPercent(kpi.previous) ?? 0);
      dir = Math.sign(Math.round(pt * 10));
      deltaText = `${Math.abs(pt).toFixed(1)} pt`;
    } else if (kpi.deltaPct != null) {
      dir = Math.sign(Math.round(kpi.deltaPct));
      deltaText = `${Math.abs(kpi.deltaPct).toFixed(0)}%`;
    }
  }
  const Icon = dir > 0 ? ArrowUpRight : dir < 0 ? ArrowDownRight : Minus;
  const series = kpi.series.filter((p) => p.value != null);
  return (
    <Card className="gap-1 py-4"><CardContent className="px-4">
      <div className="flex items-center gap-1 text-xs font-medium text-muted-foreground">
        {label}
        {(kpi.basis || kpi.coverage) && <Hint label={<span>{kpi.basis}{kpi.basis && kpi.coverage ? " · " : ""}{kpi.coverage}</span>}><button type="button" aria-label={`${label} basis`} className="text-muted-foreground/70 hover:text-foreground"><Info className="h-3 w-3" /></button></Hint>}
      </div>
      <div className="mt-1.5 flex items-end justify-between gap-2">
        <p className="font-display text-[26px] font-bold leading-none tracking-tight tabular-nums">{value}</p>
        {series.length > 1 && (
          <div className="h-9 w-24" aria-hidden>
            <ResponsiveContainer width="100%" height="100%"><LineChart data={series}><Line type="monotone" dataKey="value" stroke="var(--primary)" strokeWidth={1.75} dot={false} isAnimationActive={false} /></LineChart></ResponsiveContainer>
          </div>
        )}
      </div>
      {deltaText && (
        <p className="mt-2 flex items-center gap-1.5 text-xs">
          <span className={cn("inline-flex items-center gap-0.5 rounded-full px-1.5 py-0.5 font-medium tabular-nums", dir > 0 ? "bg-success/12 text-success" : dir < 0 ? "bg-destructive/10 text-destructive" : "bg-muted text-muted-foreground")}>
            <Icon className="h-3 w-3" aria-hidden />{deltaText}
          </span>
          <span className="text-muted-foreground">vs previous</span>
        </p>
      )}
      {(kpi.coverage || kpi.basis) && <p className="mt-1.5 truncate text-[11px] text-muted-foreground" title={[kpi.basis, kpi.coverage].filter(Boolean).join(" · ")}>{kpi.coverage ?? kpi.basis}</p>}
    </CardContent></Card>
  );
}

export function KpiSkeleton() {
  return <Card className="gap-1 py-4"><CardContent className="space-y-2.5 px-4"><Skeleton className="h-3 w-20" /><Skeleton className="h-7 w-24" /><Skeleton className="h-3 w-16" /></CardContent></Card>;
}

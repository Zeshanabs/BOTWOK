"use client";
import { Bar, BarChart, CartesianGrid, Cell, Legend, Line, LineChart, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";
import { Info } from "lucide-react";
import { fmtCompact, fmtPct } from "@/features/common/utils";
import { platformMeta } from "@/lib/platforms";
import { cn } from "@/lib/utils";
import { hourCell, type BreakdownGroup, type SeriesPoint } from "../api";

const AXIS = { fontSize: 11, fill: "var(--muted-foreground)" };
const TOOLTIP = { contentStyle: { background: "var(--popover)", border: "1px solid var(--border)", borderRadius: 8, fontSize: 12, color: "var(--popover-foreground)" } };

export function TimeSeriesChart({ data, unit, showPrevious }: { data: SeriesPoint[]; unit: "count" | "rate"; showPrevious: boolean }) {
  const fmt = (v: number) => (unit === "rate" ? fmtPct(v) : fmtCompact(v));
  return (
    <div className="h-56 w-full" role="img" aria-label="Engagement over time chart">
      <ResponsiveContainer width="100%" height="100%">
        <LineChart data={data} margin={{ top: 8, right: 8, left: -12, bottom: 0 }}>
          <CartesianGrid strokeDasharray="3 3" stroke="var(--border)" vertical={false} />
          <XAxis dataKey="date" tick={AXIS} tickFormatter={(d: string) => d.slice(5)} minTickGap={16} />
          <YAxis tick={AXIS} tickFormatter={fmt} width={48} />
          <Tooltip {...TOOLTIP} formatter={(v) => (typeof v === "number" ? fmt(v) : String(v))} />
          <Legend wrapperStyle={{ fontSize: 11 }} />
          <Line name="This period" type="monotone" dataKey="value" stroke="var(--chart-1)" strokeWidth={2} dot={false} connectNulls={false} />
          {showPrevious && <Line name="Previous" type="monotone" dataKey="previous" stroke="var(--muted-foreground)" strokeDasharray="4 4" strokeWidth={1.5} dot={false} />}
        </LineChart>
      </ResponsiveContainer>
    </div>
  );
}

/** Horizontal bars; groups with null values are listed as n/a (never drawn as 0). */
export function BarBreakdown({ groups, unit = "rate", platformKeys, onSelect, selected }: { groups: BreakdownGroup[]; unit?: "count" | "rate"; platformKeys?: boolean; onSelect?: (key: string) => void; selected?: string | null }) {
  const fmt = (v: number) => (unit === "rate" ? fmtPct(v) : fmtCompact(v));
  const withValue = groups.filter((g) => g.value != null).map((g) => ({ ...g, name: g.label ?? (platformKeys ? platformMeta(g.key).label : g.key) }));
  const na = groups.filter((g) => g.value == null);
  if (!groups.length) return <p className="py-8 text-center text-sm text-muted-foreground">No data for this period.</p>;
  return (
    <div>
      {withValue.length > 0 && (
        <div style={{ height: Math.max(120, withValue.length * 32 + 24) }} className="w-full" role="img" aria-label="Breakdown chart">
          <ResponsiveContainer width="100%" height="100%">
            <BarChart data={withValue} layout="vertical" margin={{ top: 4, right: 40, left: 8, bottom: 4 }}>
              <XAxis type="number" tick={AXIS} tickFormatter={fmt} hide />
              <YAxis type="category" dataKey="name" tick={AXIS} width={110} />
              <Tooltip {...TOOLTIP} formatter={(v) => (typeof v === "number" ? fmt(v) : String(v))} labelFormatter={(l, p) => { const g = p?.[0]?.payload as BreakdownGroup | undefined; return `${String(l)}${g?.n != null ? ` · n=${g.n}` : ""}`; }} />
              <Bar dataKey="value" radius={[0, 4, 4, 0]} label={{ position: "right", fontSize: 11, fill: "var(--foreground)", formatter: (v: unknown) => (typeof v === "number" ? fmt(v) : "") }}
                   onClick={(d: unknown) => { const k = (d as { key?: string } | undefined)?.key; if (k && onSelect) onSelect(k); }} cursor={onSelect ? "pointer" : undefined}>
                {withValue.map((g) => <Cell key={g.key} fill={platformKeys ? platformMeta(g.key).color : "var(--chart-2)"} fillOpacity={selected && selected !== g.key ? 0.35 : 1} />)}
              </Bar>
            </BarChart>
          </ResponsiveContainer>
        </div>
      )}
      {na.length > 0 && (
        <p className="mt-1 flex items-center gap-1 text-xs text-muted-foreground"><Info className="h-3 w-3" /> n/a (not provided by the platform): {na.map((g) => g.label ?? (platformKeys ? platformMeta(g.key).label : g.key)).join(", ")}</p>
      )}
    </div>
  );
}

const DAYS = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"];
/** Weekday × hour heatmap from by=hour groups. */
export function Heatmap({ groups, unit = "rate" }: { groups: BreakdownGroup[]; unit?: "count" | "rate" }) {
  const cells = groups.flatMap((g) => { const c = hourCell(g); return c && g.value != null ? [{ ...c, value: g.value, n: g.n ?? null }] : []; });
  if (!cells.length) return <p className="py-8 text-center text-sm text-muted-foreground">Not enough posts to compute best hours.</p>;
  const hourOnly = cells.every((c) => c.weekday === -1);
  const rows = hourOnly ? ["All days"] : DAYS;
  const max = Math.max(...cells.map((c) => c.value));
  const min = Math.min(...cells.map((c) => c.value));
  const at = (r: number, h: number) => cells.find((c) => (hourOnly ? true : c.weekday === r) && c.hour === h);
  const fmt = (v: number) => (unit === "rate" ? fmtPct(v) : fmtCompact(v));
  return (
    <div className="overflow-x-auto">
      <table className="w-full min-w-[520px] border-separate border-spacing-0.5 text-[10px]" aria-label="Best hours heatmap">
        <thead><tr><th className="w-8" />{Array.from({ length: 24 }, (_, h) => <th key={h} className="font-normal text-muted-foreground">{h % 3 === 0 ? String(h).padStart(2, "0") : ""}</th>)}</tr></thead>
        <tbody>
          {rows.map((d, r) => (
            <tr key={d}>
              <th className="pr-1 text-right font-normal text-muted-foreground">{d}</th>
              {Array.from({ length: 24 }, (_, h) => {
                const c = at(r, h);
                const intensity = c ? (max === min ? 1 : (c.value - min) / (max - min)) : 0;
                return <td key={h} title={c ? `${d} ${String(h).padStart(2, "0")}:00 · ${fmt(c.value)}${c.n != null ? ` · n=${c.n}` : ""}` : `${d} ${h}:00 · no data`}
                           className={cn("h-5 rounded-sm", !c && "bg-muted/50")} style={c ? { background: `color-mix(in oklch, var(--primary) ${Math.round(15 + intensity * 85)}%, transparent)` } : undefined} />;
              })}
            </tr>
          ))}
        </tbody>
      </table>
      <p className="mt-1 text-[11px] text-muted-foreground">Darker = higher engagement rate. Hover a cell for value and sample size.</p>
    </div>
  );
}

/** Weekday strip (Mon–Sun) from a by=weekday breakdown (keys "0".."6", Monday = 0). */
export function WeekdayStrip({ groups, unit = "rate" }: { groups: BreakdownGroup[]; unit?: "count" | "rate" }) {
  const vals = DAYS.map((_, i) => groups.find((g) => String(g.key) === String(i)) ?? null);
  const present = vals.filter((g): g is BreakdownGroup => g != null && g.value != null);
  if (!present.length) return null;
  const max = Math.max(...present.map((g) => g.value as number));
  const min = Math.min(...present.map((g) => g.value as number));
  const fmt = (v: number) => (unit === "rate" ? fmtPct(v) : fmtCompact(v));
  return (
    <div>
      <p className="mb-1 text-[11px] text-muted-foreground">By weekday</p>
      <div className="grid grid-cols-7 gap-1 text-center text-[10px]">
        {DAYS.map((d, i) => {
          const g = vals[i];
          const v = g?.value ?? null;
          const intensity = v == null ? 0 : max === min ? 1 : (v - min) / (max - min);
          return (
            <div key={d} title={v == null ? `${d} · no data` : `${d} · ${fmt(v)}${g?.n != null ? ` · n=${g.n}` : ""}`}>
              <div className={cn("h-6 rounded-sm", v == null && "bg-muted/50")} style={v != null ? { background: `color-mix(in oklch, var(--primary) ${Math.round(15 + intensity * 85)}%, transparent)` } : undefined} />
              <span className="text-muted-foreground">{d}</span>
            </div>
          );
        })}
      </div>
    </div>
  );
}

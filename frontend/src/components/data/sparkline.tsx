"use client";
import { Line, LineChart, ResponsiveContainer, YAxis } from "recharts";
import { cn } from "@/lib/utils";

/** Tiny trend line (no axes). Renders a muted dash when there is no series. */
export function Sparkline({ values, className, color = "var(--chart-2)", label }: { values: number[]; className?: string; color?: string; label?: string }) {
  if (values.length < 2) return <span className={cn("text-xs text-muted-foreground", className)} aria-label="No series">—</span>;
  const data = values.map((v, i) => ({ i, v }));
  return (
    <div className={cn("h-7 w-24", className)} role="img" aria-label={label ?? `Trend line, ${values.length} points, last value ${values[values.length - 1]}`}>
      <ResponsiveContainer width="100%" height="100%">
        <LineChart data={data} margin={{ top: 2, bottom: 2, left: 0, right: 0 }}>
          <YAxis hide domain={["dataMin", "dataMax"]} />
          <Line type="monotone" dataKey="v" stroke={color} strokeWidth={2} dot={false} isAnimationActive={false} />
        </LineChart>
      </ResponsiveContainer>
    </div>
  );
}

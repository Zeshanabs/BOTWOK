import { cn } from "@/lib/utils";

/** Tiny inline trend line (stroke + soft area). Renders a flat placeholder with fewer than two points. */
export function Sparkline({ values, width = 88, height = 28, className, stroke = "currentColor" }: {
  values: number[]; width?: number; height?: number; className?: string; stroke?: string;
}) {
  const pts = values.filter((v) => Number.isFinite(v));
  if (pts.length < 2) {
    return <svg width={width} height={height} className={cn("text-muted-foreground/40", className)} aria-hidden><line x1="2" y1={height / 2} x2={width - 2} y2={height / 2} stroke="currentColor" strokeWidth="1.5" strokeDasharray="3 3" /></svg>;
  }
  const min = Math.min(...pts), max = Math.max(...pts);
  const span = max - min || 1;
  const pad = 2;
  const step = (width - pad * 2) / (pts.length - 1);
  const coords = pts.map((v, i) => [pad + i * step, pad + (1 - (v - min) / span) * (height - pad * 2)] as const);
  const path = coords.map(([x, y], i) => `${i === 0 ? "M" : "L"}${x.toFixed(1)} ${y.toFixed(1)}`).join(" ");
  const area = `${path} L${coords[coords.length - 1][0].toFixed(1)} ${height - pad} L${pad} ${height - pad} Z`;
  const up = pts[pts.length - 1] >= pts[0];
  return (
    <svg width={width} height={height} viewBox={`0 0 ${width} ${height}`} className={cn(up ? "text-success" : "text-destructive", className)} role="img" aria-label={`Trend ${up ? "up" : "down"}`}>
      <path d={area} fill="currentColor" opacity="0.12" />
      <path d={path} fill="none" stroke={stroke} strokeWidth="1.75" strokeLinecap="round" strokeLinejoin="round" />
      <circle cx={coords[coords.length - 1][0]} cy={coords[coords.length - 1][1]} r="2" fill={stroke} />
    </svg>
  );
}

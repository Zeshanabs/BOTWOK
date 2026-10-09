"use client";
import { CheckCircle2, XCircle } from "lucide-react";
import { PlatformIcon } from "@/components/data/platform-icon";
import { platformMeta } from "@/lib/platforms";
import { cn } from "@/lib/utils";
import { budgetFor, type BudgetLine } from "../platform-rules";

const fmt = (n: number) => new Intl.NumberFormat("en-US").format(n);

function Bar({ line }: { line: BudgetLine }) {
  const pct = Math.min(100, (line.used / Math.max(1, line.limit)) * 100);
  const near = !line.over && pct >= 90;
  return (
    <div className="space-y-1">
      <div className="flex items-center justify-between gap-2 text-xs">
        <span className="text-muted-foreground">{line.label}{line.mode === "x_weighted" && " (weighted)"}{line.mode === "utf8_bytes" && " (bytes)"}</span>
        <span className={cn("tabular-nums", line.over ? "font-semibold text-red-600" : near ? "text-amber-600" : "text-muted-foreground")}>
          {fmt(line.used)}/{fmt(line.limit)} {line.over && <span className="sr-only">over limit</span>}
        </span>
      </div>
      <div className="h-1.5 w-full overflow-hidden rounded-full bg-muted" role="meter" aria-valuemin={0} aria-valuemax={line.limit} aria-valuenow={line.used} aria-label={`${line.label} characters`}>
        <div className={cn("h-full rounded-full", line.over ? "bg-red-500" : near ? "bg-amber-500" : "bg-primary")} style={{ width: `${pct}%` }} />
      </div>
    </div>
  );
}

/** Per-platform character budget (doc 23 §23.4) with X URL=23 weighting, UTF-8 bytes for YouTube, segments for threads. */
export function CharacterBudget({ platform, text, segments, metadata, hashtags, className }: {
  platform: string; text: string; segments?: string[]; metadata?: Record<string, unknown>; hashtags?: string[]; className?: string;
}) {
  const lines = budgetFor(platform, text, { segments, metadata, hashtags });
  if (!lines.length) return null;
  return (
    <div className={cn("space-y-2", className)} aria-label={`${platformMeta(platform).label} limits`}>
      {lines.map((l) => <Bar key={l.key} line={l} />)}
    </div>
  );
}

/** Compact one-line totals per platform: "li 1,340/3,000 ✓  x 312/280 ✗". */
export function BudgetSummary({ entries, onSelect }: { entries: { platform: string; text: string; segments?: string[]; metadata?: Record<string, unknown>; hashtags?: string[]; id?: string }[]; onSelect?: (id: string) => void }) {
  return (
    <div className="flex flex-wrap gap-x-4 gap-y-1 text-xs">
      {entries.map((e) => {
        const lines = budgetFor(e.platform, e.text, e);
        const main = lines[0];
        if (!main) return null;
        const over = lines.some((l) => l.over);
        const body = (
          <>
            <PlatformIcon platform={e.platform} size={16} />
            <span className="tabular-nums">{fmt(main.used)}/{fmt(main.limit)}</span>
            {over ? <XCircle className="h-3.5 w-3.5 text-red-600" aria-label="over limit" /> : <CheckCircle2 className="h-3.5 w-3.5 text-emerald-600" aria-label="within limit" />}
          </>
        );
        return e.id && onSelect
          ? <button key={e.id} type="button" onClick={() => onSelect(e.id as string)} className="flex items-center gap-1 rounded px-1 hover:bg-muted">{body}</button>
          : <span key={e.platform + (e.id ?? "")} className="flex items-center gap-1">{body}</span>;
      })}
    </div>
  );
}

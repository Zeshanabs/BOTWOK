"use client";
import { useState } from "react";
import { Play } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Checkbox } from "@/components/ui/checkbox";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { FieldError, FormError, problemFieldErrors } from "@/components/shared/form-errors";
import { BrandSelect } from "@/features/brand/components/brand-select";
import { useCan } from "@/lib/permissions";
import { cn } from "@/lib/utils";
import { useStartResearch } from "../hooks";
import type { ResearchDepth, ResearchRunInput, ResearchScope } from "../types";

const SCOPES: { id: ResearchScope; label: string }[] = [
  { id: "web", label: "Web" }, { id: "news", label: "News" }, { id: "rss", label: "RSS feeds" }, { id: "competitor_sites", label: "Competitor sites" },
];
const DEPTHS: { id: ResearchDepth; label: string; est: string }[] = [
  { id: "quick", label: "Quick", est: "~10 sources" }, { id: "standard", label: "Standard", est: "~40 sources" }, { id: "deep", label: "Deep", est: "~100 sources" },
];
const RECENCY = [{ v: "7", l: "Last 7 days" }, { v: "30", l: "Last 30 days" }, { v: "90", l: "Last 90 days" }, { v: "365", l: "Last year" }, { v: "any", l: "Any time" }];

export function ResearchForm({ initial, defaultBrandId, onStarted }: {
  initial?: Partial<ResearchRunInput>;
  defaultBrandId: string | null;
  onStarted: (runId: string) => void;
}) {
  const can = useCan();
  const start = useStartResearch();
  const [query, setQuery] = useState(initial?.query ?? "");
  const [scope, setScope] = useState<ResearchScope[]>(initial?.scope ?? ["web", "news"]);
  const [depth, setDepth] = useState<ResearchDepth>(initial?.depth ?? "standard");
  const [recency, setRecency] = useState(initial?.recency_days ? String(initial.recency_days) : "30");
  const [brandId, setBrandId] = useState<string | null>(initial?.brand_id ?? defaultBrandId);
  const errors = problemFieldErrors(start.error);

  function submit(e: React.FormEvent) {
    e.preventDefault();
    if (!query.trim() || !scope.length) return;
    start.mutate(
      { query: query.trim(), scope, depth, recency_days: recency === "any" ? null : Number(recency), brand_id: brandId ?? defaultBrandId },
      { onSuccess: (d) => onStarted(d.run_id ?? d.id ?? "") },
    );
  }

  return (
    <form onSubmit={submit} className="space-y-4" aria-label="New research run"
          onKeyDown={(e) => { if (e.key === "Enter" && (e.metaKey || e.ctrlKey)) submit(e); }}>
      <div className="space-y-1">
        <Label htmlFor="rq">Query</Label>
        <Input id="rq" value={query} onChange={(e) => setQuery(e.target.value)} placeholder="e.g. cold brew trends 2026" aria-invalid={!!errors.query} required />
        <FieldError errors={errors} name="query" />
      </div>
      <fieldset className="space-y-2">
        <legend className="text-sm font-medium">Scope</legend>
        <div className="grid grid-cols-2 gap-2">
          {SCOPES.map((s) => (
            <label key={s.id} className="flex items-center gap-2 text-sm">
              <Checkbox checked={scope.includes(s.id)} onCheckedChange={(c) => setScope((cur) => (c ? [...cur, s.id] : cur.filter((x) => x !== s.id)))} />
              {s.label}
            </label>
          ))}
        </div>
        {!scope.length && <p className="text-xs text-destructive">Pick at least one scope.</p>}
        <FieldError errors={errors} name="scope" />
      </fieldset>
      <fieldset className="space-y-2">
        <legend className="text-sm font-medium">Depth</legend>
        <div role="radiogroup" className="grid grid-cols-3 gap-1 rounded-lg bg-muted p-1">
          {DEPTHS.map((d) => (
            <button key={d.id} type="button" role="radio" aria-checked={depth === d.id} onClick={() => setDepth(d.id)}
                    className={cn("rounded-md px-2 py-1.5 text-xs font-medium", depth === d.id ? "bg-background shadow-sm" : "text-muted-foreground hover:text-foreground")}>
              {d.label}
            </button>
          ))}
        </div>
        <p className="text-xs text-muted-foreground">Estimate: {DEPTHS.find((d) => d.id === depth)?.est}</p>
      </fieldset>
      <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-1 xl:grid-cols-2">
        <div className="space-y-1">
          <Label htmlFor="rrec">Recency</Label>
          <Select value={recency} onValueChange={setRecency}>
            <SelectTrigger id="rrec" className="w-full"><SelectValue /></SelectTrigger>
            <SelectContent>{RECENCY.map((r) => <SelectItem key={r.v} value={r.v}>{r.l}</SelectItem>)}</SelectContent>
          </Select>
        </div>
        <div className="space-y-1">
          <Label htmlFor="rbrand">Brand</Label>
          <BrandSelect id="rbrand" value={brandId ?? defaultBrandId} onChange={setBrandId} />
        </div>
      </div>
      <FormError error={Object.keys(errors).length ? null : start.error} />
      <Button type="submit" className="w-full" disabled={!can.create || start.isPending || !query.trim() || !scope.length}>
        <Play className="h-4 w-4" /> {start.isPending ? "Starting…" : "Run research"} <kbd className="ml-1 hidden text-[10px] opacity-70 sm:inline">⌘↵</kbd>
      </Button>
      {!can.create && <p className="text-xs text-muted-foreground">Viewers can read research but not start runs.</p>}
    </form>
  );
}

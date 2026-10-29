"use client";
import Link from "next/link";
import { Sparkles } from "lucide-react";
import { Popover, PopoverContent, PopoverTrigger } from "@/components/ui/popover";
import { cn } from "@/lib/utils";
import type { GenerationMetadata } from "../types";
import { fmtUsd } from "../utils";
import { useWorkspacePath } from "../hooks";

/** Provenance chip "✦ AI" with agent/model/run/cost (doc 24 §0.5). */
export function AiBadge({ meta, className, label = "AI" }: { meta?: GenerationMetadata | null; className?: string; label?: string }) {
  const ws = useWorkspacePath();
  const chip = (
    <span className={cn("inline-flex items-center gap-1 rounded-full bg-ai/15 px-2 py-0.5 text-xs font-medium text-ai", className)}>
      <Sparkles className="h-3 w-3" aria-hidden /> {label}
    </span>
  );
  if (!meta || Object.keys(meta).length === 0) return chip;
  return (
    <Popover>
      <PopoverTrigger asChild><button type="button" aria-label="AI provenance details">{chip}</button></PopoverTrigger>
      <PopoverContent className="w-64 text-xs">
        <dl className="grid grid-cols-[auto_1fr] gap-x-3 gap-y-1">
          {meta.agent && <><dt className="text-muted-foreground">Agent</dt><dd className="font-mono">{meta.agent}</dd></>}
          {meta.tier && <><dt className="text-muted-foreground">Tier</dt><dd>{meta.tier}</dd></>}
          {meta.provider && <><dt className="text-muted-foreground">Provider</dt><dd>{meta.provider}</dd></>}
          {meta.model && <><dt className="text-muted-foreground">Model</dt><dd className="font-mono break-all">{meta.model}</dd></>}
          {meta.prompt_version && <><dt className="text-muted-foreground">Prompt</dt><dd className="font-mono">{meta.prompt_version}</dd></>}
          {meta.cost_usd != null && <><dt className="text-muted-foreground">Cost</dt><dd>{fmtUsd(meta.cost_usd)}</dd></>}
        </dl>
        {meta.run_id && <Link className="mt-2 inline-block text-primary underline-offset-2 hover:underline" href={ws(`command-center/${meta.run_id}`)}>Open run ↗</Link>}
      </PopoverContent>
    </Popover>
  );
}

export function CostPill({ usd, className }: { usd: number | null | undefined; className?: string }) {
  if (usd == null) return null;
  return <span className={cn("inline-flex items-center rounded-full border px-2 py-0.5 font-mono text-[11px] text-muted-foreground", className)} title="AI cost">{fmtUsd(usd)}</span>;
}

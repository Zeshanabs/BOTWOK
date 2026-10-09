"use client";
/** Credibility / relevance / injection badges and favicon used by SourceList surfaces (research, command center). */
import { useState } from "react";
import { Globe, ShieldAlert, Star } from "lucide-react";
import { faviconUrl, score100 } from "@/lib/formatters";
import { cn } from "@/lib/utils";

export function credibilityLevel(v: unknown): "high" | "med" | "low" | null {
  const s = score100(v);
  if (s === null) return null;
  return s >= 75 ? "high" : s >= 50 ? "med" : "low";
}

export function CredibilityBadge({ value, className }: { value: unknown; className?: string }) {
  const level = credibilityLevel(value);
  if (!level) return null;
  const styles = {
    high: "bg-green-100 text-green-800 dark:bg-green-900/40 dark:text-green-200",
    med: "bg-amber-100 text-amber-800 dark:bg-amber-900/40 dark:text-amber-200",
    low: "bg-red-100 text-red-800 dark:bg-red-900/40 dark:text-red-200",
  }[level];
  return (
    <span className={cn("inline-flex items-center gap-1 rounded-full px-2 py-0.5 text-[11px] font-medium", styles, className)} title={`Credibility ${score100(value)}/100`}>
      <span className="h-1.5 w-1.5 rounded-full bg-current" aria-hidden /> {level === "med" ? "medium" : level} credibility
    </span>
  );
}

export function RelevanceBadge({ value, className }: { value: unknown; className?: string }) {
  const s = score100(value);
  if (s === null) return null;
  return (
    <span className={cn("inline-flex items-center gap-0.5 rounded-full border px-2 py-0.5 text-[11px] font-medium tabular-nums", className)} title={`Relevance ${s}/100`}>
      <Star className="h-3 w-3 fill-current text-amber-500" aria-hidden /> {s}
      <span className="sr-only">relevance</span>
    </span>
  );
}

export function InjectionBadge({ className }: { className?: string }) {
  return (
    <span className={cn("inline-flex items-center gap-1 rounded-full border border-red-300 px-2 py-0.5 text-[11px] font-medium text-red-700 dark:border-red-800 dark:text-red-300", className)}
          title="This page contained text that looked like instructions to an AI. It was treated as untrusted data only.">
      <ShieldAlert className="h-3 w-3" aria-hidden /> Possible prompt injection
    </span>
  );
}

export function Favicon({ domain, className }: { domain: string | null | undefined; className?: string }) {
  const [failed, setFailed] = useState(false);
  const src = faviconUrl(domain);
  if (!src || failed) return <Globe className={cn("h-4 w-4 shrink-0 text-muted-foreground", className)} aria-hidden />;
  return (
    // eslint-disable-next-line @next/next/no-img-element -- external favicon service, tiny image
    <img src={src} alt="" width={16} height={16} className={cn("h-4 w-4 shrink-0 rounded-sm", className)} onError={() => setFailed(true)} loading="lazy" />
  );
}

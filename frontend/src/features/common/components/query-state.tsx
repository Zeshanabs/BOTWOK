"use client";
import { useState } from "react";
import { AlertTriangle, Check, Copy, Info, RotateCw } from "lucide-react";
import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert";
import { Button } from "@/components/ui/button";
import { Skeleton } from "@/components/ui/skeleton";
import { cn } from "@/lib/utils";
import { errorMessage, isNotAvailable, requestId } from "../utils";

/** Region-scoped error with Retry and a copyable request id (doc 24 §0.6). 404/501 render as "not available yet". */
export function QueryError({ error, onRetry, title = "Couldn't load this", className, notAvailableText }: {
  error: unknown; onRetry?: () => void; title?: string; className?: string; notAvailableText?: string;
}) {
  const [copied, setCopied] = useState(false);
  if (isNotAvailable(error) && notAvailableText) return <NotAvailable className={className} text={notAvailableText} />;
  const rid = requestId(error);
  return (
    <Alert variant="destructive" className={className}>
      <AlertTriangle />
      <AlertTitle>{title}</AlertTitle>
      <AlertDescription>
        <p>{errorMessage(error)}</p>
        <div className="mt-1 flex flex-wrap items-center gap-2">
          {onRetry && <Button size="xs" variant="outline" onClick={onRetry}><RotateCw /> Retry</Button>}
          {rid && (
            <Button size="xs" variant="ghost" onClick={() => { void navigator.clipboard?.writeText(rid); setCopied(true); setTimeout(() => setCopied(false), 1500); }}>
              {copied ? <Check /> : <Copy />} <span className="font-mono">{rid.slice(-12)}</span>
            </Button>
          )}
        </div>
      </AlertDescription>
    </Alert>
  );
}

export function NotAvailable({ text, className }: { text: string; className?: string }) {
  return (
    <Alert className={className}>
      <Info />
      <AlertTitle>Not available yet</AlertTitle>
      <AlertDescription>{text}</AlertDescription>
    </Alert>
  );
}

export function SkeletonRows({ rows = 4, className }: { rows?: number; className?: string }) {
  return (
    <div className={cn("space-y-2", className)} aria-busy="true" aria-label="Loading">
      {Array.from({ length: rows }).map((_, i) => <Skeleton key={i} className="h-9 w-full" />)}
    </div>
  );
}

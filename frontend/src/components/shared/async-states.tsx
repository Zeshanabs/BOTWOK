"use client";
import { useState } from "react";
import { AlertTriangle, Check, Copy, Info, RotateCw, SearchX } from "lucide-react";
import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert";
import { Button } from "@/components/ui/button";
import { Skeleton } from "@/components/ui/skeleton";
import { errorMessage, errorStatus, isNotAvailable, requestId } from "@/features/common/utils";
import { cn } from "@/lib/utils";

export { errorMessage, errorStatus, isNotAvailable };

/**
 * Region-scoped error with Retry and a copyable request id (doc 24 §0.6).
 * 404 with `notFoundText` → "not found"; 404/405/501 with `notAvailableText` → calm "not available yet".
 */
export function QueryError({ error, onRetry, title = "Couldn't load this", className, notAvailableText, notFoundText }: {
  error: unknown; onRetry?: () => void | Promise<unknown>; title?: string; className?: string; notAvailableText?: string; notFoundText?: string;
}) {
  const [copied, setCopied] = useState(false);
  if (errorStatus(error) === 404 && notFoundText) return <NotAvailable className={className} icon={SearchX} title="Not found" description={notFoundText} />;
  if (isNotAvailable(error) && notAvailableText) return <NotAvailable className={className} description={notAvailableText} />;
  const rid = requestId(error);
  return (
    <Alert variant="destructive" className={cn("bg-destructive/[0.04]", className)}>
      <AlertTriangle />
      <AlertTitle>{title}</AlertTitle>
      <AlertDescription>
        <p>{errorMessage(error)}</p>
        <div className="mt-1.5 flex flex-wrap items-center gap-2">
          {onRetry && <Button size="xs" variant="outline" onClick={() => void onRetry()}><RotateCw /> Retry</Button>}
          {rid && (
            <Button size="xs" variant="ghost" onClick={() => { void navigator.clipboard?.writeText(rid); setCopied(true); setTimeout(() => setCopied(false), 1500); }} title="Copy request id">
              {copied ? <Check /> : <Copy />} <span className="font-mono">{rid.slice(-12)}</span>
            </Button>
          )}
        </div>
      </AlertDescription>
    </Alert>
  );
}

/** Calm informational state for modules the backend does not expose (yet). Accepts `text` or `title` + `description`. */
export function NotAvailable({ title = "Not available yet", description, text, className, icon: Icon = Info }: {
  title?: string; description?: string; text?: string; className?: string; icon?: typeof Info;
}) {
  return (
    <Alert className={cn("border-dashed bg-muted/40", className)}>
      <Icon />
      <AlertTitle>{title}</AlertTitle>
      {(description ?? text) && <AlertDescription>{description ?? text}</AlertDescription>}
    </Alert>
  );
}

/** Rows of skeleton bars that mirror a list or table. */
export function ListSkeleton({ rows = 4, rowClassName = "h-10", className }: { rows?: number; rowClassName?: string; className?: string }) {
  return (
    <div className={cn("space-y-2", className)} aria-busy="true" aria-label="Loading">
      {Array.from({ length: rows }).map((_, i) => <Skeleton key={i} className={cn("w-full rounded-lg", rowClassName)} style={{ opacity: 1 - i * 0.08 }} />)}
    </div>
  );
}

/** A responsive grid of card-shaped skeletons. `className` overrides the column rules. */
export function CardGridSkeleton({ count = 6, className, cardClassName = "h-36" }: { count?: number; className?: string; cardClassName?: string }) {
  return (
    <div className={cn("grid gap-4 sm:grid-cols-2 lg:grid-cols-3", className)} aria-busy="true" aria-label="Loading">
      {Array.from({ length: count }).map((_, i) => <Skeleton key={i} className={cn("w-full rounded-xl", cardClassName)} />)}
    </div>
  );
}

"use client";
/** Shared loading / error / not-available states for query-driven regions (doc 24 §0.6). */
import { AlertCircle, Clock, RotateCw } from "lucide-react";
import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert";
import { Button } from "@/components/ui/button";
import { Skeleton } from "@/components/ui/skeleton";
import { ApiError } from "@/lib/api";
import { cn } from "@/lib/utils";

const UNROUTED = ["Not Found", "Method Not Allowed", "Not Implemented"];

/** HTTP status of an ApiError; FastAPI's default (non-Problem) bodies like `{"detail":"Not Found"}` carry no status. */
export function errorStatus(error: unknown): number | null {
  if (!(error instanceof ApiError)) return null;
  if (typeof error.problem.status === "number") return error.problem.status;
  const d = error.problem.detail;
  return d === "Not Found" ? 404 : d === "Method Not Allowed" ? 405 : d === "Not Implemented" ? 501 : null;
}

/** True when the backend has not implemented the endpoint yet (or AI is disabled). */
export function isNotAvailable(error: unknown): boolean {
  const st = errorStatus(error);
  return st !== null ? [404, 405, 501].includes(st) : error instanceof ApiError && UNROUTED.includes(error.problem.detail ?? "");
}

export function errorMessage(error: unknown, fallback = "Something went wrong"): string {
  if (error instanceof ApiError) return error.problem.detail || error.problem.title || fallback;
  if (error instanceof Error) return error.message || fallback;
  return fallback;
}

export function NotAvailable({ title = "Not available yet", description, className }: { title?: string; description?: string; className?: string }) {
  return (
    <div className={cn("flex items-start gap-3 rounded-lg border border-dashed bg-muted/30 p-4 text-sm", className)} role="status">
      <Clock className="mt-0.5 h-4 w-4 shrink-0 text-muted-foreground" aria-hidden />
      <div>
        <p className="font-medium">{title}</p>
        <p className="text-muted-foreground">{description ?? "This part of Botwok isn't switched on in this install yet. Everything else keeps working."}</p>
      </div>
    </div>
  );
}

/** Region-scoped error: calm "not available" for 404/501, destructive Alert + Retry otherwise. */
export function QueryError({ error, onRetry, title = "Couldn't load this", className, notAvailableText, notFoundText }: {
  error: unknown; onRetry?: () => void; title?: string; className?: string; notAvailableText?: string;
  /** For single-resource reads: a 404 means "doesn't exist" rather than "endpoint not implemented". */
  notFoundText?: string;
}) {
  if (notFoundText && errorStatus(error) === 404) return <NotAvailable className={className} title="Not found" description={notFoundText} />;
  if (isNotAvailable(error)) return <NotAvailable className={className} description={notAvailableText} />;
  const requestId = error instanceof ApiError ? error.problem.instance : undefined;
  return (
    <Alert variant="destructive" className={className}>
      <AlertCircle />
      <AlertTitle>{title}</AlertTitle>
      <AlertDescription>
        <p>{errorMessage(error)}</p>
        {requestId && <p className="font-mono text-xs">Request {requestId}</p>}
        {onRetry && (
          <Button variant="outline" size="sm" className="mt-2" onClick={onRetry}>
            <RotateCw className="h-3 w-3" /> Retry
          </Button>
        )}
      </AlertDescription>
    </Alert>
  );
}

export function ListSkeleton({ rows = 5, className, rowClassName }: { rows?: number; className?: string; rowClassName?: string }) {
  return (
    <div className={cn("space-y-2", className)} aria-busy="true" aria-label="Loading">
      {Array.from({ length: rows }).map((_, i) => <Skeleton key={i} className={cn("h-12 w-full", rowClassName)} />)}
    </div>
  );
}

export function CardGridSkeleton({ count = 6, className, cardClassName }: { count?: number; className?: string; cardClassName?: string }) {
  return (
    <div className={cn("grid gap-4 sm:grid-cols-2 xl:grid-cols-3", className)} aria-busy="true" aria-label="Loading">
      {Array.from({ length: count }).map((_, i) => <Skeleton key={i} className={cn("h-44 w-full rounded-xl", cardClassName)} />)}
    </div>
  );
}

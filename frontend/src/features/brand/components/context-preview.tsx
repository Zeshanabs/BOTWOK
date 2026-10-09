"use client";
/** BrandContext preview — exactly what agents receive (GET /brands/{id}/context). */
import { toast } from "sonner";
import { Copy, RefreshCw } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Skeleton } from "@/components/ui/skeleton";
import { QueryError } from "@/components/data/async-states";
import { fmtCompact } from "@/lib/formatters";
import { useBrandContext } from "../hooks";

export function ContextPreview({ brandId }: { brandId: string }) {
  const q = useBrandContext(brandId);
  return (
    <Card className="gap-3">
      <CardHeader className="flex flex-row items-center justify-between">
        <CardTitle className="text-sm">Preview AI context</CardTitle>
        <div className="flex gap-1">
          <Button size="icon-sm" variant="ghost" aria-label="Refresh context" onClick={() => q.refetch()} disabled={q.isFetching}><RefreshCw className={q.isFetching ? "h-4 w-4 animate-spin" : "h-4 w-4"} /></Button>
          <Button size="icon-sm" variant="ghost" aria-label="Copy context" disabled={!q.data?.text}
                  onClick={() => navigator.clipboard?.writeText(q.data?.text ?? "").then(() => toast.success("Context copied"), () => toast.error("Clipboard unavailable"))}><Copy className="h-4 w-4" /></Button>
        </div>
      </CardHeader>
      <CardContent className="space-y-2">
        {q.isLoading ? <Skeleton className="h-64 w-full" /> : q.error ? (
          <QueryError error={q.error} onRetry={() => q.refetch()} title="Couldn't build the context" notAvailableText="The context preview isn't available on this install yet." />
        ) : (
          <>
            <pre className="max-h-[60vh] overflow-auto whitespace-pre-wrap rounded-md bg-muted/50 p-3 font-mono text-[11px] leading-relaxed">{q.data?.text || "(empty — fill in the sections to give agents something to work with)"}</pre>
            <p className="text-xs text-muted-foreground">
              {q.data?.token_estimate != null ? `≈ ${fmtCompact(q.data.token_estimate)} tokens · ` : ""}{q.data?.mode ? `${q.data.mode} mode · ` : ""}sent to every agent for this brand.
            </p>
          </>
        )}
      </CardContent>
    </Card>
  );
}

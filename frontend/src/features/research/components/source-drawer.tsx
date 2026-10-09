"use client";
/** Source detail drawer (doc 24 §7): provenance, scores, keywords/topics, extracted text, Save / Cite. */
import { toast } from "sonner";
import { Bookmark, Copy, ExternalLink, Quote } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Sheet, SheetContent, SheetDescription, SheetHeader, SheetTitle } from "@/components/ui/sheet";
import { Skeleton } from "@/components/ui/skeleton";
import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert";
import { QueryError, errorMessage } from "@/components/data/async-states";
import { domainOf, fmtDate, fmtDateTime } from "@/lib/formatters";
import { useCan } from "@/lib/permissions";
import { useResearchSource, useSaveSource } from "../hooks";
import { credibilityOf, relevanceOf, type ResearchSourceDetail } from "../types";
import { CredibilityBadge, Favicon, InjectionBadge, RelevanceBadge } from "./source-badges";

export function citationFor(s: ResearchSourceDetail): string {
  if (s.citation) return s.citation;
  const url = s.final_url || s.canonical_url || s.url || "";
  return [s.title, s.author, s.domain || domainOf(url), s.published_at ? fmtDate(s.published_at) : null, url].filter(Boolean).join(". ");
}

function Row({ label, children }: { label: string; children: React.ReactNode }) {
  return <div className="contents"><dt className="text-muted-foreground">{label}</dt><dd className="min-w-0 break-words">{children}</dd></div>;
}

export function SourceDrawer({ sourceId, onOpenChange }: { sourceId: string | null; onOpenChange: (open: boolean) => void }) {
  const can = useCan();
  const q = useResearchSource(sourceId);
  const save = useSaveSource();
  const s = q.data;
  const url = s ? s.final_url || s.canonical_url || s.url : null;
  const domain = s ? s.domain || domainOf(url) : "";
  const text = s?.text || s?.extracted_text || s?.content;

  async function cite() {
    if (!s) return;
    try { await navigator.clipboard.writeText(citationFor(s)); toast.success("Citation copied"); } catch { toast.error("Clipboard unavailable"); }
  }

  return (
    <Sheet open={!!sourceId} onOpenChange={onOpenChange}>
      <SheetContent className="w-full overflow-y-auto sm:max-w-xl">
        <SheetHeader>
          <SheetTitle className="flex items-start gap-2 pr-6"><Favicon domain={domain} className="mt-1" />{s?.title || (q.isLoading ? "Loading source…" : "Source")}</SheetTitle>
          <SheetDescription>{domain}{s?.source_kind ? ` · ${s.source_kind}` : ""}</SheetDescription>
        </SheetHeader>
        <div className="space-y-4 px-4 pb-6 text-sm">
          {q.isLoading && <div className="space-y-2"><Skeleton className="h-4 w-1/2" /><Skeleton className="h-24 w-full" /><Skeleton className="h-48 w-full" /></div>}
          {q.error != null && <QueryError error={q.error} onRetry={() => q.refetch()} title="Couldn't load source" notFoundText="This source was removed." />}
          {s && (
            <>
              <div className="flex flex-wrap gap-2">
                {can.create && (
                  <Button size="sm" disabled={save.isPending || s.saved} onClick={() => save.mutate(s.id, { onSuccess: () => toast.success("Saved to research library"), onError: (e) => toast.error(errorMessage(e)) })}>
                    <Bookmark className="h-3 w-3" /> {s.saved ? "Saved" : "Save"}
                  </Button>
                )}
                <Button size="sm" variant="outline" onClick={cite}><Quote className="h-3 w-3" /> Cite</Button>
                {url && <Button size="sm" variant="ghost" asChild><a href={url} target="_blank" rel="noreferrer noopener"><ExternalLink className="h-3 w-3" /> Open original</a></Button>}
              </div>
              {s.injection_flag && (
                <Alert variant="destructive">
                  <AlertTitle>Possible prompt injection</AlertTitle>
                  <AlertDescription>This page contained text that looked like instructions to an AI. Botwok treats it as untrusted data and never follows it.</AlertDescription>
                </Alert>
              )}
              <div className="flex flex-wrap gap-1">
                <RelevanceBadge value={relevanceOf(s)} />
                <CredibilityBadge value={credibilityOf(s)} />
                {s.injection_flag && <InjectionBadge />}
              </div>
              <dl className="grid grid-cols-[8rem_1fr] gap-x-3 gap-y-1 text-xs">
                {url && <Row label="URL"><a href={url} target="_blank" rel="noreferrer noopener" className="text-primary hover:underline">{url}</a></Row>}
                <Row label="Published">{fmtDate(s.published_at)}</Row>
                <Row label="Retrieved">{fmtDateTime(s.retrieved_at)}</Row>
                {s.author && <Row label="Author">{s.author}</Row>}
                {s.language && <Row label="Language">{s.language}</Row>}
                {s.word_count != null && <Row label="Words">{s.word_count}</Row>}
                {s.fetch_status && <Row label="Fetch status">{s.fetch_status}</Row>}
                {s.trust && <Row label="Trust">{s.trust}</Row>}
                {s.content_hash && (
                  <Row label="Content hash">
                    <button type="button" className="inline-flex items-center gap-1 font-mono hover:text-primary" title="Copy hash"
                            onClick={() => navigator.clipboard?.writeText(s.content_hash ?? "").then(() => toast.success("Hash copied"), () => undefined)}>
                      {s.content_hash.slice(0, 16)}… <Copy className="h-3 w-3" />
                    </button>
                  </Row>
                )}
              </dl>
              {s.summary && <section><h3 className="mb-1 text-xs font-semibold uppercase tracking-wide text-muted-foreground">Summary</h3><p>{s.summary}</p></section>}
              {(s.keywords?.length ?? 0) > 0 && (
                <section><h3 className="mb-1 text-xs font-semibold uppercase tracking-wide text-muted-foreground">Keywords</h3>
                  <div className="flex flex-wrap gap-1">{s.keywords?.map((k) => <span key={k} className="rounded-full bg-secondary px-2 py-0.5 text-xs">{k}</span>)}</div></section>
              )}
              {(s.topics?.length ?? 0) > 0 && (
                <section><h3 className="mb-1 text-xs font-semibold uppercase tracking-wide text-muted-foreground">Topics</h3>
                  <div className="flex flex-wrap gap-1">{s.topics?.map((k) => <span key={k} className="rounded-full border px-2 py-0.5 text-xs">{k}</span>)}</div></section>
              )}
              <section>
                <h3 className="mb-1 text-xs font-semibold uppercase tracking-wide text-muted-foreground">Extracted text</h3>
                {text ? <div className="max-h-96 overflow-y-auto whitespace-pre-wrap rounded-md border bg-muted/30 p-3 text-xs leading-relaxed">{text}</div>
                      : <p className="text-xs text-muted-foreground">Extracted text isn&apos;t included in this response.</p>}
              </section>
            </>
          )}
        </div>
      </SheetContent>
    </Sheet>
  );
}

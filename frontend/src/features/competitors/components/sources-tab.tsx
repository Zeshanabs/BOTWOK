"use client";
import { useState } from "react";
import { Globe, Newspaper } from "lucide-react";
import { EmptyState } from "@/components/data/empty-state";
import { ListSkeleton, QueryError } from "@/components/data/async-states";
import { domainOf, fmtDate } from "@/lib/formatters";
import { useResearchSources } from "@/features/research/hooks";
import { credibilityOf } from "@/features/research/types";
import { CredibilityBadge, Favicon, InjectionBadge } from "@/features/research/components/source-badges";
import { SourceDrawer } from "@/features/research/components/source-drawer";

/** Website & Blog (public_web) or News (search) sources linked to this competitor. */
export function CompetitorSourcesTab({ competitorId, kind }: { competitorId: string; kind: "website" | "news" }) {
  const q = useResearchSources({ competitor_id: competitorId });
  const [openId, setOpenId] = useState<string | null>(null);
  if (q.isLoading) return <ListSkeleton rows={5} />;
  if (q.error) return <QueryError error={q.error} onRetry={() => q.refetch()} title="Couldn't load sources" />;
  const isNews = (k?: string | null) => k === "news" || k === "search" || k === "press";
  const items = (q.data ?? []).filter((s) => (kind === "news" ? isNews(s.source_kind) : !isNews(s.source_kind)))
    .sort((a, b) => String(b.published_at ?? "").localeCompare(String(a.published_at ?? "")));
  if (!items.length) {
    return kind === "news"
      ? <EmptyState icon={Newspaper} title="No news mentions yet" description="Dated mentions found through the search provider appear here after a sync or report." />
      : <EmptyState icon={Globe} title="No website pages yet" description="Pages, blog posts and RSS items from the competitor's own site (fetched per robots.txt) appear after a sync." />;
  }
  return (
    <>
      <ul className="space-y-2">
        {items.map((s) => {
          const domain = s.domain || domainOf(s.url ?? s.canonical_url);
          return (
            <li key={s.id}>
              <button type="button" onClick={() => setOpenId(s.id)} className="flex w-full items-start gap-3 rounded-lg border p-3 text-left hover:bg-accent/40">
                <Favicon domain={domain} className="mt-0.5" />
                <span className="min-w-0 flex-1">
                  <span className="block text-sm font-medium">{s.title || s.url}</span>
                  <span className="block text-xs text-muted-foreground">{domain} · {fmtDate(s.published_at)}</span>
                  {s.summary && <span className="mt-1 block line-clamp-2 text-xs text-muted-foreground">{s.summary}</span>}
                </span>
                <span className="flex shrink-0 flex-col items-end gap-1"><CredibilityBadge value={credibilityOf(s)} />{s.injection_flag && <InjectionBadge />}</span>
              </button>
            </li>
          );
        })}
      </ul>
      <SourceDrawer sourceId={openId} onOpenChange={(o) => { if (!o) setOpenId(null); }} />
    </>
  );
}

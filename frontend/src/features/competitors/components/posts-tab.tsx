"use client";
import { useState } from "react";
import { ExternalLink, FileText } from "lucide-react";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { Sheet, SheetContent, SheetDescription, SheetHeader, SheetTitle } from "@/components/ui/sheet";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { PlatformIcon } from "@/components/shared/platform-icon";
import { AvailabilityBadge } from "@/components/shared/availability-badge";
import { EmptyState } from "@/components/shared/empty-state";
import { ListSkeleton, QueryError } from "@/components/shared/async-states";
import { fmtCompact, fmtDate, fmtDateTime, truncate } from "@/lib/formatters";
import { platformMeta } from "@/lib/platforms";
import { useCompetitorPosts } from "../hooks";
import type { CompetitorPost } from "../types";

const ALL = "all";

export function PostsTab({ competitorId }: { competitorId: string }) {
  const q = useCompetitorPosts(competitorId);
  const [platform, setPlatform] = useState(ALL);
  const [format, setFormat] = useState(ALL);
  const [open, setOpen] = useState<CompetitorPost | null>(null);
  if (q.isLoading) return <ListSkeleton rows={8} />;
  if (q.error) return <QueryError error={q.error} onRetry={() => q.refetch()} title="Couldn't load posts" />;
  const posts = q.data ?? [];
  if (!posts.length) return <EmptyState icon={FileText} title="No posts collected" description="Posts are collected only from Official API profiles. Restricted platforms show handles only." />;
  const platforms = Array.from(new Set(posts.map((p) => p.platform).filter(Boolean))) as string[];
  const formats = Array.from(new Set(posts.map((p) => p.format).filter(Boolean))) as string[];
  const rows = posts.filter((p) => (platform === ALL || p.platform === platform) && (format === ALL || p.format === format))
    .sort((a, b) => String(b.posted_at ?? "").localeCompare(String(a.posted_at ?? "")));

  return (
    <div className="space-y-3">
      <div className="flex flex-wrap gap-2">
        <Select value={platform} onValueChange={setPlatform}>
          <SelectTrigger size="sm" aria-label="Platform"><SelectValue /></SelectTrigger>
          <SelectContent><SelectItem value={ALL}>All platforms</SelectItem>{platforms.map((p) => <SelectItem key={p} value={p}>{platformMeta(p).label}</SelectItem>)}</SelectContent>
        </Select>
        <Select value={format} onValueChange={setFormat}>
          <SelectTrigger size="sm" aria-label="Format"><SelectValue /></SelectTrigger>
          <SelectContent><SelectItem value={ALL}>All formats</SelectItem>{formats.map((f) => <SelectItem key={f} value={f}>{f.replace(/_/g, " ")}</SelectItem>)}</SelectContent>
        </Select>
        <span className="self-center text-xs text-muted-foreground">{rows.length} posts</span>
      </div>
      <div className="overflow-x-auto rounded-lg border">
        <Table>
          <TableHeader><TableRow><TableHead>Date</TableHead><TableHead>Platform</TableHead><TableHead>Format</TableHead><TableHead>Caption</TableHead><TableHead className="text-right">Likes</TableHead><TableHead className="text-right">Comments</TableHead><TableHead className="text-right">Views</TableHead><TableHead>Source</TableHead><TableHead /></TableRow></TableHeader>
          <TableBody>
            {rows.map((p) => (
              <TableRow key={p.id} className="cursor-pointer" onClick={() => setOpen(p)}>
                <TableCell className="whitespace-nowrap text-xs">{fmtDate(p.posted_at)}</TableCell>
                <TableCell>{p.platform && <PlatformIcon platform={p.platform} size={18} />}</TableCell>
                <TableCell className="text-xs">{p.format?.replace(/_/g, " ") ?? "—"}</TableCell>
                <TableCell className="max-w-sm truncate text-sm">{truncate(p.text, 120) || "—"}</TableCell>
                <TableCell className="text-right tabular-nums">{fmtCompact(p.like_count)}</TableCell>
                <TableCell className="text-right tabular-nums">{fmtCompact(p.comment_count)}</TableCell>
                <TableCell className="text-right tabular-nums">{fmtCompact(p.view_count)}</TableCell>
                <TableCell>{p.availability && <AvailabilityBadge availability={p.availability} short />}</TableCell>
                <TableCell onClick={(e) => e.stopPropagation()}>{p.url && <a href={p.url} target="_blank" rel="noreferrer noopener" aria-label="Open original post"><ExternalLink className="h-4 w-4 text-muted-foreground hover:text-foreground" /></a>}</TableCell>
              </TableRow>
            ))}
          </TableBody>
        </Table>
      </div>
      <Sheet open={!!open} onOpenChange={(o) => { if (!o) setOpen(null); }}>
        <SheetContent className="w-full overflow-y-auto sm:max-w-lg">
          {open && (
            <>
              <SheetHeader>
                <SheetTitle className="flex items-center gap-2">{open.platform && <PlatformIcon platform={open.platform} />} Post · {fmtDate(open.posted_at)}</SheetTitle>
                <SheetDescription>{open.format?.replace(/_/g, " ")} · collected {fmtDateTime(open.retrieved_at)}</SheetDescription>
              </SheetHeader>
              <div className="space-y-4 px-4 pb-6 text-sm">
                {open.availability && <AvailabilityBadge availability={open.availability} />}
                <p className="whitespace-pre-wrap">{open.text || "No caption."}</p>
                {(open.hashtags?.length ?? 0) > 0 && <p className="text-xs text-muted-foreground">{open.hashtags?.join(" ")}</p>}
                <dl className="grid grid-cols-2 gap-2 text-xs">
                  {(["like_count", "comment_count", "share_count", "view_count"] as const).map((k) => (
                    <div key={k} className="rounded-md border p-2"><dt className="text-muted-foreground">{k.replace("_count", "s")}</dt><dd className="text-base font-medium tabular-nums">{open[k] != null ? Number(open[k]).toLocaleString() : "Not collected"}</dd></div>
                  ))}
                </dl>
                {(open.media_urls?.length ?? 0) > 0 && (
                  <ul className="space-y-1 text-xs">{open.media_urls?.map((m) => <li key={m}><a href={m} target="_blank" rel="noreferrer noopener" className="text-primary hover:underline">{truncate(m, 60)}</a></li>)}</ul>
                )}
                {open.url && <a href={open.url} target="_blank" rel="noreferrer noopener" className="inline-flex items-center gap-1 text-primary hover:underline">Open original <ExternalLink className="h-3 w-3" /></a>}
              </div>
            </>
          )}
        </SheetContent>
      </Sheet>
    </div>
  );
}

"use client";
import Link from "next/link";
import { ArrowUpRight, MoreHorizontal, Star } from "lucide-react";
import { Button } from "@/components/ui/button";
import { DropdownMenu, DropdownMenuContent, DropdownMenuItem, DropdownMenuSeparator, DropdownMenuTrigger } from "@/components/ui/dropdown-menu";
import { PlatformIcon } from "@/components/shared/platform-icon";
import { humanize, score100 } from "@/lib/formatters";
import { useCan } from "@/lib/permissions";
import { useSession } from "@/stores/session";
import type { Idea } from "../types";

export function evidenceLink(idea: Idea, slug: string | null): { href: string; label: string } | null {
  const e = idea.evidence;
  if (!e) return null;
  if (e.trend_ids?.length) return { href: `/w/${slug}/trends?trend=${e.trend_ids[0]}`, label: "trend" };
  if (e.research_source_ids?.length) return { href: `/w/${slug}/research`, label: "research" };
  if (e.report_id) return { href: `/w/${slug}/reports/${e.report_id}`, label: "competitor gap" };
  if (e.insight_ids?.length) return { href: `/w/${slug}/analytics`, label: "insight" };
  if (e.urls?.length) return { href: e.urls[0], label: "source" };
  return null;
}

export interface IdeaActions {
  onStatus: (idea: Idea, status: string) => void;
  onPromote: (idea: Idea) => void;
  onDelete: (idea: Idea) => void;
  onOpen: (idea: Idea) => void;
}

export function IdeaMenu({ idea, actions }: { idea: Idea; actions: IdeaActions }) {
  const can = useCan();
  return (
    <DropdownMenu>
      <DropdownMenuTrigger asChild><Button variant="ghost" size="icon-xs" aria-label={`Actions for ${idea.title}`}><MoreHorizontal /></Button></DropdownMenuTrigger>
      <DropdownMenuContent align="end">
        <DropdownMenuItem onClick={() => actions.onOpen(idea)}>Details</DropdownMenuItem>
        {can.create && idea.status !== "promoted" && (
          <>
            {idea.status !== "shortlisted" && <DropdownMenuItem onClick={() => actions.onStatus(idea, "shortlisted")}>Shortlist</DropdownMenuItem>}
            {idea.status !== "new" && <DropdownMenuItem onClick={() => actions.onStatus(idea, "new")}>Move to new</DropdownMenuItem>}
            {idea.status !== "discarded" && <DropdownMenuItem onClick={() => actions.onStatus(idea, "discarded")}>Discard</DropdownMenuItem>}
            <DropdownMenuItem onClick={() => actions.onPromote(idea)}>Promote to Studio</DropdownMenuItem>
            <DropdownMenuSeparator />
            <DropdownMenuItem className="text-destructive" onClick={() => actions.onDelete(idea)}>Delete</DropdownMenuItem>
          </>
        )}
      </DropdownMenuContent>
    </DropdownMenu>
  );
}

export function IdeaCard({ idea, pillarName, actions, dragHandle }: { idea: Idea; pillarName?: string; actions: IdeaActions; dragHandle?: React.ReactNode }) {
  const slug = useSession((s) => s.workspaceSlug);
  const can = useCan();
  const ev = evidenceLink(idea, slug);
  const formats = idea.formats?.length ? idea.formats : idea.format ? [idea.format] : [];
  const s = score100(idea.score);
  return (
    <div className="rounded-lg border bg-card p-3 text-sm shadow-xs">
      <div className="flex items-start gap-1">
        {dragHandle}
        <button type="button" className="min-w-0 flex-1 text-left font-medium hover:underline" onClick={() => actions.onOpen(idea)}>
          {idea.ai_run_id && <span className="mr-1 text-ai" aria-label="AI generated">✦</span>}{idea.title}
        </button>
        <IdeaMenu idea={idea} actions={actions} />
      </div>
      <div className="mt-1.5 flex flex-wrap items-center gap-1.5 text-xs text-muted-foreground">
        {idea.content_type && <span className="rounded-full bg-secondary px-2 py-0.5">{humanize(idea.content_type)}</span>}
        {formats.map((f) => <span key={f} className="rounded-full border px-2 py-0.5">{f.replace(/_/g, " ")}</span>)}
        {(idea.platforms ?? []).map((p) => <PlatformIcon key={p} platform={p} size={16} />)}
      </div>
      <div className="mt-1.5 flex flex-wrap items-center gap-2 text-xs text-muted-foreground">
        {(pillarName || idea.pillar?.name) && <span>{pillarName || idea.pillar?.name}</span>}
        {s !== null && <span className="inline-flex items-center gap-0.5 tabular-nums"><Star className="h-3 w-3 fill-current text-warning" />{s}</span>}
        {ev && (ev.href.startsWith("http") ? <a href={ev.href} target="_blank" rel="noreferrer noopener" className="text-primary hover:underline">↳ {ev.label}</a> : <Link href={ev.href} className="text-primary hover:underline">↳ {ev.label}</Link>)}
        {idea.similar_to && <span className="text-warning">similar to another idea</span>}
      </div>
      {idea.status === "promoted" && idea.promoted_content_id ? (
        <Link href={`/w/${slug}/studio/${idea.promoted_content_id}`} className="mt-2 inline-flex items-center gap-1 text-xs text-primary hover:underline">In Studio <ArrowUpRight className="h-3 w-3" /></Link>
      ) : can.create && idea.status !== "discarded" ? (
        <Button size="xs" variant="outline" className="mt-2" onClick={() => actions.onPromote(idea)}>Promote ▸</Button>
      ) : null}
    </div>
  );
}

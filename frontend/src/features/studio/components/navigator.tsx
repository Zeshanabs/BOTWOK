"use client";
import { useState } from "react";
import { AlertTriangle, GitCompare, Plus, RotateCcw, Sparkles } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Checkbox } from "@/components/ui/checkbox";
import { PlatformIcon } from "@/components/data/platform-icon";
import { StatusChip } from "@/components/data/status-chip";
import { SkeletonRows } from "@/features/common/components/query-state";
import { relTime, toItems, validationIssues } from "@/features/common/utils";
import { platformMeta } from "@/lib/platforms";
import { cn } from "@/lib/utils";
import type { ContentItem, ContentVersion } from "../api";
import { useVersions } from "../hooks";
import { budgetFor } from "../platform-rules";
import { versionAuthor, versionTargetLabel } from "./version-compare-dialog";

export interface LiveVariantText { text: string; segments?: string[]; metadata?: Record<string, unknown>; hashtags?: string[] }

/** Left navigator: master, variants (status + limit warnings), versions (pick two → compare, restore), campaign/pillar. */
export function Navigator({ content, selected, onSelect, onAddPlatform, onCompare, onRestore, live, canEdit, issuesOnly, onIssuesOnly }: {
  content: ContentItem; selected: string; onSelect: (id: string) => void; onAddPlatform: () => void;
  onCompare: (a?: string, b?: string) => void; onRestore: (v: ContentVersion) => void; live: (vid: string) => LiveVariantText;
  canEdit: boolean; issuesOnly: boolean; onIssuesOnly: (b: boolean) => void;
}) {
  const versions = useVersions(content.id);
  const list = toItems(versions.data).sort((a, b) => (a.created_at < b.created_at ? 1 : -1));
  const [picked, setPicked] = useState<string[]>([]);
  const variants = (content.variants ?? []).map((v) => {
    const l = live(v.id);
    const over = budgetFor(v.platform, l.text, l).find((x) => x.over);
    const { errors } = validationIssues(v.validation);
    return { v, over, errors };
  }).filter((x) => !issuesOnly || x.over || x.errors.length);

  return (
    <nav aria-label="Content navigator" className="space-y-4 text-sm">
      <section>
        <p className="mb-1 text-[11px] font-semibold uppercase tracking-wide text-muted-foreground">Master</p>
        <button type="button" onClick={() => onSelect("master")} aria-current={selected === "master"}
                className={cn("w-full rounded-md border p-2 text-left hover:bg-accent", selected === "master" && "border-primary bg-primary/5")}>
          <div className="flex items-center gap-2"><StatusChip status={content.status} /><span className="text-xs text-muted-foreground">v{content.current_version}</span>{content.ai_generated && <Sparkles className="h-3 w-3 text-ai" aria-label="AI-assisted" />}</div>
          <p className="mt-1 line-clamp-2 font-medium">{content.title || "Untitled"}</p>
        </button>
      </section>
      <section>
        <div className="mb-1 flex items-center justify-between">
          <p className="text-[11px] font-semibold uppercase tracking-wide text-muted-foreground">Variants</p>
          {canEdit && <Button size="icon-xs" variant="ghost" onClick={onAddPlatform} aria-label="Add platform version" title="Add platform version"><Plus /></Button>}
        </div>
        <label className="mb-1 flex items-center gap-1.5 text-[11px] text-muted-foreground"><Checkbox checked={issuesOnly} onCheckedChange={(c) => onIssuesOnly(c === true)} className="size-3.5" />Show issues only</label>
        {variants.length === 0 && <p className="text-xs text-muted-foreground">{issuesOnly ? "No issues." : "No platform versions yet."}</p>}
        <ul className="space-y-1">
          {variants.map(({ v, over, errors }) => (
            <li key={v.id}>
              <button type="button" onClick={() => onSelect(v.id)} aria-current={selected === v.id}
                      className={cn("flex w-full items-center gap-2 rounded-md px-2 py-1.5 text-left hover:bg-accent", selected === v.id && "bg-primary/5 ring-1 ring-primary")}>
                <PlatformIcon platform={v.platform} size={18} />
                <span className="min-w-0 flex-1 truncate">{platformMeta(v.platform).label}</span>
                {(over || errors.length > 0) && <span className="flex items-center gap-0.5 text-xs text-red-600" title={over ? `${over.label} ${over.used}/${over.limit}` : errors.map((e) => e.message).join("; ")}><AlertTriangle className="h-3 w-3" />{over ? over.used : errors.length}</span>}
                <StatusChip status={v.status} className="shrink-0" />
              </button>
            </li>
          ))}
        </ul>
        {canEdit && <Button size="sm" variant="ghost" className="mt-1 w-full justify-start text-xs" onClick={onAddPlatform}><Plus /> Add platform version</Button>}
      </section>
      <section>
        <div className="mb-1 flex items-center justify-between">
          <p className="text-[11px] font-semibold uppercase tracking-wide text-muted-foreground">Versions</p>
          <Button size="xs" variant="ghost" disabled={list.length < 2} onClick={() => onCompare(picked[1], picked[0])}><GitCompare /> Compare{picked.length === 2 ? " 2" : ""}</Button>
        </div>
        {versions.isLoading && <SkeletonRows rows={3} />}
        {versions.error && <p className="text-xs text-muted-foreground">Version history unavailable.</p>}
        <ul className="max-h-72 space-y-1 overflow-y-auto pr-1">
          {list.map((ver) => (
            <li key={ver.id} className="group flex items-center gap-1.5 rounded px-1 py-1 text-xs hover:bg-accent">
              <Checkbox className="size-3.5" aria-label={`Select v${ver.version} for compare`} checked={picked.includes(ver.id)}
                        onCheckedChange={(c) => setPicked((s) => (c === true ? [...s.filter((x) => x !== ver.id), ver.id].slice(-2) : s.filter((x) => x !== ver.id)))} />
              <span className="font-medium tabular-nums">v{ver.version}</span>
              <span className={cn("min-w-0 flex-1 truncate", ver.author_type === "agent" && "text-ai")}>{versionAuthor(ver)} · {versionTargetLabel(ver, content.variants ?? [])}</span>
              <span className="shrink-0 text-muted-foreground">{relTime(ver.created_at).replace(" ago", "")}</span>
              {canEdit && <Button size="icon-xs" variant="ghost" className="opacity-0 group-hover:opacity-100 focus-visible:opacity-100" aria-label={`Restore v${ver.version}`} title="Restore as new version" onClick={() => onRestore(ver)}><RotateCcw /></Button>}
            </li>
          ))}
        </ul>
      </section>
      {(content.campaign || content.pillar || content.content_type) && (
        <section className="space-y-1 border-t pt-3 text-xs">
          {content.campaign && <p><span className="text-muted-foreground">Campaign</span> {content.campaign.name}</p>}
          {content.pillar && <p className="flex items-center gap-1"><span className="text-muted-foreground">Pillar</span>{content.pillar.color && <span className="h-2 w-2 rounded-full" style={{ background: content.pillar.color }} />}{content.pillar.name}</p>}
          {content.content_type && <p><span className="text-muted-foreground">Type</span> {content.content_type.replace(/_/g, " ")}</p>}
        </section>
      )}
    </nav>
  );
}

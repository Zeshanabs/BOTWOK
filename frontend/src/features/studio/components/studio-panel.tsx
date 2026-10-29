"use client";
import { Sparkles } from "lucide-react";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import type { ContentStatus } from "@/features/common/types";
import type { ContentItem, ContentVariant } from "../api";
import type { Seg } from "../segments";
import { AiPanel } from "./panels/ai-panel";
import { ApprovalPanel } from "./panels/approval-panel";
import { CriticPanel } from "./panels/critic-panel";
import { MediaPanel } from "./panels/media-panel";
import { SchedulePanel } from "./panels/schedule-panel";
import { SeoPanel } from "./panels/seo-panel";
import { SourcesPanel, type PendingSource } from "./panels/sources-panel";

export type PanelTab = "ai" | "sources" | "seo" | "media" | "critic" | "approval" | "schedule";
export const PANEL_TABS: { id: PanelTab; label: string }[] = [
  { id: "ai", label: "AI" }, { id: "sources", label: "Sources" }, { id: "seo", label: "SEO" }, { id: "media", label: "Media" },
  { id: "critic", label: "Critic" }, { id: "approval", label: "Approval" }, { id: "schedule", label: "Schedule" },
];

export interface StudioPanelProps {
  content: ContentItem;
  variant: ContentVariant | null;
  tab: PanelTab;
  onTabChange: (t: PanelTab) => void;
  dirty: boolean;
  flush: () => void;
  liveText: string;
  hashtags: string[];
  onHashtagsChange: (t: string[]) => void;
  segs: Seg[] | null;
  onSegsChange: (s: Seg[]) => void;
  onApplySuggestion: (text: string, field?: string | null) => void;
  onRequestApproval: () => void;
  onTransition: (to: ContentStatus) => void;
  transitionPending: boolean;
  onSelectVariant: (id: string) => void;
  pendingSources: PendingSource[];
  onAddSource: (s: PendingSource) => void;
  onRemoveSource: (id: string) => void;
}

/** Right-hand tabbed panel (AI, Sources, SEO, Media, Critic, Approval, Schedule). */
export function StudioPanel(p: StudioPanelProps) {
  const seed = [p.content.body?.visual_concept, p.content.body?.hook, p.content.title].filter(Boolean).join(" — ");
  return (
    <Tabs value={p.tab} onValueChange={(v) => p.onTabChange(v as PanelTab)} className="gap-3">
      <TabsList className="flex h-auto w-full flex-wrap justify-start">
        {PANEL_TABS.map((t) => (
          <TabsTrigger key={t.id} value={t.id} className="flex-none px-2 text-xs">
            {t.id === "ai" && <Sparkles className="text-ai" />}{t.label}
          </TabsTrigger>
        ))}
      </TabsList>
      <TabsContent value="ai"><AiPanel content={p.content} variant={p.variant} dirty={p.dirty} onBeforeRun={p.flush} pendingSources={p.pendingSources} onSourcesConsumed={() => p.pendingSources.forEach((x) => p.onRemoveSource(x.id))} /></TabsContent>
      <TabsContent value="sources"><SourcesPanel content={p.content} pending={p.pendingSources} onAdd={p.onAddSource} onRemove={p.onRemoveSource} /></TabsContent>
      <TabsContent value="seo"><SeoPanel content={p.content} variant={p.variant} text={p.liveText} hashtags={p.hashtags} onChange={p.onHashtagsChange} /></TabsContent>
      <TabsContent value="media"><MediaPanel content={p.content} variant={p.variant} segs={p.segs} onSegsChange={p.onSegsChange} seedPrompt={seed} /></TabsContent>
      <TabsContent value="critic"><CriticPanel content={p.content} variant={p.variant} onApplySuggestion={p.onApplySuggestion} /></TabsContent>
      <TabsContent value="approval"><ApprovalPanel content={p.content} onRequestApproval={p.onRequestApproval} onTransition={p.onTransition} transitionPending={p.transitionPending} /></TabsContent>
      <TabsContent value="schedule"><SchedulePanel content={p.content} variant={p.variant} onSelectVariant={p.onSelectVariant} /></TabsContent>
    </Tabs>
  );
}

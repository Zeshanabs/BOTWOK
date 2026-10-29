"use client";
import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Hash, Loader2, Plus, Sparkles } from "lucide-react";
import { toast } from "sonner";
import { Button } from "@/components/ui/button";
import { RunCard } from "@/features/common/components/run-card";
import { usePermissions } from "@/features/common/hooks";
import { validationIssues } from "@/features/common/utils";
import { api } from "@/lib/api";
import { platformMeta } from "@/lib/platforms";
import { cn } from "@/lib/utils";
import { contentApi, type ContentItem, type ContentVariant } from "../../api";
import { contentKeys } from "../../hooks";
import { normalizeTag, ruleFor, stripMarkdown } from "../../platform-rules";
import { HashtagInput } from "../hashtag-input";

interface BrandSettings { topics?: { keywords?: string[]; hashtags?: { core?: string[]; campaign?: string[]; banned?: string[] } } }

const STOP = new Set("the a an and or but if then of to in on for with at by from is are was were be been it this that these those you your we our they their as not no yes can will just more most how what why when who into about over than so very".split(" "));

/** Local heuristic: frequent meaningful words → CamelCase hashtags. */
export function heuristicTags(text: string, n = 8): string[] {
  const counts = new Map<string, number>();
  for (const w of stripMarkdown(text).toLowerCase().match(/[a-z][a-z0-9]{3,}/g) ?? []) {
    if (STOP.has(w)) continue;
    counts.set(w, (counts.get(w) ?? 0) + 1);
  }
  return Array.from(counts.entries()).sort((a, b) => b[1] - a[1]).slice(0, n).map(([w]) => `#${w[0].toUpperCase()}${w.slice(1)}`);
}

export function useBrandHashtags(brandId: string) {
  return useQuery({ queryKey: ["brands", brandId, "settings"], queryFn: () => api.get<BrandSettings>(`/brands/${brandId}/settings`), staleTime: 60_000, retry: false });
}

/** SEO / Hashtags tab: counts vs platform caps, banned warnings, brand sets, AI or heuristic suggestions. */
export function SeoPanel({ content, variant, text, hashtags, onChange }: {
  content: ContentItem; variant: ContentVariant | null; text: string; hashtags: string[]; onChange: (tags: string[]) => void;
}) {
  const qc = useQueryClient();
  const { canCreate } = usePermissions();
  const settings = useBrandHashtags(content.brand_id);
  const brandTags = settings.data?.topics?.hashtags ?? {};
  const banned = (brandTags.banned ?? []).map((t) => normalizeTag(t).toLowerCase());
  const [runId, setRunId] = useState<string | null>(null);
  const [local, setLocal] = useState<string[] | null>(null);
  const rule = variant ? ruleFor(variant.platform) : undefined;
  const { errors, warnings } = validationIssues(variant?.validation);
  const tagIssues = [...errors, ...warnings].filter((i) => /hashtag|banned/i.test(`${i.code ?? ""} ${i.field ?? ""} ${i.message}`));
  const have = new Set(hashtags.map((t) => t.toLowerCase()));
  const pool = Array.from(new Set([
    ...(content.body?.hashtags ?? []), ...(content.variants ?? []).flatMap((v) => v.hashtags ?? []), ...(brandTags.core ?? []), ...(brandTags.campaign ?? []), ...(local ?? []),
  ].map(normalizeTag).filter(Boolean)));
  const suggestions = pool.filter((t) => !have.has(t.toLowerCase()) && !banned.includes(t.toLowerCase()));

  const suggest = useMutation({
    mutationFn: () => contentApi.generate(content.id, { mode: "hashtags", platform: variant?.platform, variant_id: variant?.id }),
    onSuccess: (r) => setRunId(r.run_id),
    onError: () => { setLocal(heuristicTags(text)); toast.message("AI hashtag suggestions unavailable — showing local keyword suggestions"); },
  });

  return (
    <div className="space-y-4">
      <div>
        <p className="mb-1.5 text-xs font-medium">Hashtags {variant ? `· ${platformMeta(variant.platform).label}` : "· master"}</p>
        <HashtagInput value={hashtags} onChange={onChange} banned={brandTags.banned} cap={rule?.hashtagCap} recommended={rule?.hashtagRecommended} disabled={!canCreate} />
      </div>
      {(tagIssues.length > 0 || hashtags.some((t) => banned.includes(t.toLowerCase()))) && (
        <ul className="space-y-1 rounded-md border border-destructive/40 bg-destructive/[0.06] p-2 text-xs text-destructive">
          {hashtags.filter((t) => banned.includes(t.toLowerCase())).map((t) => <li key={t}>{t} is on the brand’s banned list</li>)}
          {tagIssues.map((i, k) => <li key={k}>{i.message}</li>)}
        </ul>
      )}
      <div>
        <div className="mb-1.5 flex items-center justify-between">
          <p className="text-xs font-medium">Suggestions</p>
          <div className="flex gap-1">
            <Button size="xs" variant="ghost" onClick={() => setLocal(heuristicTags(text))} disabled={!text.trim()}><Hash /> From text</Button>
            <Button size="xs" variant="outline" onClick={() => suggest.mutate()} disabled={!canCreate || suggest.isPending}>{suggest.isPending ? <Loader2 className="animate-spin" /> : <Sparkles className="text-ai" />} Suggest</Button>
          </div>
        </div>
        {suggestions.length === 0 ? <p className="text-xs text-muted-foreground">No suggestions yet.</p> : (
          <div className="flex flex-wrap gap-1.5">
            {suggestions.map((t) => (
              <button key={t} type="button" disabled={!canCreate} onClick={() => onChange([...hashtags, t])} className={cn("inline-flex items-center gap-1 rounded-full border px-2 py-0.5 text-xs hover:bg-accent", (brandTags.core ?? []).map((x) => normalizeTag(x).toLowerCase()).includes(t.toLowerCase()) && "border-primary/50")}>
                <Plus className="h-3 w-3" />{t}
              </button>
            ))}
          </div>
        )}
        {suggestions.length > 1 && canCreate && <Button size="xs" variant="ghost" className="mt-1" onClick={() => onChange([...hashtags, ...suggestions.slice(0, Math.max(0, (rule?.hashtagCap ?? rule?.hashtagRecommended ?? 5) - hashtags.length))])}>Add set</Button>}
        {(brandTags.core ?? []).length > 0 && <p className="mt-1 text-[11px] text-muted-foreground">Outlined chips are brand core hashtags.</p>}
      </div>
      {runId && <RunCard runId={runId} title="✦ Hashtag suggestions" compact onDone={() => { void qc.invalidateQueries({ queryKey: contentKeys.detail(content.id) }); }} />}
      {(content.body?.keywords ?? []).length > 0 && (
        <div>
          <p className="mb-1 text-xs font-medium">Keywords</p>
          <div className="flex flex-wrap gap-1">{content.body?.keywords?.map((k) => <span key={k} className="rounded bg-muted px-1.5 py-0.5 text-xs">{k}</span>)}</div>
        </div>
      )}
      {rule && <p className="text-[11px] text-muted-foreground">{rule.notes.join(" · ")}</p>}
    </div>
  );
}

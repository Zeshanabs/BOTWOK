"use client";
import { AlertTriangle, Info, Plus, Scissors, Sparkles, Trash2, XCircle } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Textarea } from "@/components/ui/textarea";
import { validationIssues } from "@/features/common/utils";
import { cn } from "@/lib/utils";
import type { ContentVariant } from "../api";
import { countText, ruleFor, splitIntoSegments } from "../platform-rules";
import type { VariantDraft } from "../use-drafts";
import { CharacterBudget } from "./character-budget";
import { HashtagInput } from "./hashtag-input";

/** Centre-column fields for a platform variant: title (yt/pin), text or thread segments, hashtags, budgets, validation, changes made. */
export function VariantFields({ variant, draft, onChange, readOnly, bannedTags }: {
  variant: ContentVariant; draft: VariantDraft; onChange: (p: Partial<VariantDraft>) => void; readOnly: boolean; bannedTags?: string[];
}) {
  const rule = ruleFor(variant.platform);
  const thread = !!rule?.perSegment;
  const segTexts = draft.segs.map((s) => s.text);
  const useSegments = thread && draft.segs.length > 0 && variant.format !== "carousel";
  const { errors, warnings } = validationIssues(variant.validation);
  const fieldErr = (f: string) => errors.filter((e) => e.field === f || e.field?.startsWith(`${f}.`) || e.field?.startsWith(`${f}[`));

  return (
    <div className="space-y-5">
      {(rule?.extraFields ?? []).map((f) => {
        const val = typeof draft.metadata[f.key] === "string" ? (draft.metadata[f.key] as string) : "";
        const used = countText(val, f.mode);
        return (
          <div key={f.key} className="space-y-1.5">
            <div className="flex items-center justify-between"><Label htmlFor={`meta-${f.key}`} className="text-xs uppercase tracking-wide text-muted-foreground">{f.label}</Label><span className={cn("text-xs tabular-nums", used > f.limit ? "text-red-600" : "text-muted-foreground")}>{used}/{f.limit}</span></div>
            <Input id={`meta-${f.key}`} value={val} readOnly={readOnly} aria-invalid={used > f.limit} onChange={(e) => onChange({ metadata: { ...draft.metadata, [f.key]: e.target.value } })} />
          </div>
        );
      })}
      {useSegments ? (
        <div className="space-y-2">
          <div className="flex items-center justify-between">
            <Label className="text-xs uppercase tracking-wide text-muted-foreground">Thread ({draft.segs.length} posts)</Label>
            {!readOnly && <Button size="xs" variant="ghost" onClick={() => onChange({ text: segTexts.join("\n\n"), segs: [] })}>Merge into one post</Button>}
          </div>
          {draft.segs.map((s, i) => {
            const used = countText(s.text, rule?.mode ?? "chars");
            const over = rule ? used > rule.textLimit : false;
            return (
              <div key={i} className="relative">
                <Textarea value={s.text} readOnly={readOnly} rows={3} aria-label={`Post ${i + 1}`} aria-invalid={over}
                          onChange={(e) => onChange({ segs: draft.segs.map((x, j) => (j === i ? { ...x, text: e.target.value } : x)) })} />
                <div className="mt-0.5 flex items-center justify-between text-xs">
                  <span className="text-muted-foreground">{i + 1}/{draft.segs.length}</span>
                  <span className="flex items-center gap-2">
                    <span className={cn("tabular-nums", over ? "font-semibold text-red-600" : "text-muted-foreground")}>{used}/{rule?.textLimit}</span>
                    {!readOnly && draft.segs.length > 1 && <Button size="icon-xs" variant="ghost" aria-label={`Remove post ${i + 1}`} onClick={() => onChange({ segs: draft.segs.filter((_, j) => j !== i) })}><Trash2 /></Button>}
                  </span>
                </div>
              </div>
            );
          })}
          {!readOnly && <Button size="sm" variant="outline" onClick={() => onChange({ segs: [...draft.segs, { text: "", rest: {} }] })}><Plus /> Add post</Button>}
        </div>
      ) : (
        <div className="space-y-1.5">
          <div className="flex items-center justify-between">
            <Label htmlFor={`text-${variant.id}`} className="text-xs uppercase tracking-wide text-muted-foreground">{rule?.textLabel ?? "Text"}</Label>
            {thread && !readOnly && rule && countText(draft.text, rule.mode) > rule.textLimit && (
              <Button size="xs" variant="ghost" onClick={() => onChange({ segs: splitIntoSegments(draft.text, variant.platform).map((t) => ({ text: t, rest: {} })), stringMode: true })}><Scissors /> Split into thread</Button>
            )}
          </div>
          <Textarea id={`text-${variant.id}`} value={draft.text} readOnly={readOnly} rows={10} className="font-[450] leading-relaxed" aria-invalid={fieldErr("text").length > 0}
                    onChange={(e) => onChange({ text: e.target.value })} placeholder={`Write the ${rule?.textLabel.toLowerCase() ?? "text"}…`} />
          {fieldErr("text").map((e, i) => <p key={i} className="text-xs text-red-600">{e.message}</p>)}
        </div>
      )}
      <CharacterBudget platform={variant.platform} text={draft.text} segments={useSegments ? segTexts : undefined} metadata={draft.metadata} hashtags={draft.hashtags} />
      <div className="space-y-1.5">
        <Label className="text-xs uppercase tracking-wide text-muted-foreground">Hashtags</Label>
        <HashtagInput value={draft.hashtags} onChange={(h) => onChange({ hashtags: h })} banned={bannedTags} cap={rule?.hashtagCap} recommended={rule?.hashtagRecommended} disabled={readOnly} />
      </div>
      {(errors.length > 0 || warnings.length > 0) && (
        <div className="space-y-1 rounded-md border p-2 text-xs" aria-label="Platform validation">
          <p className="font-medium">Platform validation <span className="font-normal text-muted-foreground">(last server check)</span></p>
          {errors.map((e, i) => <p key={`e${i}`} className="flex items-start gap-1.5 text-red-700 dark:text-red-300"><XCircle className="mt-0.5 h-3.5 w-3.5 shrink-0" />{e.message}{e.code && <span className="font-mono text-muted-foreground">{e.code}</span>}</p>)}
          {warnings.map((w, i) => <p key={`w${i}`} className="flex items-start gap-1.5 text-amber-700 dark:text-amber-300"><AlertTriangle className="mt-0.5 h-3.5 w-3.5 shrink-0" />{w.message}</p>)}
        </div>
      )}
      {(variant.changes_made ?? []).length > 0 && (
        <div className="rounded-md bg-ai/10 p-2 text-xs">
          <p className="mb-1 flex items-center gap-1 font-medium"><Sparkles className="h-3.5 w-3.5 text-ai" /> What the repurposer changed</p>
          <ul className="list-disc space-y-0.5 pl-5">{variant.changes_made?.map((c, i) => <li key={i}>{c}</li>)}</ul>
        </div>
      )}
      {rule && <p className="flex items-start gap-1.5 text-[11px] text-muted-foreground"><Info className="mt-0.5 h-3 w-3 shrink-0" />{rule.notes.join(" · ")}</p>}
    </div>
  );
}

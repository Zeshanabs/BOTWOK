"use client";
import { ImagePlus, Sparkles } from "lucide-react";
import { Button } from "@/components/ui/button";
import { MediaThumb } from "@/features/media/components/media-thumb";
import type { ContentAsset } from "../api";

/** Horizontal strip of attached media with alt-text status. */
export function MediaStrip({ assets, onAdd, onGenerate, disabled }: { assets: ContentAsset[]; onAdd?: () => void; onGenerate?: () => void; disabled?: boolean }) {
  const sorted = [...assets].sort((a, b) => a.position - b.position);
  const images = sorted.filter((a) => (a.media?.kind ?? "image") === "image");
  const described = images.filter((a) => (a.alt_text ?? a.media?.alt_text ?? "").trim()).length;
  return (
    <div className="space-y-1.5">
      <div className="flex flex-wrap items-center gap-2">
        {sorted.map((a, i) => (
          <div key={a.id ?? a.media_asset_id} className="relative">
            <MediaThumb asset={{ id: a.media_asset_id, ...(a.media ?? {}), alt_text: a.alt_text ?? a.media?.alt_text }} className="h-16 w-16" />
            <span className="absolute left-1 top-1 rounded bg-black/60 px-1 text-[10px] text-white">{i + 1}</span>
            {a.media?.ai_generated && <Sparkles className="absolute bottom-1 right-1 h-3 w-3 text-white drop-shadow" aria-label="AI-generated" />}
          </div>
        ))}
        {onAdd && <Button type="button" variant="outline" size="sm" className="h-16 w-16 flex-col gap-1 text-xs" onClick={onAdd} disabled={disabled}><ImagePlus /> Add</Button>}
        {onGenerate && <Button type="button" variant="outline" size="sm" className="h-16 w-16 flex-col gap-1 text-xs" onClick={onGenerate} disabled={disabled}><Sparkles className="text-ai" /> AI</Button>}
      </div>
      {images.length > 0 && (
        <p className={described < images.length ? "text-xs text-warning" : "text-xs text-muted-foreground"}>
          Alt text {described < images.length ? "⚠" : "✓"} {described} of {images.length} image{images.length === 1 ? "" : "s"} described
        </p>
      )}
    </div>
  );
}

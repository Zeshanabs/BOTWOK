"use client";
import { useState } from "react";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { ArrowDown, ArrowUp, Crop, Eraser, ImagePlus, Library, MoreHorizontal, Plus, Sparkles, Trash2, Unlink } from "lucide-react";
import { toast } from "sonner";
import { Button } from "@/components/ui/button";
import { Dialog, DialogContent, DialogDescription, DialogHeader, DialogTitle } from "@/components/ui/dialog";
import { DropdownMenu, DropdownMenuContent, DropdownMenuItem, DropdownMenuTrigger } from "@/components/ui/dropdown-menu";
import { Input } from "@/components/ui/input";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { QueryError, SkeletonRows } from "@/features/common/components/query-state";
import { usePermissions } from "@/features/common/hooks";
import { errorMessage, isNotAvailable, toItems } from "@/features/common/utils";
import { assetName, mediaApi, TRANSFORM_PRESETS, type MediaAsset } from "@/features/media/api";
import { GenerateImageDialog } from "@/features/media/components/generate-image-dialog";
import { MediaThumb } from "@/features/media/components/media-thumb";
import { UploadButton } from "@/features/media/components/upload-button";
import { useMediaList } from "@/features/media/hooks";
import { platformMeta } from "@/lib/platforms";
import { contentApi, type ContentAsset, type ContentItem, type ContentVariant } from "../../api";
import { contentKeys } from "../../hooks";
import type { Seg } from "../../segments";

/** Media tab: attached assets, upload, library, AI generation, resize/remove-bg, carousel builder. */
export function MediaPanel({ content, variant, segs, onSegsChange, seedPrompt }: {
  content: ContentItem; variant: ContentVariant | null; segs: Seg[] | null; onSegsChange: (s: Seg[]) => void; seedPrompt: string;
}) {
  const qc = useQueryClient();
  const { canCreate } = usePermissions();
  const [genOpen, setGenOpen] = useState(false);
  const [libOpen, setLibOpen] = useState(false);
  const assets: ContentAsset[] = [...(variant?.assets ?? []), ...(content.assets ?? []).filter((a) => !a.variant_id)];
  const refresh = () => void qc.invalidateQueries({ queryKey: contentKeys.detail(content.id) });
  const attach = useMutation({
    mutationFn: (m: MediaAsset) => contentApi.attachAsset(content.id, { media_asset_id: m.id, variant_id: variant?.id ?? null, role: variant?.format === "carousel" ? "carousel_slide" : "primary", position: assets.length, alt_text: m.alt_text ?? null }),
    onSuccess: () => { toast.success("Media attached"); refresh(); },
    onError: (e) => toast.error(`Couldn't attach: ${errorMessage(e)}`),
  });
  const detach = useMutation({
    mutationFn: (a: ContentAsset) => contentApi.detachAsset(content.id, a.id ?? a.media_asset_id),
    onSuccess: () => { toast.success("Media detached"); refresh(); },
    onError: (e) => toast.error(isNotAvailable(e) ? "Detaching isn't supported by this backend yet" : errorMessage(e)),
  });
  const transform = useMutation({
    mutationFn: ({ id, platform, format, aspect }: { id: string; platform: string; format: string; aspect?: string }) => mediaApi.transform(id, { platform, format, aspect }),
    onSuccess: () => { toast.success("Resize queued — the derived file appears in the Media Library"); void qc.invalidateQueries({ queryKey: ["media"] }); },
    onError: (e) => toast.error(isNotAvailable(e) ? "Resizing isn't available on this backend yet" : errorMessage(e)),
  });
  const removeBg = useMutation({
    mutationFn: (id: string) => mediaApi.removeBackground(id),
    onSuccess: () => { toast.success("Background removal queued"); void qc.invalidateQueries({ queryKey: ["media"] }); },
    onError: (e) => toast.error(isNotAvailable(e) ? "Background removal isn't available (no provider configured)" : errorMessage(e)),
  });
  const platformPresets = TRANSFORM_PRESETS.filter((p) => !variant || p.platform === variant.platform);
  const isCarousel = (variant?.format ?? content.master_format) === "carousel";

  return (
    <div className="space-y-4">
      <div className="flex flex-wrap gap-2">
        <UploadButton brandId={content.brand_id} onUploaded={(list) => list.forEach((m) => attach.mutate(m))} />
        <Button size="sm" variant="outline" onClick={() => setLibOpen(true)} disabled={!canCreate}><Library /> Library</Button>
        <Button size="sm" variant="outline" onClick={() => setGenOpen(true)} disabled={!canCreate}><Sparkles className="text-ai" /> Generate</Button>
      </div>
      <p className="text-xs text-muted-foreground">Attached to {variant ? `${platformMeta(variant.platform).label} version` : "master"}{variant ? " (+ master media)" : ""}</p>
      {assets.length === 0 ? <p className="rounded-md border border-dashed p-3 text-sm text-muted-foreground">No media yet. Upload, pick from the library, or generate an image.</p> : (
        <ul className="space-y-2">
          {assets.map((a) => (
            <li key={a.id ?? a.media_asset_id} className="flex items-center gap-2 rounded-md border p-1.5">
              <MediaThumb asset={{ id: a.media_asset_id, ...(a.media ?? {}) }} className="h-12 w-12" />
              <div className="min-w-0 flex-1 text-xs">
                <p className="truncate font-medium">{a.role.replace(/_/g, " ")} · #{a.position + 1}{a.media?.ai_generated && <span className="ml-1 text-ai">✦ AI</span>}</p>
                <p className={(a.alt_text ?? a.media?.alt_text) ? "truncate text-muted-foreground" : "text-warning"}>{a.alt_text ?? a.media?.alt_text ?? "No alt text"}</p>
                {a.media?.width && <p className="text-muted-foreground">{a.media.width}×{a.media.height}</p>}
              </div>
              {canCreate && (
                <DropdownMenu>
                  <DropdownMenuTrigger asChild><Button size="icon-sm" variant="ghost" aria-label="Media actions"><MoreHorizontal /></Button></DropdownMenuTrigger>
                  <DropdownMenuContent align="end">
                    {platformPresets.map((p) => <DropdownMenuItem key={p.platform + p.format + (p.aspect ?? "")} onClick={() => transform.mutate({ id: a.media_asset_id, platform: p.platform, format: p.format, aspect: p.aspect })}><Crop /> Resize: {p.label}</DropdownMenuItem>)}
                    <DropdownMenuItem onClick={() => removeBg.mutate(a.media_asset_id)}><Eraser /> Remove background</DropdownMenuItem>
                    <DropdownMenuItem onClick={() => detach.mutate(a)}><Unlink /> Detach</DropdownMenuItem>
                  </DropdownMenuContent>
                </DropdownMenu>
              )}
            </li>
          ))}
        </ul>
      )}
      {isCarousel && variant && segs && (
        <CarouselBuilder segs={segs} onChange={onSegsChange} assets={assets} disabled={!canCreate} />
      )}
      {isCarousel && !variant && <p className="text-xs text-muted-foreground">Carousel slides are built per platform version — select a variant tab.</p>}
      <GenerateImageDialog open={genOpen} onOpenChange={setGenOpen} brandId={content.brand_id} seedPrompt={seedPrompt} onPick={(m) => attach.mutate(m)} pickLabel="Attach" />
      <LibraryPicker open={libOpen} onOpenChange={setLibOpen} brandId={content.brand_id} onPick={(m) => attach.mutate(m)} />
    </div>
  );
}

function CarouselBuilder({ segs, onChange, assets, disabled }: { segs: Seg[]; onChange: (s: Seg[]) => void; assets: ContentAsset[]; disabled?: boolean }) {
  const move = (i: number, d: number) => { const n = [...segs]; const [x] = n.splice(i, 1); n.splice(i + d, 0, x); onChange(n); };
  return (
    <section aria-labelledby="carousel-h" className="space-y-2">
      <div className="flex items-center justify-between">
        <h3 id="carousel-h" className="text-xs font-semibold uppercase tracking-wide text-muted-foreground">Carousel slides ({segs.length})</h3>
        <Button size="xs" variant="outline" disabled={disabled} onClick={() => onChange([...segs, { text: "", rest: {} }])}><Plus /> Slide</Button>
      </div>
      {segs.length === 0 && <p className="text-xs text-muted-foreground">No slides yet.</p>}
      <ol className="space-y-2">
        {segs.map((s, i) => {
          const media = assets.find((a) => a.media_asset_id === s.media_asset_id);
          return (
            <li key={i} className="flex gap-2 rounded-md border p-1.5">
              <div className="flex w-12 flex-col items-center gap-1">
                {media ? <MediaThumb asset={{ id: media.media_asset_id, ...(media.media ?? {}) }} className="h-12 w-12" /> : <div className="flex h-12 w-12 items-center justify-center rounded-md bg-muted"><ImagePlus className="h-4 w-4 text-muted-foreground" /></div>}
                <span className="text-[10px] text-muted-foreground">{i + 1}</span>
              </div>
              <div className="min-w-0 flex-1 space-y-1">
                <Input value={s.text} onChange={(e) => onChange(segs.map((x, j) => (j === i ? { ...x, text: e.target.value } : x)))} placeholder={`Slide ${i + 1} text`} className="h-8 text-xs" disabled={disabled} aria-label={`Slide ${i + 1} text`} />
                <Select value={s.media_asset_id ?? "none"} onValueChange={(v) => onChange(segs.map((x, j) => (j === i ? { ...x, media_asset_id: v === "none" ? null : v } : x)))} disabled={disabled}>
                  <SelectTrigger size="sm" className="h-7 w-full text-xs" aria-label={`Slide ${i + 1} media`}><SelectValue /></SelectTrigger>
                  <SelectContent><SelectItem value="none">No media</SelectItem>{assets.map((a, k) => <SelectItem key={a.media_asset_id} value={a.media_asset_id}>Media #{k + 1}</SelectItem>)}</SelectContent>
                </Select>
              </div>
              <div className="flex flex-col">
                <Button size="icon-xs" variant="ghost" aria-label="Move up" disabled={disabled || i === 0} onClick={() => move(i, -1)}><ArrowUp /></Button>
                <Button size="icon-xs" variant="ghost" aria-label="Move down" disabled={disabled || i === segs.length - 1} onClick={() => move(i, 1)}><ArrowDown /></Button>
                <Button size="icon-xs" variant="ghost" aria-label="Remove slide" disabled={disabled} onClick={() => onChange(segs.filter((_, j) => j !== i))}><Trash2 /></Button>
              </div>
            </li>
          );
        })}
      </ol>
    </section>
  );
}

function LibraryPicker({ open, onOpenChange, brandId, onPick }: { open: boolean; onOpenChange: (o: boolean) => void; brandId: string; onPick: (m: MediaAsset) => void }) {
  const [kind, setKind] = useState("all");
  const list = useMediaList({ brand_id: brandId, kind: kind === "all" ? undefined : kind });
  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="max-h-[85vh] overflow-y-auto sm:max-w-3xl">
        <DialogHeader><DialogTitle>Pick from Media Library</DialogTitle><DialogDescription>Selecting attaches the asset; the original stays in the library.</DialogDescription></DialogHeader>
        <Select value={kind} onValueChange={setKind}><SelectTrigger className="w-40" aria-label="Type"><SelectValue /></SelectTrigger>
          <SelectContent><SelectItem value="all">All types</SelectItem><SelectItem value="image">Images</SelectItem><SelectItem value="video">Videos</SelectItem></SelectContent></Select>
        {open && list.isLoading && <SkeletonRows rows={3} />}
        {list.error && <QueryError error={list.error} onRetry={() => list.refetch()} notAvailableText="The media library isn't available yet." />}
        {list.data && toItems(list.data).length === 0 && <p className="text-sm text-muted-foreground">The library is empty.</p>}
        <div className="grid grid-cols-3 gap-2 sm:grid-cols-5">
          {toItems(list.data).map((m) => (
            <button key={m.id} type="button" className="group space-y-1 text-left" onClick={() => { onPick(m); onOpenChange(false); }}>
              <MediaThumb asset={m} className="aspect-square w-full ring-primary group-hover:ring-2" />
              <p className="truncate text-[11px] text-muted-foreground">{assetName(m)}{m.ai_generated ? " · ✦" : ""}</p>
            </button>
          ))}
        </div>
        <Button variant="ghost" size="sm" className="justify-self-start" onClick={() => onOpenChange(false)}>Close</Button>
      </DialogContent>
    </Dialog>
  );
}

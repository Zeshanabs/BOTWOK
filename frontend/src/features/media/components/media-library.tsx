"use client";
import { useDeferredValue, useState } from "react";
import Link from "next/link";
import { useInfiniteQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { Crop, Download, Eraser, ImageIcon, Loader2, Search, Sparkles, Trash2, UploadCloud } from "lucide-react";
import { toast } from "sonner";
import { Button } from "@/components/ui/button";
import { Checkbox } from "@/components/ui/checkbox";
import { DropdownMenu, DropdownMenuContent, DropdownMenuItem, DropdownMenuLabel, DropdownMenuTrigger } from "@/components/ui/dropdown-menu";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { Sheet, SheetContent, SheetDescription, SheetHeader, SheetTitle } from "@/components/ui/sheet";
import { Skeleton } from "@/components/ui/skeleton";
import { Textarea } from "@/components/ui/textarea";
import { EmptyState } from "@/components/shared/empty-state";
import { PageHeader } from "@/components/shared/page-header";
import { PlatformIcon } from "@/components/shared/platform-icon";
import { AiBadge } from "@/features/common/components/ai-badge";
import { ConfirmDialog } from "@/features/common/components/confirm-dialog";
import { QueryError, SkeletonRows } from "@/features/common/components/query-state";
import { useActiveBrand, useBrands, usePermissions, useWorkspacePath } from "@/features/common/hooks";
import type { ListResponse } from "@/features/common/types";
import { errorMessage, errorStatus, fmtDate, fmtUsd, isNotAvailable, toItems } from "@/features/common/utils";
import { cn } from "@/lib/utils";
import { aspectLabel, assetName, fmtBytes, mediaApi, TRANSFORM_PRESETS, type MediaAsset, type MediaFilters } from "../api";
import { useMediaAsset, useMediaList, useMediaUrl, useUpload } from "../hooks";
import { GenerateImageDialog } from "./generate-image-dialog";
import { MediaThumb } from "./media-thumb";
import { UploadButton } from "./upload-button";

const ALL = "all";

/** Media Library (doc 24 §13): filters, grid with usage and provenance, drop-to-upload, detail Sheet, generate, bulk delete. */
export function MediaLibrary() {
  const qc = useQueryClient();
  const { brandId } = useActiveBrand();
  const brands = toItems(useBrands().data);
  const { canCreate, canManage } = usePermissions();
  const [kind, setKind] = useState(ALL);
  const [source, setSource] = useState(ALL);
  const [brandFilter, setBrandFilter] = useState<string>("current");
  const [q, setQ] = useState("");
  const dq = useDeferredValue(q.trim());
  const [openId, setOpenId] = useState<string | null>(null);
  const [genOpen, setGenOpen] = useState(false);
  const [selected, setSelected] = useState<Set<string>>(new Set());
  const [bulkConfirm, setBulkConfirm] = useState(false);
  const [dragging, setDragging] = useState(false);
  const { upload, isUploading } = useUpload(brandId);
  const filters: MediaFilters = { kind: kind === ALL ? undefined : kind, source: source === ALL ? undefined : source, brand_id: brandFilter === "current" ? brandId : brandFilter === ALL ? undefined : brandFilter, q: dq || undefined };
  const list = useInfiniteQuery({
    queryKey: ["media", "list", filters],
    queryFn: ({ pageParam }) => mediaApi.list({ ...filters, cursor: pageParam }),
    initialPageParam: undefined as string | undefined,
    getNextPageParam: (last: ListResponse<MediaAsset>) => (Array.isArray(last) ? undefined : last.next_cursor ?? undefined),
    refetchInterval: (query) => ((query.state.data?.pages ?? []).some((p) => toItems(p).some((a) => a.status === "processing")) ? 4000 : false),
  });
  const assets = (list.data?.pages ?? []).flatMap((p) => toItems(p));
  const total = (list.data?.pages?.[0] && !Array.isArray(list.data.pages[0]) ? list.data.pages[0].total : undefined) ?? assets.length;
  const filtered = kind !== ALL || source !== ALL || !!dq || brandFilter !== "current";
  const clear = () => { setKind(ALL); setSource(ALL); setQ(""); setBrandFilter("current"); };
  const bulkDelete = useMutation({
    mutationFn: async (ids: string[]) => {
      const failures: string[] = [];
      for (const id of ids) { try { await mediaApi.remove(id); } catch (e) { failures.push(errorMessage(e)); } }
      return { failures, ok: ids.length - failures.length };
    },
    onSuccess: ({ failures, ok }) => {
      if (ok) toast.success(`Deleted ${ok} asset${ok === 1 ? "" : "s"}`);
      if (failures.length) toast.error(`${failures.length} not deleted: ${failures[0]}`);
      setSelected(new Set()); setBulkConfirm(false);
      void qc.invalidateQueries({ queryKey: ["media"] });
    },
  });
  const toggle = (id: string) => setSelected((s) => { const n = new Set(s); if (n.has(id)) n.delete(id); else n.add(id); return n; });

  return (
    <div onDragOver={(e) => { if (canCreate && e.dataTransfer.types.includes("Files")) { e.preventDefault(); setDragging(true); } }}
         onDragLeave={(e) => { if (e.currentTarget === e.target) setDragging(false); }}
         onDrop={(e) => { if (!canCreate) return; e.preventDefault(); setDragging(false); const files = Array.from(e.dataTransfer.files); if (files.length) void upload(files); }}
         className="relative">
      {dragging && <div className="pointer-events-none absolute inset-0 z-20 flex items-center justify-center rounded-xl border-2 border-dashed border-primary bg-primary/5 text-primary"><UploadCloud className="mr-2 h-6 w-6" /> Drop to upload</div>}
      <PageHeader title="Media Library" description="Uploaded and generated media, renditions and where each asset is used."
                  actions={canCreate && <>
                    <Button variant="outline" size="sm" onClick={() => setGenOpen(true)}><Sparkles className="text-ai" /> Generate image</Button>
                    <UploadButton brandId={brandId} variant="default" />
                  </>} />
      <div className="mb-4 flex flex-wrap items-center gap-2">
        <div className="relative w-full sm:w-56"><Search className="absolute left-2 top-2.5 h-4 w-4 text-muted-foreground" /><Input value={q} onChange={(e) => setQ(e.target.value)} placeholder="Search files, prompts…" className="pl-8" aria-label="Search media" /></div>
        <Select value={kind} onValueChange={setKind}><SelectTrigger className="w-32" aria-label="Type"><SelectValue /></SelectTrigger>
          <SelectContent><SelectItem value={ALL}>All types</SelectItem><SelectItem value="image">Images</SelectItem><SelectItem value="video">Videos</SelectItem><SelectItem value="document">Documents</SelectItem></SelectContent></Select>
        <div className="flex rounded-md border p-0.5 text-xs" role="radiogroup" aria-label="Source">
          {[{ v: ALL, l: "All" }, { v: "upload", l: "Uploaded" }, { v: "generated", l: "✦ Generated" }].map((o) => (
            <button key={o.v} type="button" role="radio" aria-checked={source === o.v} onClick={() => setSource(o.v)} className={cn("rounded px-2 py-1", source === o.v && "bg-secondary")}>{o.l}</button>
          ))}
        </div>
        <Select value={brandFilter} onValueChange={setBrandFilter}><SelectTrigger className="w-40" aria-label="Brand"><SelectValue /></SelectTrigger>
          <SelectContent><SelectItem value="current">Current brand</SelectItem><SelectItem value={ALL}>All brands</SelectItem>{brands.map((b) => <SelectItem key={b.id} value={b.id}>{b.name}</SelectItem>)}</SelectContent></Select>
        {filtered && <Button size="sm" variant="ghost" onClick={clear}>Clear filters</Button>}
        {isUploading && <span className="flex items-center gap-1 text-xs text-muted-foreground"><Loader2 className="h-3 w-3 animate-spin" /> Uploading…</span>}
      </div>
      {selected.size > 0 && (
        <div className="mb-3 flex items-center gap-2 rounded-md border bg-muted/50 px-3 py-2 text-sm">
          <span>{selected.size} selected</span>
          <Button size="xs" variant="ghost" onClick={() => setSelected(new Set())}>Clear</Button>
          {canManage && <Button size="xs" variant="destructive" className="ml-auto" onClick={() => setBulkConfirm(true)}><Trash2 /> Delete</Button>}
        </div>
      )}
      {list.isLoading ? (
        <div className="grid grid-cols-3 gap-3 sm:grid-cols-4 lg:grid-cols-6" aria-busy="true">{Array.from({ length: 12 }).map((_, i) => <Skeleton key={i} className="aspect-square w-full" />)}</div>
      ) : list.error ? (
        <QueryError error={list.error} onRetry={() => list.refetch()} title="Couldn't load media" notAvailableText="The media API isn't available on this backend yet." />
      ) : assets.length === 0 ? (
        filtered ? <EmptyState icon={Search} title="No media matches these filters" action={{ label: "Clear filters", onClick: clear }} />
          : <EmptyState icon={ImageIcon} title="Drop files here or generate an image." description="Uploads are stored locally (MinIO) and processed into thumbnails and platform renditions." action={canCreate ? { label: "Generate image", onClick: () => setGenOpen(true) } : undefined} />
      ) : (
        <>
          <ul className="grid grid-cols-3 gap-3 sm:grid-cols-4 lg:grid-cols-6">
            {assets.map((a) => (
              <li key={a.id} className="group relative">
                <button type="button" className="block w-full text-left" onClick={() => setOpenId(a.id)} aria-label={`Open ${assetName(a)}`}>
                  <MediaThumb asset={a} className={cn("aspect-square w-full ring-primary transition group-hover:ring-2", selected.has(a.id) && "ring-2")} />
                  <p className="mt-1 truncate text-xs font-medium">{a.ai_generated && <Sparkles className="mr-0.5 inline h-3 w-3 text-ai" />}{assetName(a)}</p>
                  <p className="truncate text-[11px] text-muted-foreground">
                    {a.status === "failed" ? <span className="text-destructive">{a.error ?? "failed"}</span> : <>
                      {a.width && a.height ? `${a.width}×${a.height}` : a.kind}{aspectLabel(a.width, a.height) ? ` · ${aspectLabel(a.width, a.height)}` : ""}
                      {" · "}{a.usage_count != null ? (a.usage_count ? `used ${a.usage_count}×` : "unused") : a.source === "derived" ? `${a.platform_target ?? "derived"} rendition` : fmtBytes(a.bytes)}
                    </>}
                  </p>
                </button>
                {canManage && <Checkbox checked={selected.has(a.id)} onCheckedChange={() => toggle(a.id)} aria-label="Select" className={cn("absolute left-1.5 top-1.5 bg-background", !selected.has(a.id) && "opacity-0 group-hover:opacity-100 focus-visible:opacity-100")} />}
              </li>
            ))}
          </ul>
          <div className="mt-4 flex items-center justify-between text-xs text-muted-foreground">
            <span>Showing {assets.length}{total > assets.length ? ` of ${total}` : ""}</span>
            {list.hasNextPage && <Button size="sm" variant="outline" onClick={() => list.fetchNextPage()} disabled={list.isFetchingNextPage}>{list.isFetchingNextPage && <Loader2 className="animate-spin" />} Load more</Button>}
          </div>
        </>
      )}
      <AssetDetailSheet id={openId} onOpenChange={(o) => !o && setOpenId(null)} />
      <GenerateImageDialog open={genOpen} onOpenChange={setGenOpen} brandId={brandId} onPick={() => toast.success("Kept in the library")} pickLabel="Keep" />
      <ConfirmDialog open={bulkConfirm} onOpenChange={setBulkConfirm} destructive title={`Delete ${selected.size} asset${selected.size === 1 ? "" : "s"}?`} confirmLabel="Delete" pending={bulkDelete.isPending}
                     onConfirm={() => bulkDelete.mutate(Array.from(selected))}
                     description={<p>Files are removed from storage. Assets attached to scheduled posts are refused by the server and stay.</p>} />
    </div>
  );
}

/** Asset detail: metadata, provenance, alt text, renditions, usage, resize, remove background, download, delete. */
export function AssetDetailSheet({ id, onOpenChange }: { id: string | null; onOpenChange: (o: boolean) => void }) {
  const qc = useQueryClient();
  const ws = useWorkspacePath();
  const { canCreate, canManage } = usePermissions();
  const asset = useMediaAsset(id);
  const a = asset.data;
  const url = useMediaUrl(a?.id, a?.url ?? null);
  const derivedQ = useMediaList({ derived_from_id: a?.id }, !!a?.id && !a?.derived);
  const derived = a?.derived ?? (a ? toItems(derivedQ.data) : []);
  const href = a?.url ?? url.data?.url ?? null;
  const [alt, setAlt] = useState<string | null>(null);
  const [altReadOnly, setAltReadOnly] = useState(false);
  const [confirmDel, setConfirmDel] = useState(false);
  const altValue = alt ?? a?.alt_text ?? "";
  const saveAlt = useMutation({
    mutationFn: () => mediaApi.patch(a!.id, { alt_text: altValue }),
    onSuccess: (m) => { toast.success("Alt text saved"); setAlt(null); if (m?.id) qc.setQueryData(["media", m.id], m); void qc.invalidateQueries({ queryKey: ["media", "list"] }); },
    onError: (e) => { if (isNotAvailable(e)) { setAltReadOnly(true); toast.message("Editing alt text isn't supported by this backend yet"); } else toast.error(errorMessage(e)); },
  });
  const transform = useMutation({
    mutationFn: (p: { platform: string; format: string; aspect?: string }) => mediaApi.transform(a!.id, p),
    onSuccess: () => { toast.success("Rendition queued"); void qc.invalidateQueries({ queryKey: ["media"] }); },
    onError: (e) => toast.error(isNotAvailable(e) ? "Resizing isn't available on this backend yet" : errorMessage(e)),
  });
  const removeBg = useMutation({
    mutationFn: () => mediaApi.removeBackground(a!.id),
    onSuccess: () => { toast.success("Background removal queued"); void qc.invalidateQueries({ queryKey: ["media"] }); },
    onError: (e) => toast.error(isNotAvailable(e) ? "Background removal isn't available — no provider is configured" : errorMessage(e)),
  });
  const del = useMutation({
    mutationFn: () => mediaApi.remove(a!.id),
    onSuccess: () => { toast.success("Asset deleted"); setConfirmDel(false); onOpenChange(false); void qc.invalidateQueries({ queryKey: ["media"] }); },
    onError: (e) => { setConfirmDel(false); toast.error(errorStatus(e) === 409 ? `Can't delete: ${errorMessage(e)}` : errorMessage(e)); },
  });

  return (
    <Sheet open={!!id} onOpenChange={(o) => { if (!o) { setAlt(null); setAltReadOnly(false); } onOpenChange(o); }}>
      <SheetContent className="w-full overflow-y-auto sm:max-w-md">
        <SheetHeader>
          <SheetTitle className="flex items-center gap-2 pr-6">{a?.ai_generated && <Sparkles className="h-4 w-4 text-ai" />}<span className="truncate">{a ? assetName(a) : "Asset"}</span></SheetTitle>
          <SheetDescription>{a ? `${a.source.replace(/_/g, " ")} · ${fmtDate(a.created_at)} · ${a.width && a.height ? `${a.width}×${a.height}` : a.kind} · ${fmtBytes(a.bytes)}` : "Loading…"}</SheetDescription>
        </SheetHeader>
        <div className="space-y-5 px-4 pb-6">
          {asset.isLoading && <><Skeleton className="aspect-square w-full" /><SkeletonRows rows={3} /></>}
          {asset.error && <QueryError error={asset.error} onRetry={() => asset.refetch()} />}
          {a && (
            <>
              <MediaThumb asset={a} fit="contain" className="aspect-square w-full" />
              {a.status === "failed" && <p className="rounded-md bg-destructive/[0.06] p-2 text-sm text-destructive">Processing failed: {a.error ?? "unknown error"}</p>}
              {a.ai_generated && (
                <section className="space-y-1 text-xs">
                  <div className="flex items-center gap-2"><AiBadge meta={{ provider: a.provider, model: a.model, cost_usd: a.cost_usd, run_id: a.ai_run_id }} label="Generated" /><span className="text-muted-foreground">{[a.provider, a.model].filter(Boolean).join(" · ")}</span></div>
                  {a.prompt && <p className="rounded-md bg-muted p-2"><span className="text-muted-foreground">Prompt: </span>{a.prompt}</p>}
                  <p className="text-muted-foreground">{a.seed != null && `seed ${a.seed} · `}{a.cost_usd != null && `cost ${fmtUsd(a.cost_usd)}`}</p>
                </section>
              )}
              <section className="space-y-1.5">
                <Label htmlFor="alt">Alt text {a.alt_text_source === "ai" && <span className="text-xs text-ai">✦ AI-drafted</span>}</Label>
                <Textarea id="alt" rows={3} value={altValue} onChange={(e) => setAlt(e.target.value)} readOnly={!canCreate || altReadOnly} placeholder="Describe the image for screen readers" />
                {altReadOnly && <p className="text-xs text-muted-foreground">Alt text is read-only on this backend.</p>}
                {canCreate && !altReadOnly && <Button size="sm" variant="outline" disabled={alt == null || saveAlt.isPending} onClick={() => saveAlt.mutate()}>{saveAlt.isPending && <Loader2 className="animate-spin" />} Save alt text</Button>}
              </section>
              <section>
                <h3 className="mb-1.5 text-xs font-semibold uppercase tracking-wide text-muted-foreground">Derived files</h3>
                {derivedQ.isLoading && !a.derived ? <Skeleton className="h-10" /> : derived.length === 0 ? <p className="text-xs text-muted-foreground">No renditions yet.</p> : (
                  <ul className="space-y-1.5">{derived.map((d) => (
                    <li key={d.id} className="flex items-center gap-2 text-xs">
                      <MediaThumb asset={d} className="h-10 w-10" />
                      <span className="flex-1">{d.width && d.height ? `${d.width}×${d.height}` : d.kind}{d.platform_target && <> · <PlatformIcon platform={d.platform_target} size={14} className="inline-flex align-middle" /></>}{aspectLabel(d.width, d.height) ? ` · ${aspectLabel(d.width, d.height)}` : ""}</span>
                      {d.status && d.status !== "ready" && <span className="text-muted-foreground">{d.status}</span>}
                    </li>))}
                  </ul>
                )}
              </section>
              <section>
                <h3 className="mb-1.5 text-xs font-semibold uppercase tracking-wide text-muted-foreground">Used in</h3>
                {(a.usage ?? []).length === 0 ? <p className="text-xs text-muted-foreground">{a.usage_count ? `Used ${a.usage_count}×` : a.usage ? "Not used in any content." : "Usage isn't reported by this backend yet."}</p> : (
                  <ul className="space-y-1 text-sm">{a.usage?.map((u, i) => (
                    <li key={`${u.content_item_id}-${i}`}><Link href={ws(`studio/${u.content_item_id}`)} className="flex items-center gap-1.5 hover:underline">{u.platform && <PlatformIcon platform={u.platform} size={16} />}{u.title ?? "Untitled"}<span className="text-xs text-muted-foreground">{u.role}</span></Link></li>
                  ))}</ul>
                )}
              </section>
              <div className="flex flex-wrap gap-2">
                {canCreate && a.kind === "image" && (
                  <DropdownMenu>
                    <DropdownMenuTrigger asChild><Button size="sm" variant="outline" disabled={transform.isPending}><Crop /> Resize</Button></DropdownMenuTrigger>
                    <DropdownMenuContent><DropdownMenuLabel>Platform preset</DropdownMenuLabel>{TRANSFORM_PRESETS.map((p) => <DropdownMenuItem key={p.platform + p.format + (p.aspect ?? "")} onClick={() => transform.mutate({ platform: p.platform, format: p.format, aspect: p.aspect })}><PlatformIcon platform={p.platform} size={14} /> {p.label}</DropdownMenuItem>)}</DropdownMenuContent>
                  </DropdownMenu>
                )}
                {canCreate && a.kind === "image" && <Button size="sm" variant="outline" onClick={() => removeBg.mutate()} disabled={removeBg.isPending}>{removeBg.isPending ? <Loader2 className="animate-spin" /> : <Eraser />} Remove bg</Button>}
                {href && <Button size="sm" variant="outline" asChild><a href={href} download={assetName(a)} target="_blank" rel="noreferrer"><Download /> Download</a></Button>}
                {canManage && <Button size="sm" variant="ghost" className="text-destructive" onClick={() => setConfirmDel(true)}><Trash2 /> Delete</Button>}
              </div>
            </>
          )}
        </div>
        <ConfirmDialog open={confirmDel} onOpenChange={setConfirmDel} destructive title={`Delete ${a ? assetName(a) : "this asset"}?`} confirmLabel="Delete asset" pending={del.isPending} onConfirm={() => del.mutate()}
                       description={<p>The file and its renditions are removed from storage{(a?.usage ?? []).length ? ` and detached from ${a?.usage?.length} content item(s)` : ""}. Deletion is blocked while the asset is attached to a scheduled post.</p>} />
      </SheetContent>
    </Sheet>
  );
}

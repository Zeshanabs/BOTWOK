"use client";
import { useEffect, useRef, useState } from "react";
import Link from "next/link";
import { useRouter, useSearchParams } from "next/navigation";
import { useMutation } from "@tanstack/react-query";
import { AlertTriangle, ArrowLeft, CheckCircle2, Eye, GitCompare, History, Loader2, MoreHorizontal, PanelRight, Pencil, Plus, Save, Send, Sparkles, Trash2, Undo2 } from "lucide-react";
import { toast } from "sonner";
import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert";
import { Button } from "@/components/ui/button";
import { Dialog, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle } from "@/components/ui/dialog";
import { DropdownMenu, DropdownMenuContent, DropdownMenuItem, DropdownMenuSeparator, DropdownMenuTrigger } from "@/components/ui/dropdown-menu";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { Sheet, SheetContent, SheetHeader, SheetTitle } from "@/components/ui/sheet";
import { Skeleton } from "@/components/ui/skeleton";
import { Textarea } from "@/components/ui/textarea";
import { PlatformIcon } from "@/components/shared/platform-icon";
import { StatusChip } from "@/components/shared/status-chip";
import { AiBadge } from "@/features/common/components/ai-badge";
import { ConfirmDialog } from "@/features/common/components/confirm-dialog";
import { QueryError } from "@/features/common/components/query-state";
import { useMediaQuery, usePermissions, useWorkspacePath } from "@/features/common/hooks";
import type { ContentStatus } from "@/features/common/types";
import { errorMessage, errorStatus } from "@/features/common/utils";
import { PLATFORMS, platformMeta, type Platform } from "@/lib/platforms";
import { cn } from "@/lib/utils";
import { contentApi, type ContentItem, type ContentVersion } from "../api";
import { useAutosave, useContent, useContentMutations, useUnsavedGuard, useVersions } from "../hooks";
import { composeMaster, stripMarkdown } from "../platform-rules";
import { useEditorDrafts } from "../use-drafts";
import { toItems } from "@/features/common/utils";
import { BudgetSummary } from "./character-budget";
import { HashtagInput } from "./hashtag-input";
import { MediaStrip } from "./media-strip";
import { Navigator } from "./navigator";
import { PlatformPreview } from "./platform-preview";
import { RepurposeDialog } from "./repurpose-dialog";
import { approvalPrecheck, RequestApprovalDialog } from "./request-approval-dialog";
import { RichTextEditor } from "./rich-text";
import { StatusMenu } from "./status-menu";
import { PANEL_TABS, StudioPanel, type PanelTab } from "./studio-panel";
import { VariantFields } from "./variant-fields";
import { VersionCompareDialog } from "./version-compare-dialog";
import { useBrandHashtags } from "./panels/seo-panel";
import type { PendingSource } from "./panels/sources-panel";

/** Studio editor route: loads the content item, then mounts the workspace keyed by id. */
export function ContentEditor({ contentId }: { contentId: string }) {
  const q = useContent(contentId);
  const ws = useWorkspacePath();
  if (q.isLoading) return <EditorSkeleton />;
  if (q.error) {
    if (errorStatus(q.error) === 404) return <div className="py-16 text-center"><p className="font-medium">Content not found</p><p className="mt-1 text-sm text-muted-foreground">It may have been deleted or belongs to another workspace.</p><Button asChild className="mt-4" variant="outline"><Link href={ws("studio")}>Back to Studio</Link></Button></div>;
    return <QueryError error={q.error} onRetry={() => q.refetch()} title="Couldn't load this content" />;
  }
  if (!q.data) return null;
  return <EditorWorkspace key={q.data.id} content={q.data} />;
}

function EditorSkeleton() {
  return (
    <div className="space-y-4" aria-busy="true" aria-label="Loading editor">
      <Skeleton className="h-9 w-2/3" />
      <div className="grid gap-6 xl:grid-cols-[220px_minmax(0,1fr)_360px]">
        <div className="hidden space-y-2 xl:block">{Array.from({ length: 6 }).map((_, i) => <Skeleton key={i} className="h-8" />)}</div>
        <div className="space-y-3"><Skeleton className="h-8 w-1/2" /><Skeleton className="h-16" /><Skeleton className="h-64" /><Skeleton className="h-10" /></div>
        <div className="hidden space-y-2 xl:block"><Skeleton className="h-9" /><Skeleton className="h-48" /></div>
      </div>
    </div>
  );
}

function EditorWorkspace({ content }: { content: ContentItem }) {
  const router = useRouter();
  const params = useSearchParams();
  const ws = useWorkspacePath();
  const perms = usePermissions();
  const readOnly = !perms.canCreate;
  const xl = useMediaQuery("(min-width: 1280px)");
  const lg = useMediaQuery("(min-width: 1024px)");
  const drafts = useEditorDrafts(content);
  const muts = useContentMutations(content.id);
  const versions = useVersions(content.id);
  const brandSettings = useBrandHashtags(content.brand_id);
  const bannedTags = brandSettings.data?.topics?.hashtags?.banned ?? [];

  const variantList = content.variants ?? [];
  const initialVariant = params.get("variant");
  const [selected, setSelected] = useState<string>(() => variantList.find((v) => v.platform === initialVariant || v.id === initialVariant)?.id ?? "master");
  const [tab, setTab] = useState<PanelTab>(() => (PANEL_TABS.find((t) => t.id === params.get("panel"))?.id ?? "ai"));
  const [mode, setMode] = useState<"edit" | "preview">("edit");
  const [previewPlatform, setPreviewPlatform] = useState<Platform>(variantList[0]?.platform ?? "linkedin");
  const [sheetOpen, setSheetOpen] = useState(false);
  const [repurpose, setRepurpose] = useState<{ open: boolean; preselect?: Platform | null }>({ open: false });
  const [compare, setCompare] = useState<{ open: boolean; a?: string; b?: string }>({ open: false });
  const [askApproval, setAskApproval] = useState(false);
  const [confirmDelete, setConfirmDelete] = useState(false);
  const [issuesOnly, setIssuesOnly] = useState(false);
  const [pendingSources, setPendingSources] = useState<PendingSource[]>([]);

  const variant = variantList.find((v) => v.id === selected) ?? null;
  const vDraft = variant ? drafts.variants[variant.id] : null;

  const syncUrl = (sel: string, t: PanelTab) => {
    const v = variantList.find((x) => x.id === sel);
    const sp = new URLSearchParams();
    if (v) sp.set("variant", v.platform);
    if (t !== "ai") sp.set("panel", t);
    const s = sp.toString();
    router.replace(s ? `?${s}` : window.location.pathname, { scroll: false });
  };
  const select = (id: string) => { setSelected(id); syncUrl(id, tab); if (variantList.find((v) => v.id === id)) setPreviewPlatform(variantList.find((v) => v.id === id)?.platform ?? previewPlatform); };
  const changeTab = (t: PanelTab) => { setTab(t); syncUrl(selected, t); };
  const openPanel = (t: PanelTab) => { changeTab(t); if (!xl) setSheetOpen(true); };

  // Autosave every 5 s, guard unload, keyboard shortcuts.
  useAutosave(drafts.dirty, drafts.saveAll, 5000);
  useUnsavedGuard(drafts.dirty);
  const liveForVariant = (vid: string) => {
    const d = drafts.variants[vid];
    const v = variantList.find((x) => x.id === vid);
    if (!d || !v) return { text: "", hashtags: [] as string[] };
    return { text: d.text, segments: d.segs.length && v.format !== "carousel" ? d.segs.map((s) => s.text) : undefined, metadata: d.metadata, hashtags: d.hashtags };
  };
  const precheck = approvalPrecheck(content, liveForVariant);
  const canRequest = perms.canCreate && ["draft", "ai_generated", "rejected", "idea"].includes(content.status);
  const shortcuts = useRef({ save: () => {}, request: () => {} });
  useEffect(() => {
    shortcuts.current = {
      save: () => { drafts.saveAll(); if (!drafts.dirty) toast.message("Nothing to save"); },
      request: () => { if (canRequest) { drafts.saveAll(); setAskApproval(true); } },
    };
  });
  useEffect(() => {
    const h = (e: KeyboardEvent) => {
      if (!(e.metaKey || e.ctrlKey)) return;
      if (e.key.toLowerCase() === "s") { e.preventDefault(); shortcuts.current.save(); }
      else if (e.key === "Enter") { e.preventDefault(); shortcuts.current.request(); }
    };
    window.addEventListener("keydown", h);
    return () => window.removeEventListener("keydown", h);
  }, []);

  const transition = (to: ContentStatus) => {
    if (drafts.dirty) drafts.saveAll();
    muts.transition.mutate({ to });
  };
  const restore = (v: ContentVersion) => {
    if (drafts.dirty && !window.confirm("You have unsaved edits. Restoring will create a new version from the old one; your unsaved edits stay in the editor. Continue?")) return;
    muts.restore.mutate({ version: v.version, variant_id: v.target_type.includes("variant") ? v.target_id : null }, { onSuccess: () => setCompare({ open: false }) });
  };
  const del = useMutation({
    mutationFn: () => contentApi.remove(content.id),
    onSuccess: () => { toast.success("Content deleted"); router.push(ws("studio")); },
    onError: (e) => toast.error(errorMessage(e)),
  });
  const applySuggestion = (text: string, field?: string | null) => {
    const copy = () => { void navigator.clipboard?.writeText(text); toast.message("Suggestion copied — paste it where it fits"); };
    if (variant && vDraft) {
      if (field === "text") { drafts.updateVariant(variant.id, { text }); toast.success("Suggestion applied — saved as your version"); }
      else copy();
      return;
    }
    const f = field === "hook" || field === "cta" || field === "body_md" ? field : field === "body" ? "body_md" : null;
    if (!f) { copy(); return; }
    drafts.setMaster((m) => ({ ...m, [f]: text }));
    toast.success(`Suggestion applied to ${f === "body_md" ? "body" : f}`);
  };
  const masterText = composeMaster(drafts.master);
  const liveText = variant && vDraft ? vDraft.text : masterText;
  const liveTags = variant && vDraft ? vDraft.hashtags : drafts.master.hashtags;
  const setLiveTags = (t: string[]) => (variant ? drafts.updateVariant(variant.id, { hashtags: t }) : drafts.setMaster((m) => ({ ...m, hashtags: t })));
  const masterAssets = (content.assets ?? []).filter((a) => !a.variant_id);
  const previewMedia = [...(variant?.assets ?? []), ...masterAssets].sort((a, b) => a.position - b.position).map((a) => ({ id: a.media_asset_id, ...(a.media ?? {}), alt_text: a.alt_text ?? a.media?.alt_text }));
  const budgetEntries = variantList.map((v) => ({ id: v.id, platform: v.platform, ...liveForVariant(v.id) }));

  const panel = (
    <StudioPanel content={content} variant={variant} tab={tab} onTabChange={changeTab} dirty={drafts.dirty} flush={drafts.saveAll}
                 liveText={stripMarkdown(liveText)} hashtags={liveTags} onHashtagsChange={setLiveTags}
                 segs={vDraft?.segs ?? null} onSegsChange={(s) => variant && drafts.updateVariant(variant.id, { segs: s, stringMode: false })}
                 onApplySuggestion={applySuggestion} onRequestApproval={() => { drafts.saveAll(); setAskApproval(true); }}
                 onTransition={transition} transitionPending={muts.transition.isPending} onSelectVariant={select}
                 pendingSources={pendingSources} onAddSource={(src) => setPendingSources((cur) => (cur.some((x) => x.id === src.id) ? cur : [...cur, src]))}
                 onRemoveSource={(id) => setPendingSources((cur) => cur.filter((x) => x.id !== id))} />
  );

  const saveState = drafts.saving ? <span className="flex items-center gap-1"><Loader2 className="h-3 w-3 animate-spin" /> Saving…</span>
    : drafts.saveError ? <span className="flex items-center gap-1 text-destructive" title={drafts.saveError}><AlertTriangle className="h-3 w-3" /> Not saved — kept locally, retrying</span>
    : drafts.dirty ? <span className="flex items-center gap-1 text-warning">● Unsaved changes</span>
    : <span className="flex items-center gap-1"><CheckCircle2 className="h-3 w-3 text-success" /> {drafts.savedAt ? `Saved ${new Date(drafts.savedAt).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" })}` : "All changes saved"} · v{content.current_version}</span>;

  return (
    <div className="pb-24 lg:pb-4">
      {/* Header */}
      <div className="mb-4 flex flex-col gap-3 lg:flex-row lg:items-center">
        <div className="flex min-w-0 flex-1 items-center gap-2">
          <Button asChild variant="ghost" size="icon-sm" aria-label="Back to Studio"><Link href={ws("studio")} onClick={() => drafts.dirty && drafts.saveAll()}><ArrowLeft /></Link></Button>
          <Link href={ws("studio")} className="hidden text-sm text-muted-foreground hover:underline sm:inline">Studio</Link>
          <span className="hidden text-muted-foreground sm:inline">/</span>
          <Input value={drafts.master.title} onChange={(e) => drafts.setMaster((m) => ({ ...m, title: e.target.value }))} readOnly={readOnly} aria-label="Title"
                 className="h-9 min-w-0 flex-1 border-transparent px-1 text-lg font-semibold shadow-none hover:border-input focus-visible:border-input" placeholder="Untitled" />
          <StatusMenu status={content.status} onTransition={transition} pending={muts.transition.isPending} />
          {content.ai_generated && <AiBadge meta={content.generation_metadata} className="hidden sm:inline-flex" />}
        </div>
        <div className="flex flex-wrap items-center gap-2">
          {perms.canCreate && <Button variant="outline" size="sm" onClick={() => setRepurpose({ open: true })}><Sparkles className="text-ai" /> Repurpose</Button>}
          {content.status === "needs_review" && perms.canApprove
            ? <Button size="sm" onClick={() => openPanel("approval")}><CheckCircle2 /> Review & decide</Button>
            : canRequest && <Button size="sm" onClick={() => { drafts.saveAll(); setAskApproval(true); }}><Send /> Request approval</Button>}
          {!xl && <Button variant="outline" size="sm" className="hidden lg:inline-flex" onClick={() => setSheetOpen(true)}><PanelRight /> Panel</Button>}
          <DropdownMenu>
            <DropdownMenuTrigger asChild><Button variant="ghost" size="icon-sm" aria-label="More actions"><MoreHorizontal /></Button></DropdownMenuTrigger>
            <DropdownMenuContent align="end">
              <DropdownMenuItem onClick={() => setCompare({ open: true })}><GitCompare /> Compare versions</DropdownMenuItem>
              {content.generation_metadata?.run_id && <DropdownMenuItem asChild><Link href={ws(`command-center/${content.generation_metadata.run_id}`)}><History /> AI runs</Link></DropdownMenuItem>}
              {perms.canManage && content.status !== "archived" && <DropdownMenuItem onClick={() => transition("archived")}>Archive</DropdownMenuItem>}
              {perms.canManage && <><DropdownMenuSeparator /><DropdownMenuItem className="text-destructive" onClick={() => setConfirmDelete(true)}><Trash2 /> Delete</DropdownMenuItem></>}
            </DropdownMenuContent>
          </DropdownMenu>
        </div>
      </div>

      {drafts.recovered && (
        <Alert className="mb-4"><Undo2 /><AlertTitle>Unsaved draft found in this browser</AlertTitle>
          <AlertDescription><p>A save failed on {new Date(drafts.recovered.at).toLocaleString()}. Restore it into the editor?</p>
            <div className="mt-1 flex gap-2"><Button size="xs" onClick={drafts.restoreRecovered}>Restore draft</Button><Button size="xs" variant="ghost" onClick={drafts.dropRecovered}>Discard</Button></div></AlertDescription></Alert>
      )}
      {drafts.incoming != null && (
        <Alert className="mb-4"><Sparkles className="text-ai" /><AlertTitle>A newer version (v{drafts.incoming}) arrived while you were editing</AlertTitle>
          <AlertDescription><p>Your unsaved text is kept. Compare before saving, or discard your edits to load it.</p>
            <div className="mt-1 flex gap-2">
              <Button size="xs" variant="outline" onClick={() => setCompare({ open: true })}>View diff</Button>
              <Button size="xs" variant="ghost" onClick={() => { drafts.discard(); }}>Discard my edits</Button>
              <Button size="xs" variant="ghost" onClick={drafts.clearIncoming}>Keep mine</Button>
            </div></AlertDescription></Alert>
      )}
      {readOnly && <p className="mb-4 rounded-md bg-muted px-3 py-2 text-sm text-muted-foreground">You have view-only access to this content.</p>}

      <div className="grid gap-6 lg:grid-cols-[220px_minmax(0,1fr)] xl:grid-cols-[220px_minmax(0,1fr)_360px]">
        {lg && (
          <aside className="lg:sticky lg:top-0 lg:max-h-[calc(100vh-7rem)] lg:overflow-y-auto">
            <Navigator content={content} selected={selected} onSelect={select} onAddPlatform={() => setRepurpose({ open: true })}
                       onCompare={(a, b) => setCompare({ open: true, a, b })} onRestore={restore} live={liveForVariant} canEdit={perms.canCreate}
                       issuesOnly={issuesOnly} onIssuesOnly={setIssuesOnly} />
          </aside>
        )}

        {/* Centre editor */}
        <section aria-label="Editor" className="min-w-0 space-y-4">
          <div className="flex flex-wrap items-center gap-2">
            <div className="flex flex-wrap items-center gap-1" role="tablist" aria-label="Master and platform versions">
              <button type="button" role="tab" aria-selected={selected === "master"} onClick={() => select("master")}
                      className={cn("rounded-md border px-2.5 py-1 text-sm", selected === "master" ? "border-primary bg-primary/5 font-medium" : "hover:bg-accent")}>Master</button>
              {variantList.map((v) => (
                <button key={v.id} type="button" role="tab" aria-selected={selected === v.id} onClick={() => select(v.id)} title={`${platformMeta(v.platform).label} · ${v.format.replace(/_/g, " ")} · ${v.status.replace(/_/g, " ")}`}
                        className={cn("flex items-center gap-1 rounded-md border px-1.5 py-1 text-sm", selected === v.id ? "border-primary bg-primary/5" : "hover:bg-accent")}>
                  <PlatformIcon platform={v.platform} size={18} />{drafts.dirtyVariantIds.includes(v.id) && <span className="h-1.5 w-1.5 rounded-full bg-warning" aria-label="unsaved" />}
                </button>
              ))}
              {perms.canCreate && <Button size="icon-sm" variant="ghost" aria-label="Add platform version" onClick={() => setRepurpose({ open: true })}><Plus /></Button>}
            </div>
            <div className="ml-auto flex rounded-md border p-0.5 text-xs" role="radiogroup" aria-label="Editor mode">
              <button type="button" role="radio" aria-checked={mode === "edit"} onClick={() => setMode("edit")} className={cn("flex items-center gap-1 rounded px-2 py-1", mode === "edit" && "bg-secondary")}><Pencil className="h-3 w-3" /> Edit</button>
              <button type="button" role="radio" aria-checked={mode === "preview"} onClick={() => setMode("preview")} className={cn("flex items-center gap-1 rounded px-2 py-1", mode === "preview" && "bg-secondary")}><Eye className="h-3 w-3" /> Preview</button>
            </div>
          </div>

          {mode === "preview" ? (
            <div className="space-y-3">
              {!variant && (
                <Select value={previewPlatform} onValueChange={(p) => setPreviewPlatform(p as Platform)}>
                  <SelectTrigger className="w-48" aria-label="Preview platform"><SelectValue /></SelectTrigger>
                  <SelectContent>{PLATFORMS.map((p) => <SelectItem key={p.id} value={p.id}>{p.label}</SelectItem>)}</SelectContent>
                </Select>
              )}
              <div className="mx-auto max-w-[560px]">
                {variant && vDraft ? (
                  <PlatformPreview platform={variant.platform} format={variant.format} text={vDraft.text} hashtags={vDraft.hashtags}
                                   segments={vDraft.segs.length && variant.format !== "carousel" ? vDraft.segs.map((s) => s.text) : undefined}
                                   media={previewMedia} title={typeof vDraft.metadata.title === "string" ? vDraft.metadata.title : null} />
                ) : (
                  <PlatformPreview platform={previewPlatform} text={composeMaster({ ...drafts.master, hashtags: [] })} hashtags={drafts.master.hashtags} media={previewMedia} title={drafts.master.title} />
                )}
              </div>
            </div>
          ) : variant && vDraft ? (
            <>
              <div className="flex flex-wrap items-center gap-2 text-sm">
                <PlatformIcon platform={variant.platform} size={20} /><span className="font-medium">{platformMeta(variant.platform).label}</span>
                <span className="text-muted-foreground">· {variant.format.replace(/_/g, " ")}</span><StatusChip status={variant.status} />
                {variant.ai_generated && <AiBadge meta={variant.generation_metadata} />}
                <span className="text-xs text-muted-foreground">v{variant.current_version ?? 1}</span>
              </div>
              <VariantFields variant={variant} draft={vDraft} onChange={(p) => drafts.updateVariant(variant.id, p)} readOnly={readOnly} bannedTags={bannedTags} />
              <div className="space-y-1.5">
                <Label className="text-xs uppercase tracking-wide text-muted-foreground">Media</Label>
                <MediaStrip assets={[...(variant.assets ?? []), ...masterAssets]} onAdd={readOnly ? undefined : () => openPanel("media")} onGenerate={readOnly ? undefined : () => openPanel("media")} />
              </div>
            </>
          ) : (
            <MasterFields drafts={drafts} readOnly={readOnly} bannedTags={bannedTags} masterAssets={masterAssets} openMedia={() => openPanel("media")} />
          )}

          {/* Totals + save bar */}
          <div className="z-10 -mx-1 space-y-2 border-t bg-background/95 px-1 py-2 backdrop-blur lg:sticky lg:bottom-0">
            {budgetEntries.length > 0 && <BudgetSummary entries={budgetEntries} onSelect={select} />}
            <div className="flex flex-wrap items-center gap-2 text-xs text-muted-foreground">
              {saveState}
              <div className="ml-auto flex gap-2">
                {drafts.dirty && <Button size="sm" variant="ghost" onClick={drafts.discard}>Discard</Button>}
                <Button size="sm" onClick={() => drafts.saveAll()} disabled={readOnly || !drafts.dirty || drafts.saving}><Save /> Save <kbd className="ml-1 hidden rounded border px-1 text-[10px] sm:inline">⌘S</kbd></Button>
              </div>
            </div>
          </div>
        </section>

        {xl && <aside aria-label="Assistant panel" className="xl:sticky xl:top-0 xl:max-h-[calc(100vh-7rem)] xl:overflow-y-auto">{panel}</aside>}
      </div>

      {/* Mobile/tablet: panel in a Sheet; bottom toolbar on phones */}
      {!xl && (
        <Sheet open={sheetOpen} onOpenChange={setSheetOpen}>
          <SheetContent side={lg ? "right" : "bottom"} className={cn("overflow-y-auto p-4", lg ? "sm:max-w-md" : "max-h-[85vh]")}>
            <SheetHeader className="p-0"><SheetTitle>{PANEL_TABS.find((t) => t.id === tab)?.label} · {variant ? platformMeta(variant.platform).label : "Master"}</SheetTitle></SheetHeader>
            {panel}
          </SheetContent>
        </Sheet>
      )}
      {!lg && (
        <div className="fixed inset-x-0 bottom-14 z-30 flex items-center gap-1 overflow-x-auto border-t bg-background px-2 py-1.5 md:bottom-0" role="toolbar" aria-label="Studio panels">
          {(["ai", "sources", "critic", "approval", "schedule", "media"] as PanelTab[]).map((t) => (
            <Button key={t} size="xs" variant="ghost" onClick={() => openPanel(t)}>{t === "ai" && <Sparkles className="text-ai" />}{PANEL_TABS.find((p) => p.id === t)?.label}</Button>
          ))}
          <Button size="xs" className="ml-auto" onClick={() => drafts.saveAll()} disabled={readOnly || !drafts.dirty}>Save</Button>
        </div>
      )}

      <RepurposeDialog key={repurpose.open ? "open" : "closed"} open={repurpose.open} onOpenChange={(o) => setRepurpose({ open: o })} content={content} preselect={repurpose.preselect} onDone={muts.refresh} />
      {compare.open && (
        <VersionCompareDialog open={compare.open} onOpenChange={(o) => setCompare({ open: o })} versions={toItems(versions.data)} variants={variantList}
                              initialA={compare.a} initialB={compare.b} onRestore={restore} canRestore={perms.canCreate} />
      )}
      <RequestApprovalDialog open={askApproval} onOpenChange={setAskApproval} content={content} precheck={precheck} pending={muts.requestApproval.isPending} error={muts.requestApproval.error}
                             onSubmit={(b) => muts.requestApproval.mutate(b, { onSuccess: () => setAskApproval(false) })} />
      <ConfirmDialog open={confirmDelete} onOpenChange={setConfirmDelete} destructive title={`Delete “${content.title}”?`} confirmLabel="Delete content" pending={del.isPending}
                     typeToConfirm={content.status === "approved" ? "delete" : undefined} onConfirm={() => del.mutate()}
                     description={<p>This deletes the master, its {variantList.length} platform version(s) and version history. Scheduled posts for these versions are cancelled. Published posts stay on the platforms.</p>} />
      <Dialog open={!!drafts.conflict} onOpenChange={(o) => !o && drafts.resolveConflict("theirs")}>
        <DialogContent>
          <DialogHeader><DialogTitle>Someone saved a newer version</DialogTitle>
            <DialogDescription>Your save was based on v{content.current_version}, but a newer version exists. Choose what to keep.</DialogDescription></DialogHeader>
          <DialogFooter>
            <Button variant="outline" onClick={() => setCompare({ open: true })}>View diff</Button>
            <Button variant="outline" onClick={() => drafts.resolveConflict("theirs")}>Discard mine</Button>
            <Button onClick={() => drafts.resolveConflict("mine")}>Keep mine as newest</Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </div>
  );
}

function MasterFields({ drafts, readOnly, bannedTags, masterAssets, openMedia }: {
  drafts: ReturnType<typeof useEditorDrafts>; readOnly: boolean; bannedTags: string[]; masterAssets: NonNullable<ContentItem["assets"]>; openMedia: () => void;
}) {
  const m = drafts.master;
  const set = (p: Partial<typeof m>) => drafts.setMaster((cur) => ({ ...cur, ...p }));
  const bodyChars = Array.from(stripMarkdown(m.body_md)).length;
  const counter = (n: number, max: number) => <span className={cn("text-xs tabular-nums", n > max ? "text-destructive" : "text-muted-foreground")}>{n}/{max}</span>;
  return (
    <div className="space-y-5">
      <div className="space-y-1.5">
        <div className="flex items-center justify-between"><Label htmlFor="m-hook" className="text-xs uppercase tracking-wide text-muted-foreground">Hook</Label>{counter(Array.from(m.hook).length, 150)}</div>
        <Textarea id="m-hook" rows={2} value={m.hook} readOnly={readOnly} onChange={(e) => set({ hook: e.target.value })} placeholder="The first line people see — make it count" />
      </div>
      <div className="space-y-1.5">
        <div className="flex items-center justify-between"><span className="text-xs font-medium uppercase tracking-wide text-muted-foreground">Body</span><span className="text-xs tabular-nums text-muted-foreground">{bodyChars.toLocaleString()} chars</span></div>
        <RichTextEditor value={m.body_md} onChange={(md) => set({ body_md: md })} readOnly={readOnly} ariaLabel="Body" />
      </div>
      <div className="space-y-1.5">
        <div className="flex items-center justify-between"><Label htmlFor="m-cta" className="text-xs uppercase tracking-wide text-muted-foreground">CTA</Label>{counter(Array.from(m.cta).length, 150)}</div>
        <Input id="m-cta" value={m.cta} readOnly={readOnly} onChange={(e) => set({ cta: e.target.value })} placeholder="Get the free guide → link in bio" />
      </div>
      <div className="space-y-1.5">
        <Label className="text-xs uppercase tracking-wide text-muted-foreground">Hashtags</Label>
        <HashtagInput value={m.hashtags} onChange={(h) => set({ hashtags: h })} banned={bannedTags} disabled={readOnly} />
      </div>
      <div className="space-y-1.5">
        <Label htmlFor="m-alt" className="text-xs uppercase tracking-wide text-muted-foreground">Alt text</Label>
        <Textarea id="m-alt" rows={2} value={m.alt_text} readOnly={readOnly} onChange={(e) => set({ alt_text: e.target.value })} placeholder="Describe the primary image for screen readers" />
      </div>
      <div className="space-y-1.5">
        <Label className="text-xs uppercase tracking-wide text-muted-foreground">Media</Label>
        <MediaStrip assets={masterAssets} onAdd={readOnly ? undefined : openMedia} onGenerate={readOnly ? undefined : openMedia} />
      </div>
    </div>
  );
}

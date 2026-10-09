"use client";
import { useCallback, useRef, useState } from "react";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { toast } from "sonner";
import { errorMessage, errorStatus } from "@/features/common/utils";
import { contentApi, type ContentItem, type ContentVariant } from "./api";
import { contentKeys, patchVariantInCache } from "./hooks";
import { fromSegs, segsEqual, toSegs, type Seg } from "./segments";

export interface MasterDraft { title: string; hook: string; body_md: string; cta: string; hashtags: string[]; alt_text: string }
export interface VariantDraft { text: string; segs: Seg[]; stringMode: boolean; hashtags: string[]; metadata: Record<string, unknown> }
export type Conflict = { kind: "master" } | { kind: "variant"; vid: string } | null;

const arrEq = (a: string[], b: string[]) => a.length === b.length && a.every((x, i) => x === b[i]);
export function masterFrom(c: ContentItem): MasterDraft {
  const b = c.body ?? {};
  return { title: c.title ?? "", hook: b.hook ?? "", body_md: b.body_md ?? "", cta: b.cta ?? "", hashtags: b.hashtags ?? [], alt_text: b.alt_text ?? "" };
}
export function variantFrom(v: ContentVariant): VariantDraft {
  const { segs, stringMode } = toSegs(v.segments);
  return { text: v.text ?? "", segs, stringMode, hashtags: v.hashtags ?? [], metadata: v.platform_metadata ?? {} };
}
export const eqMaster = (a: MasterDraft, b: MasterDraft) => a.title === b.title && a.hook === b.hook && a.body_md === b.body_md && a.cta === b.cta && a.alt_text === b.alt_text && arrEq(a.hashtags, b.hashtags);
export const eqVariant = (a: VariantDraft, b: VariantDraft) => a.text === b.text && segsEqual(a.segs, b.segs) && arrEq(a.hashtags, b.hashtags) && JSON.stringify(a.metadata) === JSON.stringify(b.metadata);

const stampOf = (c: ContentItem) => `${c.current_version}|${c.updated_at ?? ""}|${(c.variants ?? []).map((v) => `${v.id}:${v.current_version ?? 0}:${v.updated_at ?? ""}`).join(",")}`;
const backupKey = (id: string) => `botwok:studio-draft:${id}`;
interface Backup { at: string; master: MasterDraft; variants: Record<string, VariantDraft> }

/**
 * Local drafts for the master and every variant with dirty tracking, server sync (never clobbering unsaved edits),
 * optimistic-concurrency saves (expected_version → 409 conflict), and a localStorage backup when saving fails.
 */
export function useEditorDrafts(content: ContentItem) {
  const qc = useQueryClient();
  const key = contentKeys.detail(content.id);
  const [master, setMaster] = useState(() => masterFrom(content));
  const [masterBase, setMasterBase] = useState(() => masterFrom(content));
  const [variants, setVariants] = useState<Record<string, VariantDraft>>(() => Object.fromEntries((content.variants ?? []).map((v) => [v.id, variantFrom(v)])));
  const [variantBase, setVariantBase] = useState<Record<string, VariantDraft>>(() => Object.fromEntries((content.variants ?? []).map((v) => [v.id, variantFrom(v)])));
  const [sentMaster, setSentMaster] = useState<MasterDraft | null>(null);
  const [sentVariants, setSentVariants] = useState<Record<string, VariantDraft>>({});
  const [stamp, setStamp] = useState(() => stampOf(content));
  const [incoming, setIncoming] = useState<number | null>(null);
  const [savedAt, setSavedAt] = useState<string | null>(null);
  const [saveError, setSaveError] = useState<string | null>(null);
  const [conflict, setConflict] = useState<Conflict>(null);
  const [recovered, setRecovered] = useState<Backup | null>(() => {
    try {
      const raw = typeof window !== "undefined" ? window.localStorage.getItem(backupKey(content.id)) : null;
      return raw ? (JSON.parse(raw) as Backup) : null;
    } catch { return null; }
  });
  const inflight = useRef(new Set<string>());

  const masterDirty = !eqMaster(master, masterBase);
  const dirtyVariantIds = Object.keys(variants).filter((id) => variantBase[id] && !eqVariant(variants[id], variantBase[id]));
  const dirty = masterDirty || dirtyVariantIds.length > 0;

  // Render-phase sync from the server copy (guarded by a stamp so it runs once per server change).
  const s = stampOf(content);
  if (s !== stamp) {
    setStamp(s);
    const sm = masterFrom(content);
    if (!eqMaster(sm, masterBase)) {
      const ours = sentMaster != null && eqMaster(sm, sentMaster);
      if (masterDirty && !ours) setIncoming(content.current_version);
      if (!masterDirty) setMaster(sm);
      setMasterBase(sm);
    }
    const nextDrafts = { ...variants };
    const nextBase = { ...variantBase };
    let changed = false;
    for (const v of content.variants ?? []) {
      const sv = variantFrom(v);
      const base = variantBase[v.id];
      if (base && eqVariant(sv, base)) continue;
      changed = true;
      const isDirty = base ? !eqVariant(variants[v.id], base) : false;
      const ours = sentVariants[v.id] != null && eqVariant(sv, sentVariants[v.id]);
      if (isDirty && !ours) setIncoming(v.current_version ?? content.current_version);
      if (!isDirty) nextDrafts[v.id] = sv;
      nextBase[v.id] = sv;
    }
    if (changed) { setVariants(nextDrafts); setVariantBase(nextBase); }
  }

  const backup = (m: MasterDraft, vs: Record<string, VariantDraft>) => {
    try { window.localStorage.setItem(backupKey(content.id), JSON.stringify({ at: new Date().toISOString(), master: m, variants: vs } satisfies Backup)); } catch { /* storage full or blocked */ }
  };
  const clearBackup = () => { try { window.localStorage.removeItem(backupKey(content.id)); } catch { /* ignore */ } };

  const saveMasterM = useMutation({
    mutationFn: ({ d, force }: { d: MasterDraft; force?: boolean }) => contentApi.patch(content.id, {
      title: d.title,
      body: { ...(content.body ?? {}), hook: d.hook, body_md: d.body_md, cta: d.cta, hashtags: d.hashtags, alt_text: d.alt_text },
      expected_version: force ? undefined : content.current_version,
    }),
    onMutate: ({ d }) => setSentMaster(d),
    onSuccess: (item) => {
      if (item && typeof item === "object" && "id" in item) qc.setQueryData(key, item); else void qc.invalidateQueries({ queryKey: key });
      void qc.invalidateQueries({ queryKey: contentKeys.versions(content.id) });
      setSavedAt(new Date().toISOString()); setSaveError(null); clearBackup();
    },
    onError: (e, { d }) => {
      if (errorStatus(e) === 409) setConflict({ kind: "master" });
      else { setSaveError(errorMessage(e)); backup(d, variants); }
    },
    onSettled: () => { inflight.current.delete("master"); },
  });
  const saveVariantM = useMutation({
    mutationFn: ({ vid, d, force }: { vid: string; d: VariantDraft; force?: boolean }) => {
      const v = (content.variants ?? []).find((x) => x.id === vid);
      return contentApi.patchVariant(content.id, vid, { text: d.text, segments: fromSegs(d.segs, d.stringMode), hashtags: d.hashtags, platform_metadata: d.metadata, expected_version: force ? undefined : v?.current_version });
    },
    onMutate: ({ vid, d }) => setSentVariants((cur) => ({ ...cur, [vid]: d })),
    onSuccess: (v) => {
      if (v && typeof v === "object" && "id" in v) qc.setQueryData<ContentItem>(key, (item) => patchVariantInCache(item, v));
      // Refresh the item too: variant edits can bump the item version / status (e.g. approved → needs_review).
      void qc.invalidateQueries({ queryKey: key });
      void qc.invalidateQueries({ queryKey: contentKeys.versions(content.id) });
      setSavedAt(new Date().toISOString()); setSaveError(null); clearBackup();
    },
    onError: (e, { vid, d }) => {
      if (errorStatus(e) === 409) setConflict({ kind: "variant", vid });
      else { setSaveError(errorMessage(e)); backup(master, { ...variants, [vid]: d }); }
    },
    onSettled: (_d, _e, { vid }) => { inflight.current.delete(vid); },
  });

  const saveAll = useCallback(() => {
    if (masterDirty && !inflight.current.has("master")) { inflight.current.add("master"); saveMasterM.mutate({ d: master }); }
    for (const vid of dirtyVariantIds) {
      if (inflight.current.has(vid)) continue;
      inflight.current.add(vid);
      saveVariantM.mutate({ vid, d: variants[vid] });
    }
  }, [masterDirty, dirtyVariantIds, master, variants, saveMasterM, saveVariantM]);

  const discard = () => {
    setMaster(masterBase);
    setVariants((cur) => ({ ...cur, ...Object.fromEntries(dirtyVariantIds.map((id) => [id, variantBase[id]])) }));
    setIncoming(null);
    clearBackup();
  };

  const resolveConflict = async (choice: "mine" | "theirs") => {
    const c = conflict;
    setConflict(null);
    if (!c) return;
    if (choice === "mine") {
      if (c.kind === "master") saveMasterM.mutate({ d: master, force: true });
      else saveVariantM.mutate({ vid: c.vid, d: variants[c.vid], force: true });
      return;
    }
    await qc.refetchQueries({ queryKey: key });
    const fresh = qc.getQueryData<ContentItem>(key);
    if (!fresh) return;
    if (c.kind === "master") { const m = masterFrom(fresh); setMaster(m); setMasterBase(m); }
    else {
      const v = (fresh.variants ?? []).find((x) => x.id === c.vid);
      if (v) { const d = variantFrom(v); setVariants((cur) => ({ ...cur, [c.vid]: d })); setVariantBase((cur) => ({ ...cur, [c.vid]: d })); }
    }
    toast.message("Loaded the newer version — your edits were discarded");
  };

  const restoreRecovered = () => {
    if (!recovered) return;
    setMaster(recovered.master);
    setVariants((cur) => ({ ...cur, ...Object.fromEntries(Object.entries(recovered.variants).filter(([id]) => id in cur)) }));
    setRecovered(null);
    toast.success("Recovered local draft — it will autosave");
  };
  const dropRecovered = () => { clearBackup(); setRecovered(null); };

  const updateVariant = (vid: string, patch: Partial<VariantDraft>) => setVariants((cur) => (cur[vid] ? { ...cur, [vid]: { ...cur[vid], ...patch } } : cur));

  return {
    master, setMaster, variants, updateVariant, masterDirty, dirtyVariantIds, dirty,
    saving: saveMasterM.isPending || saveVariantM.isPending, savedAt, saveError, saveAll, discard,
    incoming, clearIncoming: () => setIncoming(null), conflict, resolveConflict,
    recovered, restoreRecovered, dropRecovered,
  };
}

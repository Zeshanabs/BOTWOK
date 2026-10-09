"use client";
import { useEffect, useRef, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { CheckCheck, Inbox, Loader2, Sparkles } from "lucide-react";
import { toast } from "sonner";
import { Button } from "@/components/ui/button";
import { Checkbox } from "@/components/ui/checkbox";
import { Dialog, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle } from "@/components/ui/dialog";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { Skeleton } from "@/components/ui/skeleton";
import { Tabs, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { EmptyState } from "@/components/data/empty-state";
import { PageHeader } from "@/components/data/page-header";
import { PlatformIcon } from "@/components/data/platform-icon";
import { StatusChip } from "@/components/data/status-chip";
import { QueryError } from "@/features/common/components/query-state";
import { useBrands, useMediaQuery, usePermissions } from "@/features/common/hooks";
import { errorMessage, errorStatus, relTime, toItems } from "@/features/common/utils";
import { cn } from "@/lib/utils";
import { approvalPlatforms, approvalsApi, approvalTitle, isAiRequested, type Approval } from "../api";
import { useSession } from "@/stores/session";
import { ApprovalDetail, type Decision } from "./approval-detail";

const ALL = "all";

/** Approvals inbox (doc 24 §15): brand-grouped pending list, decision view, bulk approve, decided history. */
export function ApprovalsInbox() {
  const qc = useQueryClient();
  const { canApprove } = usePermissions();
  const wide = useMediaQuery("(min-width: 1024px)", true);
  const brands = toItems(useBrands().data);
  const [tab, setTab] = useState<"pending" | "decided">("pending");
  const [brand, setBrand] = useState(ALL);
  const [mine, setMine] = useState(false);
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [checked, setChecked] = useState<Set<string>>(new Set());
  const [bulkOpen, setBulkOpen] = useState(false);
  const [includeWarned, setIncludeWarned] = useState(false);
  const [decideError, setDecideError] = useState<string | null>(null);
  const list = useQuery({
    queryKey: ["approvals", "list", tab, brand],
    queryFn: () => approvalsApi.list({ status: tab === "pending" ? "pending" : ["approved", "rejected", "expired"], brand_id: brand === ALL ? undefined : brand }),
  });
  const userId = useSession((s) => s.user?.id);
  // "Mine" is filtered client-side (the list endpoint has no requester filter).
  const items = toItems(list.data).filter((a) => !mine || a.requested_by === userId);
  const current = items.find((a) => a.id === selectedId) ? selectedId : wide ? items[0]?.id ?? null : selectedId;
  const idx = items.findIndex((a) => a.id === current);
  const brandName = (a: Approval) => a.brand?.name ?? brands.find((b) => b.id === a.brand_id)?.name ?? "No brand";
  const groups = new Map<string, Approval[]>();
  items.forEach((a) => { const k = brandName(a); groups.set(k, [...(groups.get(k) ?? []), a]); });
  const warned = (a: Approval) => (a.warnings ?? []).length > 0 || a.payload?.risk_level === "high" || a.payload?.risk_level === "medium" || a.payload?.policy_flags != null;

  const decide = useMutation({
    mutationFn: ({ a, d, comment, ack }: { a: Approval; d: Decision; comment: string; ack: string[] }) =>
      d === "approve" ? approvalsApi.approve(a.id, { comment: comment.trim() || undefined, acknowledged_flags: ack.length ? ack : undefined }) : approvalsApi.reject(a.id, { comment: comment.trim(), decision: d }),
    onMutate: async ({ a }) => {
      setDecideError(null);
      await qc.cancelQueries({ queryKey: ["approvals", "list"] });
      const key = ["approvals", "list", tab, brand];
      const prev = qc.getQueryData(key);
      if (tab === "pending") qc.setQueryData(key, (old: typeof list.data) => (Array.isArray(old) ? old.filter((x) => x.id !== a.id) : old ? { ...old, items: old.items.filter((x) => x.id !== a.id) } : old));
      const next = items[idx + 1] ?? items[idx - 1];
      setSelectedId(next && next.id !== a.id ? next.id : null);
      return { prev, key, id: a.id };
    },
    onError: (e, { a }, ctx) => {
      if (ctx) qc.setQueryData(ctx.key, ctx.prev);
      setSelectedId(a.id);
      const msg = errorStatus(e) === 409 ? `Already decided: ${errorMessage(e)}` : errorMessage(e);
      setDecideError(msg);
      toast.error(msg);
    },
    onSuccess: (_r, { d }) => toast.success(d === "approve" ? "Approved — scheduling is unlocked" : d === "reject" ? "Rejected" : "Changes requested — back to draft"),
    onSettled: () => { void qc.invalidateQueries({ queryKey: ["approvals"] }); void qc.invalidateQueries({ queryKey: ["content"] }); void qc.invalidateQueries({ queryKey: ["calendar"] }); },
  });
  const bulk = useMutation({
    mutationFn: async (targets: Approval[]) => {
      const results = await Promise.allSettled(targets.map((a) => approvalsApi.approve(a.id, {})));
      return { ok: results.filter((r) => r.status === "fulfilled").length, failed: results.flatMap((r) => (r.status === "rejected" ? [errorMessage(r.reason)] : [])) };
    },
    onSuccess: ({ ok, failed }) => {
      if (ok) toast.success(`Approved ${ok} item${ok === 1 ? "" : "s"}`);
      if (failed.length) toast.error(`${failed.length} not approved: ${failed[0]}`);
      setChecked(new Set()); setBulkOpen(false);
      void qc.invalidateQueries({ queryKey: ["approvals"] }); void qc.invalidateQueries({ queryKey: ["content"] });
    },
  });
  const bulkTargets = items.filter((a) => checked.has(a.id) && (includeWarned || !warned(a)));

  // j/k navigation (inactive while typing)
  const nav = useRef({ next: () => {}, prev: () => {} });
  useEffect(() => {
    nav.current = {
      next: () => { const n = items[idx + 1]; if (n) setSelectedId(n.id); },
      prev: () => { const p = items[idx - 1]; if (p) setSelectedId(p.id); },
    };
  });
  useEffect(() => {
    const h = (e: KeyboardEvent) => {
      const t = e.target as HTMLElement | null;
      if (t && (t.tagName === "INPUT" || t.tagName === "TEXTAREA" || t.isContentEditable)) return;
      if (e.metaKey || e.ctrlKey || e.altKey) return;
      if (e.key === "j") nav.current.next();
      if (e.key === "k") nav.current.prev();
      if (e.key === "c" || e.key === "r") { const el = document.getElementById("decision-comment"); if (el) { e.preventDefault(); el.focus(); } }
    };
    window.addEventListener("keydown", h);
    return () => window.removeEventListener("keydown", h);
  }, []);

  const listPane = (
    <div className="space-y-3">
      <div className="flex flex-wrap items-center gap-2">
        <Tabs value={tab} onValueChange={(v) => { setTab(v as "pending" | "decided"); setChecked(new Set()); setSelectedId(null); }}>
          <TabsList><TabsTrigger value="pending">Pending{tab === "pending" && items.length ? ` (${items.length})` : ""}</TabsTrigger><TabsTrigger value="decided">Decided</TabsTrigger></TabsList>
        </Tabs>
        <Select value={brand} onValueChange={setBrand}><SelectTrigger size="sm" className="w-36" aria-label="Brand"><SelectValue /></SelectTrigger>
          <SelectContent><SelectItem value={ALL}>All brands</SelectItem>{brands.map((b) => <SelectItem key={b.id} value={b.id}>{b.name}</SelectItem>)}</SelectContent></Select>
        <label className="flex items-center gap-1.5 text-xs"><Checkbox checked={mine} onCheckedChange={(c) => setMine(c === true)} /> Mine</label>
      </div>
      {tab === "pending" && canApprove && items.length > 0 && (
        <div className="flex items-center gap-2 text-xs">
          <label className="flex items-center gap-1.5"><Checkbox checked={checked.size === items.length && items.length > 0} onCheckedChange={(c) => setChecked(c === true ? new Set(items.map((a) => a.id)) : new Set())} /> Select all</label>
          <Button size="xs" variant="outline" disabled={!checked.size} onClick={() => setBulkOpen(true)}><CheckCheck /> Bulk approve{checked.size ? ` (${checked.size})` : ""}</Button>
        </div>
      )}
      {list.isLoading && <div className="space-y-2">{Array.from({ length: 5 }).map((_, i) => <Skeleton key={i} className="h-14" />)}</div>}
      {list.error && <QueryError error={list.error} onRetry={() => list.refetch()} notAvailableText="The approvals API isn't available on this backend yet." />}
      {list.data && items.length === 0 && <EmptyState icon={Inbox} title={tab === "pending" ? "Nothing waiting for you." : "No decisions yet."} />}
      {Array.from(groups.entries()).map(([name, group]) => (
        <section key={name} aria-label={name}>
          <p className="mb-1 text-[11px] font-semibold uppercase tracking-wide text-muted-foreground">◆ {name} ({group.length})</p>
          <ul className="space-y-1">
            {group.map((a) => (
              <li key={a.id} className={cn("flex items-start gap-2 rounded-md border p-2", current === a.id && "border-primary bg-primary/5")}>
                {tab === "pending" && canApprove && <Checkbox className="mt-1" checked={checked.has(a.id)} onCheckedChange={(c) => setChecked((s) => { const n = new Set(s); if (c === true) n.add(a.id); else n.delete(a.id); return n; })} aria-label={`Select ${approvalTitle(a)}`} />}
                <button type="button" className="min-w-0 flex-1 text-left" onClick={() => { setSelectedId(a.id); setDecideError(null); }}>
                  <p className="flex items-center gap-1 text-sm font-medium">{approvalPlatforms(a).slice(0, 4).map((p) => <PlatformIcon key={p} platform={p} size={14} />)}<span className="truncate">{approvalTitle(a)}</span></p>
                  <p className="text-xs text-muted-foreground">
                    {isAiRequested(a) && <Sparkles className="mr-0.5 inline h-3 w-3 text-ai" aria-label="AI-assisted" />}{a.requested_by_name ?? (a.requested_by === userId ? "you" : "requested")} · {relTime(a.created_at)}{a.expires_at ? ` · expires ${relTime(a.expires_at)}` : ""}
                    {warned(a) && <span className="ml-1 text-amber-700 dark:text-amber-300">⚠</span>}
                  </p>
                </button>
                {tab === "decided" && <StatusChip status={a.status} />}
              </li>
            ))}
          </ul>
        </section>
      ))}
    </div>
  );

  const detail = current ? (
    <ApprovalDetail key={current} id={current} canDecide={canApprove} deciding={decide.isPending} decideError={decideError}
                    onDecide={(a, d, comment, ack) => decide.mutate({ a, d, comment, ack })}
                    position={idx >= 0 ? { index: idx, total: items.length } : undefined}
                    onPrev={idx > 0 ? () => setSelectedId(items[idx - 1].id) : undefined} onNext={idx >= 0 && idx < items.length - 1 ? () => setSelectedId(items[idx + 1].id) : undefined}
                    onBack={wide ? undefined : () => setSelectedId(null)} />
  ) : wide && items.length > 0 ? <p className="text-sm text-muted-foreground">Select an item.</p> : null;

  return (
    <div>
      <PageHeader title="Approvals" description={canApprove ? "Everything needed to decide — previews, critic, fact-check, sources and AI provenance." : "Your approval requests (read-only)."} />
      {wide ? (
        <div className="grid gap-6 lg:grid-cols-[340px_minmax(0,1fr)]">
          <aside className="lg:sticky lg:top-0 lg:max-h-[calc(100vh-8rem)] lg:overflow-y-auto">{listPane}</aside>
          <section aria-label="Approval item">{detail}</section>
        </div>
      ) : current ? detail : listPane}
      <Dialog open={bulkOpen} onOpenChange={setBulkOpen}>
        <DialogContent>
          <DialogHeader><DialogTitle>Bulk approve</DialogTitle><DialogDescription>Approves the exact versions shown in each request. Items with warnings (policy flags, unverified claims) are excluded unless you include them.</DialogDescription></DialogHeader>
          <ul className="max-h-64 space-y-1 overflow-y-auto text-sm">
            {items.filter((a) => checked.has(a.id)).map((a) => <li key={a.id} className={cn("flex items-center gap-2", warned(a) && !includeWarned && "text-muted-foreground line-through")}>{warned(a) ? "⚠" : "✓"} {approvalTitle(a)}</li>)}
          </ul>
          {items.some((a) => checked.has(a.id) && warned(a)) && <label className="flex items-center gap-2 text-sm"><Checkbox checked={includeWarned} onCheckedChange={(c) => setIncludeWarned(c === true)} /> Include items with warnings</label>}
          <DialogFooter>
            <Button variant="outline" onClick={() => setBulkOpen(false)}>Cancel</Button>
            <Button disabled={!bulkTargets.length || bulk.isPending} onClick={() => bulk.mutate(bulkTargets)}>{bulk.isPending && <Loader2 className="animate-spin" />} Approve {bulkTargets.length}</Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </div>
  );
}

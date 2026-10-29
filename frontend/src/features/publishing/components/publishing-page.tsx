"use client";
import { useState } from "react";
import Link from "next/link";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Ban, ExternalLink, History, Loader2, MoreHorizontal, Pause, Pencil, Play, RotateCw, Send, Trash2 } from "lucide-react";
import { toast } from "sonner";
import { Button } from "@/components/ui/button";
import { Dialog, DialogContent, DialogDescription, DialogHeader, DialogTitle } from "@/components/ui/dialog";
import { DropdownMenu, DropdownMenuContent, DropdownMenuItem, DropdownMenuSeparator, DropdownMenuTrigger } from "@/components/ui/dropdown-menu";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { Sheet, SheetContent, SheetDescription, SheetHeader, SheetTitle } from "@/components/ui/sheet";
import { Skeleton } from "@/components/ui/skeleton";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { EmptyState } from "@/components/shared/empty-state";
import { PageHeader } from "@/components/shared/page-header";
import { PlatformIcon } from "@/components/shared/platform-icon";
import { StatusChip } from "@/components/shared/status-chip";
import { ConfirmDialog } from "@/features/common/components/confirm-dialog";
import { QueryError } from "@/features/common/components/query-state";
import { useActiveBrand, usePermissions, useWorkspacePath } from "@/features/common/hooks";
import { errorMessage, fmtDateTime, isNotAvailable, problemCode, relTime, toItems } from "@/features/common/utils";
import { contentApi } from "@/features/studio/api";
import { calendarApi, normalizeCalendar, type CalendarCard } from "@/features/calendar/api";
import { PLATFORMS, platformMeta } from "@/lib/platforms";
import { cn } from "@/lib/utils";
import { isDeadLetter, personName, publishingApi, retryTarget, schedulingApi, type PublishAttempt, type PublishedPost, type ScheduledPost } from "../api";
import { AccountHealthStrip } from "./account-health";
import { ScheduleForm } from "./schedule-form";

const ALL = "all";
const QUEUE_STATUSES = ["scheduled", "queued", "publishing", "failed", "paused", "cancelled"];
const postPlatform = (p: ScheduledPost) => p.platform ?? p.social_account?.platform ?? p.variant?.platform ?? null;

/** Publishing (doc 24 §16): health strip, queue, dead letter, published posts, attempts. The LLM never publishes — rows name the approving human. */
export function PublishingPage() {
  const qc = useQueryClient();
  const ws = useWorkspacePath();
  const { brandId, timezone } = useActiveBrand();
  const { canSchedule, canManage } = usePermissions();
  const [status, setStatus] = useState(ALL);
  const [platform, setPlatform] = useState(ALL);
  const [attemptsFor, setAttemptsFor] = useState<ScheduledPost | null>(null);
  const [cancelling, setCancelling] = useState<ScheduledPost | null>(null);
  const [deleting, setDeleting] = useState<PublishedPost | null>(null);
  const [publishNowOpen, setPublishNowOpen] = useState(false);
  const f = { status: status === ALL ? undefined : status, brand_id: brandId };
  const platformFilter = platform === ALL ? undefined : platform;
  const queue = useQuery({ queryKey: ["publishing", "queue", f], queryFn: () => publishingApi.queue(f), refetchInterval: 30_000 });
  const published = useQuery({ queryKey: ["publishing", "published", { platform: platformFilter, brand_id: brandId }], queryFn: () => publishingApi.published({ platform: platformFilter, brand_id: brandId }) });
  const rows = toItems(queue.data).filter((p) => !platformFilter || postPlatform(p) === platformFilter);
  const publishedRows = toItems(published.data);
  // Queue/published rows carry ids only: join titles + content ids from the calendar over the same time window.
  const times = [...rows.map((r) => r.scheduled_at), ...publishedRows.map((p) => p.published_at)].map((t) => new Date(t).getTime()).filter((n) => Number.isFinite(n));
  const lookupFrom = times.length ? `${new Date(Math.min(...times) - 86_400_000).toISOString().slice(0, 10)}T00:00:00Z` : null;
  const lookupTo = times.length ? `${new Date(Math.max(...times) + 86_400_000).toISOString().slice(0, 10)}T23:59:59Z` : null;
  const lookup = useQuery({
    queryKey: ["publishing", "titles", brandId, lookupFrom, lookupTo],
    queryFn: () => calendarApi.get({ from: lookupFrom as string, to: lookupTo as string, view: "list", brand_id: brandId, tray: false }),
    enabled: !!lookupFrom && !!lookupTo, retry: false, staleTime: 60_000,
  });
  const cardBy = new Map<string, CalendarCard>(normalizeCalendar(lookup.data).cards.map((c) => [c.scheduled_post_id ?? c.id, c]));
  const postTitle = (p: ScheduledPost) => p.title ?? p.content?.title ?? cardBy.get(p.id)?.title ?? p.variant?.text?.slice(0, 60) ?? (lookup.isLoading ? "…" : "Untitled post");
  const contentIdOf = (p: ScheduledPost) => p.content_item_id ?? p.content?.id ?? cardBy.get(p.id)?.content_item_id ?? null;
  const publishedTitle = (pp: PublishedPost) => pp.title ?? (pp.scheduled_post_id ? cardBy.get(pp.scheduled_post_id)?.title : null) ?? pp.external_id;
  const dead = rows.filter(isDeadLetter);
  const live = rows.filter((r) => !isDeadLetter(r));
  const invalidate = () => { void qc.invalidateQueries({ queryKey: ["publishing"] }); void qc.invalidateQueries({ queryKey: ["calendar"] }); };

  const action = useMutation({
    mutationFn: ({ kind, post }: { kind: "retry" | "pause" | "resume" | "cancel"; post: ScheduledPost }) =>
      kind === "retry" ? publishingApi.retry(retryTarget(post)) : kind === "pause" ? schedulingApi.pause(post.id) : kind === "resume" ? schedulingApi.resume(post.id) : schedulingApi.cancel(post.id),
    onSuccess: (_r, { kind }) => { toast.success(kind === "retry" ? "Retry queued — a fresh pre-flight runs first" : kind === "pause" ? "Paused" : kind === "resume" ? "Resumed" : "Cancelled"); setCancelling(null); invalidate(); },
    onError: (e) => { setCancelling(null); toast.error(errorMessage(e)); },
  });
  const del = useMutation({
    mutationFn: (p: PublishedPost) => publishingApi.deletePublished(p.id),
    onSuccess: () => { toast.success("Deleted on the platform"); setDeleting(null); invalidate(); },
    onError: (e, p) => {
      setDeleting(null);
      if (problemCode(e) === "platform_does_not_support_delete") toast.error(`${platformMeta(p.platform).label} doesn't allow deleting via API — delete it in the ${platformMeta(p.platform).label} app.`);
      else toast.error(errorMessage(e));
    },
  });

  const rowActions = (p: ScheduledPost) => {
    if (!canSchedule) return null;
    const cid = contentIdOf(p);
    return (
      <DropdownMenu>
        <DropdownMenuTrigger asChild><Button size="icon-sm" variant="ghost" aria-label="Post actions"><MoreHorizontal /></Button></DropdownMenuTrigger>
        <DropdownMenuContent align="end">
          {p.status === "failed" && <DropdownMenuItem onClick={() => action.mutate({ kind: "retry", post: p })}><RotateCw /> Retry now</DropdownMenuItem>}
          {p.status === "scheduled" && <DropdownMenuItem onClick={() => action.mutate({ kind: "pause", post: p })}><Pause /> Pause</DropdownMenuItem>}
          {p.status === "paused" && <DropdownMenuItem onClick={() => action.mutate({ kind: "resume", post: p })}><Play /> Resume</DropdownMenuItem>}
          {cid && <DropdownMenuItem asChild><Link href={ws(`studio/${cid}${postPlatform(p) ? `?variant=${postPlatform(p)}&panel=schedule` : ""}`)}><Pencil /> Edit in Studio</Link></DropdownMenuItem>}
          <DropdownMenuItem onClick={() => setAttemptsFor(p)}><History /> View attempts</DropdownMenuItem>
          {["scheduled", "queued", "paused", "failed"].includes(p.status) && <><DropdownMenuSeparator /><DropdownMenuItem className="text-destructive" onClick={() => setCancelling(p)}><Ban /> Cancel</DropdownMenuItem></>}
        </DropdownMenuContent>
      </DropdownMenu>
    );
  };
  const nextRetry = (p: ScheduledPost) => (p.next_attempt_at ? relTime(p.next_attempt_at) : "—");
  const errorCell = (p: ScheduledPost) => p.last_error ? <span className="line-clamp-2 text-xs text-destructive" title={p.last_error}>{p.last_error_category && <span className="mr-1 font-mono">{p.last_error_category}</span>}{p.last_error}</span> : <span className="text-muted-foreground">—</span>;

  return (
    <div className="space-y-6">
      <PageHeader title="Publishing" description="Queue, failures and platform health. Posts publish only from approved versions through the publishing service."
                  actions={canSchedule && <Button size="sm" onClick={() => setPublishNowOpen(true)}><Send /> Publish now</Button>} />
      <section aria-label="Platform health" className="space-y-2">
        <p className="text-xs font-semibold uppercase tracking-wide text-muted-foreground">Health</p>
        <AccountHealthStrip brandId={brandId} />
      </section>

      <section aria-labelledby="queue-h" className="space-y-3">
        <div className="flex flex-wrap items-center gap-2">
          <h2 id="queue-h" className="mr-2 text-lg font-semibold">Queue</h2>
          <div className="flex flex-wrap rounded-md border p-0.5 text-xs" role="radiogroup" aria-label="Status">
            {[ALL, ...QUEUE_STATUSES].map((s) => <button key={s} type="button" role="radio" aria-checked={status === s} onClick={() => setStatus(s)} className={cn("rounded px-2 py-1 capitalize", status === s && "bg-secondary font-medium")}>{s}</button>)}
          </div>
          <Select value={platform} onValueChange={setPlatform}><SelectTrigger size="sm" className="w-36" aria-label="Platform"><SelectValue /></SelectTrigger>
            <SelectContent><SelectItem value={ALL}>All platforms</SelectItem>{PLATFORMS.map((p) => <SelectItem key={p.id} value={p.id}>{p.label}</SelectItem>)}</SelectContent></Select>
          <span className="ml-auto text-xs text-muted-foreground">Times in {timezone}</span>
        </div>
        {queue.isLoading ? <div className="space-y-2">{Array.from({ length: 5 }).map((_, i) => <Skeleton key={i} className="h-11" />)}</div>
          : queue.error ? <QueryError error={queue.error} onRetry={() => queue.refetch()} title="Couldn't load the queue" notAvailableText="The publishing queue isn't available on this backend yet." />
          : live.length === 0 ? <EmptyState icon={Send} title="Queue is empty." description={status !== ALL ? "No posts with this status." : "Approved posts you schedule appear here until they publish."} />
          : (
            <>
              <div className="hidden rounded-lg border md:block">
                <Table>
                  <TableHeader><TableRow><TableHead>Post</TableHead><TableHead>Account</TableHead><TableHead>When</TableHead><TableHead>Status</TableHead><TableHead className="text-right">Att.</TableHead><TableHead>Next retry</TableHead><TableHead>Error</TableHead><TableHead className="w-10" /></TableRow></TableHeader>
                  <TableBody>
                    {live.map((p) => (
                      <TableRow key={p.id}>
                        <TableCell className="max-w-[260px]"><span className="flex items-center gap-1.5">{postPlatform(p) && <PlatformIcon platform={postPlatform(p) as string} size={16} />}<span className="truncate">{postTitle(p)}</span></span>
                          {(personName(p.approved_by) || personName(p.created_by)) && <span className="block text-[11px] text-muted-foreground">{personName(p.approved_by) ? `approved by ${personName(p.approved_by)}` : `scheduled by ${personName(p.created_by)}`}</span>}</TableCell>
                        <TableCell className="text-sm">{p.social_account?.display_name ?? "—"}</TableCell>
                        <TableCell className="whitespace-nowrap text-sm tabular-nums">{fmtDateTime(p.scheduled_at, timezone, { weekday: "short" })}</TableCell>
                        <TableCell><StatusChip status={p.status} />{p.pause_reason && <span className="block text-[11px] text-muted-foreground">{p.pause_reason.replace(/_/g, " ")}</span>}</TableCell>
                        <TableCell className="text-right tabular-nums">{p.attempt_count ?? 0}/{p.max_attempts ?? 5}</TableCell>
                        <TableCell className="text-sm">{nextRetry(p)}</TableCell>
                        <TableCell className="max-w-[240px]">{errorCell(p)}</TableCell>
                        <TableCell>{rowActions(p)}</TableCell>
                      </TableRow>
                    ))}
                  </TableBody>
                </Table>
              </div>
              <div className="space-y-4 md:hidden">
                {QUEUE_STATUSES.filter((s) => live.some((p) => p.status === s)).map((s) => (
                  <section key={s}><p className="mb-1"><StatusChip status={s} /></p>
                    <ul className="space-y-2">{live.filter((p) => p.status === s).map((p) => (
                      <li key={p.id} className="flex items-start gap-2 rounded-lg border p-3">
                        <div className="min-w-0 flex-1">
                          <p className="flex items-center gap-1.5 font-medium">{postPlatform(p) && <PlatformIcon platform={postPlatform(p) as string} size={16} />}<span className="truncate">{postTitle(p)}</span></p>
                          <p className="text-xs text-muted-foreground">{p.social_account?.display_name} · {fmtDateTime(p.scheduled_at, timezone)} · {p.attempt_count ?? 0}/{p.max_attempts ?? 5}</p>
                          {p.last_error && <p className="mt-1 text-xs text-destructive">{p.last_error}</p>}
                        </div>
                        {rowActions(p)}
                      </li>))}</ul>
                  </section>
                ))}
              </div>
            </>
          )}
      </section>

      {dead.length > 0 && (
        <section aria-labelledby="dead-h" className="space-y-2 rounded-lg border border-destructive/40 p-4">
          <h2 id="dead-h" className="text-lg font-semibold">Dead letter ({dead.length}) <span className="text-sm font-normal text-muted-foreground">retries exhausted — needs a human</span></h2>
          <ul className="space-y-2">
            {dead.map((p) => {
              const authErr = /token|oauth|auth|expired|revoked|190/i.test(`${p.last_error ?? ""} ${p.last_error_category ?? ""}`);
              const cid = contentIdOf(p);
              return (
                <li key={p.id} className="rounded-md border p-3">
                  <div className="flex flex-wrap items-center gap-2 text-sm">
                    {postPlatform(p) && <PlatformIcon platform={postPlatform(p) as string} size={16} />}<span className="font-medium">{postTitle(p)}</span>
                    <span className="text-muted-foreground">{p.social_account?.display_name} · {fmtDateTime(p.scheduled_at, timezone)} · {p.attempt_count ?? 0}/{p.max_attempts ?? 5}</span>
                  </div>
                  <p className="mt-1 font-mono text-xs text-destructive">{p.last_error_category ? `${p.last_error_category}: ` : ""}{p.last_error ?? "Unknown error"}</p>
                  {canSchedule && (
                    <div className="mt-2 flex flex-wrap gap-2">
                      {authErr && <Button size="xs" asChild><Link href={ws("settings/social-accounts")}>Reconnect account</Link></Button>}
                      <Button size="xs" variant="outline" disabled={action.isPending} onClick={() => action.mutate({ kind: "retry", post: p })}><RotateCw /> Retry</Button>
                      {cid && <Button size="xs" variant="outline" asChild><Link href={ws(`studio/${cid}`)}><Pencil /> Edit</Link></Button>}
                      <Button size="xs" variant="ghost" onClick={() => setAttemptsFor(p)}><History /> Attempts</Button>
                      <Button size="xs" variant="ghost" className="text-destructive" onClick={() => setCancelling(p)}><Ban /> Cancel</Button>
                    </div>
                  )}
                </li>
              );
            })}
          </ul>
        </section>
      )}

      <section aria-labelledby="pub-h" className="space-y-3">
        <h2 id="pub-h" className="text-lg font-semibold">Published</h2>
        {published.isLoading ? <Skeleton className="h-32" />
          : published.error ? <QueryError error={published.error} onRetry={() => published.refetch()} notAvailableText="Published posts aren't available on this backend yet." />
          : publishedRows.length === 0 ? <p className="text-sm text-muted-foreground">Nothing published yet.</p>
          : (
            <div className="overflow-x-auto rounded-lg border">
              <Table>
                <TableHeader><TableRow><TableHead>Post</TableHead><TableHead>Account</TableHead><TableHead>Published</TableHead><TableHead>Link</TableHead><TableHead className="w-10" /></TableRow></TableHeader>
                <TableBody>
                  {publishedRows.map((p) => (
                    <TableRow key={p.id} className={cn(p.deleted_at && "opacity-60")}>
                      <TableCell className="max-w-[280px]"><span className="flex items-center gap-1.5"><PlatformIcon platform={p.platform} size={16} /><span className="truncate">{publishedTitle(p)}</span></span>
                        {personName(p.approved_by) && <span className="block text-[11px] text-muted-foreground">approved by {personName(p.approved_by)}</span>}</TableCell>
                      <TableCell className="text-sm">{p.social_account?.display_name ?? "—"}</TableCell>
                      <TableCell className="whitespace-nowrap text-sm">{fmtDateTime(p.published_at, timezone)}</TableCell>
                      <TableCell>{p.deleted_at ? <span className="text-xs text-muted-foreground">Deleted on {platformMeta(p.platform).label}</span> : p.external_url ? <a href={p.external_url} target="_blank" rel="noreferrer" className="inline-flex items-center gap-1 text-sm text-primary hover:underline">View <ExternalLink className="h-3 w-3" /></a> : "—"}</TableCell>
                      <TableCell>{canManage && !p.deleted_at && <Button size="icon-sm" variant="ghost" aria-label="Delete on platform" title="Delete on platform" onClick={() => setDeleting(p)}><Trash2 /></Button>}</TableCell>
                    </TableRow>
                  ))}
                </TableBody>
              </Table>
            </div>
          )}
      </section>

      <AttemptsSheet post={attemptsFor} title={attemptsFor ? postTitle(attemptsFor) : ""} onOpenChange={(o) => !o && setAttemptsFor(null)} tz={timezone} />
      <ConfirmDialog open={!!cancelling} onOpenChange={(o) => !o && setCancelling(null)} destructive title="Cancel this post?" confirmLabel="Cancel post" pending={action.isPending}
                     onConfirm={() => cancelling && action.mutate({ kind: "cancel", post: cancelling })}
                     description={<p>“{cancelling ? postTitle(cancelling) : ""}” won’t be published to {cancelling?.social_account?.display_name ?? "the account"}. The approved content stays in Studio.</p>} />
      <ConfirmDialog open={!!deleting} onOpenChange={(o) => !o && setDeleting(null)} destructive title={`Delete on ${deleting ? platformMeta(deleting.platform).label : ""}?`} confirmLabel="Delete on platform" pending={del.isPending}
                     typeToConfirm={deleting ? platformMeta(deleting.platform).label : undefined} onConfirm={() => deleting && del.mutate(deleting)}
                     description={<p>This will delete the post on {deleting ? platformMeta(deleting.platform).label : "the platform"}{deleting?.social_account ? ` (${deleting.social_account.display_name})` : ""}; its likes, comments and metrics will be lost and analytics stop syncing for it. This cannot be undone.</p>} />
      <PublishNowDialog open={publishNowOpen} onOpenChange={setPublishNowOpen} brandId={brandId} tz={timezone} />
    </div>
  );
}

function AttemptDetail({ id }: { id: string }) {
  const q = useQuery({ queryKey: ["publishing", "attempts", id], queryFn: () => publishingApi.attempt(id), retry: false });
  if (q.isLoading) return <Skeleton className="mt-1 h-10" />;
  if (q.error) return <p className="mt-1 text-xs text-muted-foreground">{isNotAvailable(q.error) ? "Attempt details unavailable." : errorMessage(q.error)}</p>;
  const a = q.data;
  if (!a) return null;
  return (
    <div className="mt-1 space-y-1">
      {a.idempotency_key && <p className="font-mono text-[11px] text-muted-foreground">key {a.idempotency_key}</p>}
      {a.platform_response ? <pre className="max-h-48 overflow-auto rounded bg-muted p-2 text-[11px]">{JSON.stringify(a.platform_response, null, 2)}</pre> : <p className="text-[11px] text-muted-foreground">No platform response recorded.</p>}
      {a.state && Object.keys(a.state).length > 0 && <pre className="max-h-32 overflow-auto rounded bg-muted p-2 text-[11px]">state: {JSON.stringify(a.state, null, 2)}</pre>}
    </div>
  );
}

function AttemptRow({ a, tz }: { a: PublishAttempt; tz: string }) {
  const [open, setOpen] = useState(false);
  return (
    <div className="rounded-md border p-3 text-sm">
      <div className="flex items-center gap-2"><span className="font-medium">#{a.attempt_no}</span><StatusChip status={a.status} /><span className="ml-auto text-xs text-muted-foreground">{fmtDateTime(a.started_at, tz)}{a.finished_at ? ` → ${fmtDateTime(a.finished_at, tz, { month: undefined, day: undefined })}` : ""}</span></div>
      {(a.error_category || a.error_code || a.error_message) && <p className="mt-1 font-mono text-xs text-destructive">{[a.error_category, a.error_code].filter(Boolean).join(" · ")}{a.error_message ? ` — ${a.error_message}` : ""}</p>}
      {a.segments_done ? <p className="mt-1 text-xs text-muted-foreground">{a.segments_done} segment(s) already published — a retry resumes, it doesn&apos;t restart.</p> : null}
      {a.status === "ambiguous" && <p className="mt-1 text-xs text-warning">Ambiguous result — reconciled before any retry; never retried blindly.</p>}
      <button type="button" className="mt-1 text-xs text-muted-foreground hover:text-foreground" onClick={() => setOpen((o) => !o)} aria-expanded={open}>{open ? "Hide" : "Show"} raw platform response</button>
      {open && <AttemptDetail id={a.id} />}
    </div>
  );
}

function AttemptsSheet({ post, title, onOpenChange, tz }: { post: ScheduledPost | null; title: string; onOpenChange: (o: boolean) => void; tz: string }) {
  const attempts = [...(post?.attempts ?? [])].sort((a, b) => b.attempt_no - a.attempt_no);
  return (
    <Sheet open={!!post} onOpenChange={onOpenChange}>
      <SheetContent className="w-full overflow-y-auto sm:max-w-lg">
        <SheetHeader><SheetTitle>Publish attempts</SheetTitle><SheetDescription>{title}{post ? ` · ${post.attempt_count ?? 0}/${post.max_attempts ?? 5} attempts` : ""}</SheetDescription></SheetHeader>
        <div className="space-y-3 px-4 pb-6">
          {post?.last_error && <p className="rounded-md bg-destructive/[0.06] p-2 text-xs text-destructive">Last error: {post.last_error}</p>}
          {attempts.length === 0 && <p className="text-sm text-muted-foreground">No attempts yet.</p>}
          {attempts.map((a) => <AttemptRow key={a.id} a={a} tz={tz} />)}
        </div>
      </SheetContent>
    </Sheet>
  );
}

function PublishNowDialog({ open, onOpenChange, brandId, tz }: { open: boolean; onOpenChange: (o: boolean) => void; brandId: string | null; tz: string }) {
  const approved = useQuery({ queryKey: ["publishing", "approved-content", brandId], queryFn: () => contentApi.list({ status: "approved", brand_id: brandId }), enabled: open });
  const [contentId, setContentId] = useState<string>("");
  const [variantId, setVariantId] = useState<string>("");
  const items = toItems(approved.data);
  // List rows have no variants: load the chosen item.
  const full = useQuery({ queryKey: ["content", contentId], queryFn: () => contentApi.get(contentId), enabled: open && !!contentId });
  const item = full.data;
  const variant = item?.variants?.find((v) => v.id === variantId);
  return (
    <Dialog open={open} onOpenChange={(o) => { if (!o) { setContentId(""); setVariantId(""); } onOpenChange(o); }}>
      <DialogContent className="sm:max-w-lg">
        <DialogHeader><DialogTitle>Publish now</DialogTitle><DialogDescription>Only approved platform versions can be published.</DialogDescription></DialogHeader>
        {approved.isLoading && <Loader2 className="h-4 w-4 animate-spin" />}
        {approved.error && <QueryError error={approved.error} onRetry={() => approved.refetch()} />}
        {approved.data && items.length === 0 && <p className="text-sm text-muted-foreground">No approved content.</p>}
        {items.length > 0 && (
          <div className="grid gap-3 sm:grid-cols-2">
            <Select value={contentId} onValueChange={(v) => { setContentId(v); setVariantId(""); }}><SelectTrigger className="w-full" aria-label="Content"><SelectValue placeholder="Approved content" /></SelectTrigger>
              <SelectContent>{items.map((c) => <SelectItem key={c.id} value={c.id}>{c.title}</SelectItem>)}</SelectContent></Select>
            <Select value={variantId} onValueChange={setVariantId} disabled={!item}><SelectTrigger className="w-full" aria-label="Platform version"><SelectValue placeholder={full.isLoading ? "Loading…" : "Platform version"} /></SelectTrigger>
              <SelectContent>{(item?.variants ?? []).map((v) => <SelectItem key={v.id} value={v.id} disabled={v.status !== "approved"}><PlatformIcon platform={v.platform} size={14} /> {platformMeta(v.platform).label}{v.status !== "approved" ? ` · ${v.status.replace(/_/g, " ")}` : ""}</SelectItem>)}</SelectContent></Select>
          </div>
        )}
        {variant && item && <ScheduleForm key={variant.id} variant={variant} contentApproved={item.status === "approved"} brandId={brandId} defaultTz={tz} onDone={() => onOpenChange(false)} />}
      </DialogContent>
    </Dialog>
  );
}

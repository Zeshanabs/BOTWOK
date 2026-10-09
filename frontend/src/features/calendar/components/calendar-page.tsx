"use client";
import { useState } from "react";
import { useRouter, useSearchParams } from "next/navigation";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { DndContext, DragOverlay, PointerSensor, useSensor, useSensors, type DragEndEvent, type DragStartEvent } from "@dnd-kit/core";
import { AlertTriangle, CalendarDays, ChevronLeft, ChevronRight, Inbox, PanelLeftClose, PanelLeftOpen, Plus } from "lucide-react";
import { toast } from "sonner";
import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert";
import { Button } from "@/components/ui/button";
import { Dialog, DialogContent, DialogDescription, DialogHeader, DialogTitle } from "@/components/ui/dialog";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { Skeleton } from "@/components/ui/skeleton";
import { EmptyState } from "@/components/shared/empty-state";
import { ConfirmDialog } from "@/features/common/components/confirm-dialog";
import { QueryError } from "@/features/common/components/query-state";
import { useActiveBrand, useCampaigns, useMediaQuery, usePermissions, usePillars, useWorkspacePath } from "@/features/common/hooks";
import { addDays, addMonths, dayKey, dayStartIso, keyLabel, parseDayKey, startOfMonth, startOfWeek, timezoneOptions, toLocalInput, tzParts, zonedToUtc } from "@/features/common/tz";
import { errorMessage, errorStatus, fmtDateTime, toItems } from "@/features/common/utils";
import { contentApi } from "@/features/studio/api";
import { schedulingApi } from "@/features/publishing/api";
import { ScheduleForm } from "@/features/publishing/components/schedule-form";
import { PLATFORMS } from "@/lib/platforms";
import { cn } from "@/lib/utils";
import { calendarApi, cardKey, cardTime, dragMode, normalizeCalendar, patchCardTime, VIEWS, type CalendarCard, type CalendarQuery, type CalendarResponse, type CalendarView } from "../api";
import { CardBody, TrayCard } from "./calendar-card";
import { BoardView, ListView, MonthView, TimeGridView } from "./calendar-views";
import { CardSheet } from "./card-sheet";
import { QuickCreateDialog } from "./quick-create-dialog";

const ALL = "all";
/** The calendar API filters scheduled posts by schedule status only. */
const STATUS_FILTERS = ["scheduled", "queued", "publishing", "published", "failed", "paused", "cancelled"];

function rangeFor(view: CalendarView, anchor: string): { days: string[]; first: string; last: string } {
  if (view === "day") return { days: [anchor], first: anchor, last: anchor };
  if (view === "week") { const s = startOfWeek(anchor); const days = Array.from({ length: 7 }, (_, i) => addDays(s, i)); return { days, first: days[0], last: days[6] }; }
  const s = startOfWeek(startOfMonth(anchor));
  const days = Array.from({ length: 42 }, (_, i) => addDays(s, i));
  if (view === "month") return { days, first: days[0], last: days[41] };
  const m0 = startOfMonth(anchor);
  const mdays: string[] = [];
  for (let d = m0; parseDayKey(d).m === parseDayKey(m0).m; d = addDays(d, 1)) mdays.push(d);
  return { days: mdays, first: mdays[0], last: mdays[mdays.length - 1] };
}

/** Calendar (doc 24 §14): month/week/day/list/board, filters, tz, drag-to-reschedule with optimistic rollback, tray → schedule. */
export function CalendarPage() {
  const router = useRouter();
  const params = useSearchParams();
  const qc = useQueryClient();
  const ws = useWorkspacePath();
  const { brandId, timezone: brandTz } = useActiveBrand();
  const { canSchedule, canCreate } = usePermissions();
  const mobile = !useMediaQuery("(min-width: 768px)", true);
  const pillars = toItems(usePillars(brandId).data);
  const campaigns = toItems(useCampaigns(brandId).data);

  const [viewState, setViewState] = useState<CalendarView | null>(() => (VIEWS.find((v) => v === params.get("view")) ?? null));
  const view: CalendarView = viewState ?? (mobile ? "list" : "month");
  const [tzState, setTzState] = useState<string | null>(params.get("tz"));
  const tz = tzState ?? brandTz;
  const [anchorState, setAnchor] = useState<string | null>(params.get("date"));
  const today = dayKey(new Date(), tz);
  const anchor = anchorState ?? today;
  const [platform, setPlatform] = useState(ALL);
  const [status, setStatus] = useState(ALL);
  const [campaign, setCampaign] = useState(ALL);
  const [pillar, setPillar] = useState(ALL);
  const [trayOpen, setTrayOpen] = useState(true);
  const [openCard, setOpenCard] = useState<CalendarCard | null>(null);
  const [dragging, setDragging] = useState<CalendarCard | null>(null);
  const [pendingQueued, setPendingQueued] = useState<{ card: CalendarCard; iso: string } | null>(null);
  const [traySchedule, setTraySchedule] = useState<{ card: CalendarCard; iso: string } | null>(null);
  const [quick, setQuick] = useState<{ open: boolean; local: string }>({ open: false, local: "" });

  const sync = (next: { view?: CalendarView; date?: string; tz?: string }) => {
    const sp = new URLSearchParams(params.toString());
    if (next.view) sp.set("view", next.view);
    if (next.date) sp.set("date", next.date);
    if (next.tz) sp.set("tz", next.tz);
    router.replace(`?${sp.toString()}`, { scroll: false });
  };
  const setView = (v: CalendarView) => { setViewState(v); sync({ view: v }); };
  const goTo = (d: string) => { setAnchor(d); sync({ date: d }); };
  const setTz = (z: string) => { setTzState(z); sync({ tz: z }); };
  const step = (dir: number) => goTo(view === "day" ? addDays(anchor, dir) : view === "week" ? addDays(anchor, dir * 7) : addMonths(anchor, dir));

  const range = rangeFor(view, anchor);
  const query: CalendarQuery = {
    from: dayStartIso(range.first, tz), to: dayStartIso(addDays(range.last, 1), tz), view, brand_id: brandId, tz,
    platform: platform === ALL ? undefined : platform, status: status === ALL ? undefined : status, campaign: campaign === ALL ? undefined : campaign, pillar: pillar === ALL ? undefined : pillar,
  };
  const key = ["calendar", query] as const;
  const cal = useQuery({ queryKey: key, queryFn: () => calendarApi.get(query) });
  const { cards, tray: trayFromCal, warnings } = normalizeCalendar(cal.data);
  const trayFallback = useQuery({
    queryKey: ["calendar", "tray", brandId],
    queryFn: async (): Promise<CalendarCard[]> => {
      // Fallback when the calendar response has no tray: approved items → their approved, unscheduled variants.
      const list = toItems(await contentApi.list({ status: "approved", brand_id: brandId }));
      const full = await Promise.all(list.slice(0, 20).map((c) => contentApi.get(c.id).catch(() => null)));
      return full.flatMap((c) => (c?.variants ?? [])
        .filter((v) => v.status === "approved" && !(v.scheduled_posts ?? []).some((p) => ["scheduled", "queued", "publishing", "paused", "published"].includes(p.status)))
        .map((v): CalendarCard => ({ id: v.id, kind: "unscheduled", content_item_id: c?.id ?? "", content_variant_id: v.id, title: c?.title ?? "Untitled", platform: v.platform, format: v.format, status: "approved", social_account_id: v.social_account_id ?? null, ai_generated: c?.ai_generated })));
    },
    enabled: cal.isSuccess && trayFromCal == null && canSchedule,
    retry: false,
  });
  const tray: CalendarCard[] = trayFromCal ?? trayFallback.data ?? [];

  const byDay = new Map<string, CalendarCard[]>();
  for (const c of cards) {
    const t = cardTime(c);
    if (!t) continue;
    const k = dayKey(new Date(t), tz);
    const arr = byDay.get(k) ?? [];
    arr.push(c);
    byDay.set(k, arr);
  }
  byDay.forEach((arr) => arr.sort((a, b) => ((cardTime(a) ?? "") < (cardTime(b) ?? "") ? -1 : 1)));

  const move = useMutation({
    mutationFn: ({ card, iso }: { card: CalendarCard; iso: string; from: string | null }): Promise<unknown> => (card.scheduled_post_id
      ? schedulingApi.patch(card.scheduled_post_id, { scheduled_at: iso, timezone: tz })
      : contentApi.patch(card.content_item_id, { planned_at: iso })),
    onMutate: async ({ card, iso }) => {
      await qc.cancelQueries({ queryKey: ["calendar"] });
      const prev = qc.getQueryData<CalendarResponse | unknown[]>(key);
      qc.setQueryData(key, patchCardTime(prev, cardKey(card), iso));
      return { prev };
    },
    onError: (e, { card }, ctx) => {
      if (ctx?.prev !== undefined) qc.setQueryData(key, ctx.prev);
      const reason = errorStatus(e) === 409 ? (errorMessage(e) || "Already publishing") : errorMessage(e);
      toast.error(`“${card.title}” snapped back: ${reason}`);
    },
    onSuccess: (_r, { card, iso, from }) => {
      toast.success(`Moved to ${fmtDateTime(iso, tz, { weekday: "short" })}`, {
        action: from ? { label: "Undo", onClick: () => move.mutate({ card: { ...card, scheduled_at: card.scheduled_post_id ? iso : card.scheduled_at, planned_at: card.scheduled_post_id ? card.planned_at : iso }, iso: from, from: null }) } : undefined,
      });
    },
    onSettled: () => { void qc.invalidateQueries({ queryKey: ["calendar"] }); void qc.invalidateQueries({ queryKey: ["publishing"] }); },
  });

  const requestMove = (card: CalendarCard, iso: string) => {
    const mode = dragMode(card);
    if (mode === "locked") { toast.error(`A ${card.status} post can't be moved${card.status === "failed" ? " — handle it in Publishing" : ""}`); return; }
    if (new Date(iso).getTime() < new Date().getTime() + 60_000) { toast.error("Can't move into the past"); return; }
    if (card.social_account?.status && card.social_account.status !== "active") { toast.error(`Account ${card.social_account.display_name} is ${card.social_account.status} — reconnect it first`); return; }
    if (cardTime(card) === iso) return;
    if (mode === "confirm") { setPendingQueued({ card, iso }); return; }
    move.mutate({ card, iso, from: cardTime(card) });
  };

  // Pointer-only drag; keyboard users reschedule from the card sheet and schedule tray items via click/Enter.
  const pointer = useSensor(PointerSensor, { activationConstraint: { distance: 6 } });
  const sensors = useSensors(...(mobile ? [] : [pointer]));
  const scheduleFromTray = (card: CalendarCard) => {
    const base = anchor > today ? anchor : addDays(today, 1);
    const { y, m, d } = parseDayKey(base);
    setTraySchedule({ card, iso: zonedToUtc(y, m, d, 9, 0, tz).toISOString() });
  };
  const onDragStart = (e: DragStartEvent) => { const d = e.active.data.current as { card?: CalendarCard; tray?: CalendarCard } | undefined; setDragging(d?.card ?? d?.tray ?? null); };
  const onDragEnd = (e: DragEndEvent) => {
    setDragging(null);
    const over = e.over?.data.current as { day?: string; hour?: number } | undefined;
    const data = e.active.data.current as { card?: CalendarCard; tray?: CalendarCard } | undefined;
    if (!over?.day || !data) return;
    const { y, m, d } = parseDayKey(over.day);
    if (data.tray) {
      if (!canSchedule) { toast.error("Your role can't schedule posts"); return; }
      if (over.day < today) { toast.error("Can't schedule in the past"); return; }
      setTraySchedule({ card: data.tray, iso: zonedToUtc(y, m, d, over.hour ?? 9, 0, tz).toISOString() });
      return;
    }
    if (data.card) {
      const t = cardTime(data.card);
      const orig = t ? tzParts(new Date(t), tz) : { hour: 9, minute: 0 };
      const minute = Math.round(orig.minute / 15) * 15 % 60;
      const iso = zonedToUtc(y, m, d, over.hour ?? orig.hour, over.hour != null ? minute : orig.minute, tz).toISOString();
      requestMove(data.card, iso);
    }
  };

  const label = view === "day" ? keyLabel(anchor, { weekday: "long", month: "long", day: "numeric", year: "numeric" })
    : view === "week" ? `${keyLabel(range.days[0], { month: "short", day: "numeric" })} – ${keyLabel(range.days[6], { month: "short", day: "numeric", year: "numeric" })}`
    : keyLabel(startOfMonth(anchor), { month: "long", year: "numeric" });
  const filtered = platform !== ALL || status !== ALL || campaign !== ALL || pillar !== ALL;
  const clear = () => { setPlatform(ALL); setStatus(ALL); setCampaign(ALL); setPillar(ALL); };
  const quickCreate = (day: string, hour?: number) => { const { y, m, d } = parseDayKey(day); setQuick({ open: true, local: toLocalInput(zonedToUtc(y, m, d, hour ?? 9, 0, tz), tz) }); };
  const viewProps = { days: range.days, byDay, tz, today, onOpen: setOpenCard, onQuickCreate: canCreate ? quickCreate : undefined, onShowDay: (d: string) => { goTo(d); setView("day"); } };

  return (
    <div>
      <div className="mb-4 flex flex-col gap-3">
        <div className="flex flex-wrap items-center gap-2">
          <h1 className="mr-2 text-2xl font-semibold tracking-tight">Calendar</h1>
          <Button variant="ghost" size="icon-sm" aria-label="Previous" onClick={() => step(-1)}><ChevronLeft /></Button>
          <span className="min-w-[10rem] text-center text-sm font-medium">{label}</span>
          <Button variant="ghost" size="icon-sm" aria-label="Next" onClick={() => step(1)}><ChevronRight /></Button>
          <Button variant="outline" size="sm" onClick={() => goTo(today)}>Today</Button>
          <div className="flex rounded-md border p-0.5 text-xs" role="radiogroup" aria-label="View">
            {VIEWS.map((v) => <button key={v} type="button" role="radio" aria-checked={view === v} onClick={() => setView(v)} className={cn("rounded px-2 py-1 capitalize", view === v && "bg-secondary font-medium")}>{v}</button>)}
          </div>
          <div className="ml-auto flex items-center gap-2">
            <Select value={tz} onValueChange={setTz}><SelectTrigger size="sm" className="w-48" aria-label="Display timezone"><SelectValue /></SelectTrigger>
              <SelectContent>{timezoneOptions([brandTz, tz]).map((z) => <SelectItem key={z} value={z}>{z}{z === brandTz ? " (brand)" : ""}</SelectItem>)}</SelectContent></Select>
            {canCreate && <Button size="sm" onClick={() => quickCreate(anchor < today ? today : anchor)}><Plus /> Quick create</Button>}
          </div>
        </div>
        <div className="flex flex-wrap items-center gap-2">
          <Select value={platform} onValueChange={setPlatform}><SelectTrigger size="sm" className="w-36" aria-label="Platform"><SelectValue /></SelectTrigger>
            <SelectContent><SelectItem value={ALL}>All platforms</SelectItem>{PLATFORMS.map((p) => <SelectItem key={p.id} value={p.id}>{p.label}</SelectItem>)}</SelectContent></Select>
          <Select value={status} onValueChange={setStatus}><SelectTrigger size="sm" className="w-36" aria-label="Status"><SelectValue /></SelectTrigger>
            <SelectContent><SelectItem value={ALL}>All statuses</SelectItem>{STATUS_FILTERS.map((s) => <SelectItem key={s} value={s}>{s.replace(/_/g, " ")}</SelectItem>)}</SelectContent></Select>
          <Select value={campaign} onValueChange={setCampaign}><SelectTrigger size="sm" className="w-36" aria-label="Campaign"><SelectValue /></SelectTrigger>
            <SelectContent><SelectItem value={ALL}>All campaigns</SelectItem>{campaigns.map((c) => <SelectItem key={c.id} value={c.id}>{c.name}</SelectItem>)}</SelectContent></Select>
          <Select value={pillar} onValueChange={setPillar}><SelectTrigger size="sm" className="w-36" aria-label="Pillar"><SelectValue /></SelectTrigger>
            <SelectContent><SelectItem value={ALL}>All pillars</SelectItem>{pillars.map((p) => <SelectItem key={p.id} value={p.id}>{p.name}</SelectItem>)}</SelectContent></Select>
          {filtered && <Button size="sm" variant="ghost" onClick={clear}>Clear filters</Button>}
          {canSchedule && !mobile && <Button size="sm" variant="ghost" className="ml-auto" onClick={() => setTrayOpen((o) => !o)}>{trayOpen ? <PanelLeftClose /> : <PanelLeftOpen />} Unscheduled ({tray.length})</Button>}
        </div>
      </div>

      {warnings.length > 0 && (
        <Alert className="mb-4 border-warning/40"><AlertTriangle className="text-warning" /><AlertTitle>Platform limits</AlertTitle>
          <AlertDescription><ul className="space-y-0.5">{warnings.map((w, i) => <li key={i}>{w.date && <span className="font-medium">{keyLabel(w.date.slice(0, 10), { weekday: "short", day: "numeric" })} · </span>}{w.account && `${w.account}: `}{w.message}{w.source && <span className="text-muted-foreground"> (source: {w.source})</span>}</li>)}</ul></AlertDescription>
        </Alert>
      )}

      {mobile && canSchedule && tray.length > 0 && (
        <details className="mb-3 rounded-lg border p-2">
          <summary className="cursor-pointer text-sm font-medium">Unscheduled approved ({tray.length})</summary>
          <div className="mt-2 space-y-1.5">{tray.map((c) => <button key={c.content_variant_id ?? c.id} type="button" className="block w-full text-left" onClick={() => scheduleFromTray(c)}><CardBody card={c} tz={tz} /></button>)}</div>
        </details>
      )}
      <DndContext sensors={sensors} onDragStart={onDragStart} onDragEnd={onDragEnd} onDragCancel={() => setDragging(null)}>
        <div className={cn("grid gap-4", canSchedule && trayOpen && !mobile && "lg:grid-cols-[220px_minmax(0,1fr)]")}>
          {canSchedule && trayOpen && !mobile && (
            <aside className="hidden space-y-2 lg:block" aria-label="Unscheduled approved posts">
              <p className="flex items-center gap-1 text-xs font-semibold uppercase tracking-wide text-muted-foreground"><Inbox className="h-3.5 w-3.5" /> Unscheduled ✓ ({tray.length})</p>
              <p className="text-[11px] text-muted-foreground">Drag onto a day to schedule</p>
              {trayFallback.isLoading && <Skeleton className="h-12" />}
              {tray.length === 0 && !trayFallback.isLoading && <p className="rounded-md border border-dashed p-3 text-xs text-muted-foreground">No approved posts waiting.</p>}
              <div className="max-h-[65vh] space-y-1.5 overflow-y-auto pr-1">{tray.map((c) => <TrayCard key={c.content_variant_id ?? c.id} card={c} tz={tz} onSchedule={scheduleFromTray} />)}</div>
            </aside>
          )}
          <div className="min-w-0">
            {cal.isLoading ? (
              <div className="grid grid-cols-7 gap-1" aria-busy="true">{Array.from({ length: view === "day" ? 7 : 35 }).map((_, i) => <Skeleton key={i} className="h-24" />)}</div>
            ) : cal.error ? (
              <QueryError error={cal.error} onRetry={() => cal.refetch()} title="Couldn't load the calendar" notAvailableText="The calendar API isn't available on this backend yet." />
            ) : (
              <>
                {cards.length === 0 && (view === "list" || (view === "board" && tray.length === 0)) && (
                  <EmptyState icon={CalendarDays} title={`Nothing planned for ${keyLabel(startOfMonth(anchor), { month: "long" })}.`} description={filtered ? "Try clearing filters." : undefined}
                              action={filtered ? { label: "Clear filters", onClick: clear } : canCreate ? { label: "Open Ideas", onClick: () => router.push(ws("ideas")) } : undefined} />
                )}
                {view === "month" && <MonthView {...viewProps} anchorMonth={parseDayKey(anchor).m} />}
                {(view === "week" || view === "day") && <TimeGridView {...viewProps} />}
                {view === "list" && <ListView {...viewProps} />}
                {view === "board" && (cards.length > 0 || tray.length > 0) && <BoardView cards={[...cards, ...tray]} tz={tz} onOpen={(c) => (c.scheduled_post_id ? setOpenCard(c) : canSchedule ? scheduleFromTray(c) : setOpenCard(c))} />}
                {cards.length === 0 && (view === "month" || view === "week" || view === "day") && <p className="mt-3 text-center text-sm text-muted-foreground">Nothing planned in this range.{canCreate && " Click + on a day to quick-create."}</p>}
              </>
            )}
          </div>
        </div>
        <DragOverlay>{dragging && <div className="w-48 rotate-1 opacity-90"><CardBody card={dragging} tz={tz} /></div>}</DragOverlay>
      </DndContext>

      <CardSheet card={openCard} tz={tz} onOpenChange={(o) => !o && setOpenCard(null)} onMove={requestMove} />
      <ConfirmDialog open={!!pendingQueued} onOpenChange={(o) => !o && setPendingQueued(null)} title="Move a queued post?" confirmLabel="Move it"
                     description={<p>{pendingQueued && `Already queued for ${fmtDateTime(cardTime(pendingQueued.card), tz)} — moving removes it from the queue and reschedules it for ${fmtDateTime(pendingQueued.iso, tz)}.`}</p>}
                     onConfirm={() => { if (pendingQueued) move.mutate({ card: pendingQueued.card, iso: pendingQueued.iso, from: cardTime(pendingQueued.card) }); setPendingQueued(null); }} />
      <Dialog open={!!traySchedule} onOpenChange={(o) => !o && setTraySchedule(null)}>
        <DialogContent className="sm:max-w-lg">
          <DialogHeader><DialogTitle>Schedule “{traySchedule?.card.title}”</DialogTitle><DialogDescription>Confirm the account and time. Best times are available below.</DialogDescription></DialogHeader>
          {traySchedule && traySchedule.card.content_variant_id && traySchedule.card.platform && (
            <ScheduleForm variant={{ id: traySchedule.card.content_variant_id, platform: traySchedule.card.platform, format: traySchedule.card.format ?? undefined, status: "approved", social_account_id: traySchedule.card.social_account_id }}
                          contentApproved brandId={brandId} defaultTz={tz} defaultAt={traySchedule.iso} onDone={() => setTraySchedule(null)} />
          )}
          {traySchedule && !traySchedule.card.content_variant_id && <p className="text-sm text-muted-foreground">This item has no platform version yet — open it in Studio first.</p>}
        </DialogContent>
      </Dialog>
      {quick.open && <QuickCreateDialog open={quick.open} onOpenChange={(o) => setQuick((q) => ({ ...q, open: o }))} brandId={brandId} tz={tz} defaultLocal={quick.local} onCreated={(id) => router.push(ws(`studio/${id}`))} />}
    </div>
  );
}

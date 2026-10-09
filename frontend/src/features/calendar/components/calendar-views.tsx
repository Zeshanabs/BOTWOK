"use client";
import { useDroppable } from "@dnd-kit/core";
import { Plus } from "lucide-react";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { PlatformIcon } from "@/components/data/platform-icon";
import { StatusChip } from "@/components/data/status-chip";
import { dayKey, keyLabel, parseDayKey, timeLabel, tzParts } from "@/features/common/tz";
import { cn } from "@/lib/utils";
import { BOARD_COLUMNS, cardTime, type CalendarCard as Card } from "../api";
import { CalendarCard } from "./calendar-card";

export interface ViewProps {
  days: string[];
  byDay: Map<string, Card[]>;
  tz: string;
  today: string;
  onOpen: (c: Card) => void;
  onQuickCreate?: (day: string, hour?: number) => void;
  onShowDay?: (day: string) => void;
  anchorMonth?: number;
}

const WEEKDAYS = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"];

function DayCell({ day, cards, tz, today, onOpen, onQuickCreate, onShowDay, muted }: { day: string; cards: Card[]; muted?: boolean } & Omit<ViewProps, "days" | "byDay">) {
  const { setNodeRef, isOver } = useDroppable({ id: `day:${day}`, data: { day } });
  const past = day < today;
  const shown = cards.slice(0, 4);
  return (
    <div ref={setNodeRef} className={cn("group flex min-h-[112px] flex-col gap-1 border-b border-r p-1", muted && "bg-muted/30", isOver && "bg-primary/10 ring-2 ring-inset ring-primary", past && "bg-muted/20")}>
      <div className="flex items-center justify-between">
        <button type="button" onClick={() => onShowDay?.(day)} className={cn("rounded px-1 text-xs tabular-nums hover:bg-accent", day === today && "bg-primary font-semibold text-primary-foreground hover:bg-primary/90", muted && "text-muted-foreground")}>{parseDayKey(day).d}</button>
        {onQuickCreate && !past && <button type="button" aria-label={`Quick create on ${day}`} onClick={() => onQuickCreate(day)} className="rounded p-0.5 text-muted-foreground opacity-0 hover:bg-accent group-hover:opacity-100 focus-visible:opacity-100"><Plus className="h-3 w-3" /></button>}
      </div>
      {shown.map((c) => <CalendarCard key={c.scheduled_post_id ?? c.id} card={c} tz={tz} onOpen={onOpen} compact />)}
      {cards.length > shown.length && <button type="button" onClick={() => onShowDay?.(day)} className="text-left text-[11px] text-muted-foreground hover:underline">+{cards.length - shown.length} more</button>}
    </div>
  );
}

export function MonthView(p: ViewProps) {
  return (
    <div className="overflow-x-auto rounded-lg border-l border-t">
      <div className="grid min-w-[720px] grid-cols-7">
        {WEEKDAYS.map((d) => <div key={d} className="border-b border-r bg-muted/40 px-2 py-1 text-xs font-medium text-muted-foreground">{d}</div>)}
        {p.days.map((d) => <DayCell key={d} day={d} cards={p.byDay.get(d) ?? []} tz={p.tz} today={p.today} onOpen={p.onOpen} onQuickCreate={p.onQuickCreate} onShowDay={p.onShowDay} muted={p.anchorMonth != null && parseDayKey(d).m !== p.anchorMonth} />)}
      </div>
    </div>
  );
}

function HourCell({ day, hour, cards, tz, today, onOpen, onQuickCreate }: { day: string; hour: number; cards: Card[] } & Omit<ViewProps, "days" | "byDay">) {
  const { setNodeRef, isOver } = useDroppable({ id: `slot:${day}T${hour}`, data: { day, hour } });
  const past = day < today;
  return (
    <div ref={setNodeRef} className={cn("group relative min-h-12 space-y-1 border-b border-r p-0.5", isOver && "bg-primary/10 ring-2 ring-inset ring-primary", past && "bg-muted/20")}>
      {cards.map((c) => <CalendarCard key={c.scheduled_post_id ?? c.id} card={c} tz={tz} onOpen={onOpen} compact />)}
      {onQuickCreate && !past && cards.length === 0 && <button type="button" aria-label={`Quick create ${day} ${hour}:00`} onClick={() => onQuickCreate(day, hour)} className="absolute inset-0 opacity-0 hover:bg-accent/40 focus-visible:opacity-100" />}
    </div>
  );
}

/** Week (7 columns) or day (1 column) with hour rows; drops snap to the hour (minutes kept, rounded to 15). */
export function TimeGridView(p: ViewProps) {
  const hours = Array.from({ length: 24 }, (_, h) => h);
  const hourOf = (c: Card) => { const t = cardTime(c); return t ? tzParts(new Date(t), p.tz).hour : 9; };
  return (
    <div className="max-h-[70vh] overflow-auto rounded-lg border-l border-t">
      <div className="grid min-w-[640px]" style={{ gridTemplateColumns: `56px repeat(${p.days.length}, minmax(0, 1fr))` }}>
        <div className="sticky top-0 z-10 border-b border-r bg-muted/60" />
        {p.days.map((d) => (
          <button key={d} type="button" onClick={() => p.onShowDay?.(d)} className={cn("sticky top-0 z-10 border-b border-r bg-muted/60 px-2 py-1 text-left text-xs font-medium backdrop-blur", d === p.today && "text-primary")}>
            {keyLabel(d, { weekday: "short", day: "numeric", month: "short" })}
          </button>
        ))}
        {hours.map((h) => (
          <div key={h} className="contents">
            <div className="border-b border-r px-1 py-0.5 text-right text-[10px] tabular-nums text-muted-foreground">{String(h).padStart(2, "0")}:00</div>
            {p.days.map((d) => <HourCell key={d + h} day={d} hour={h} cards={(p.byDay.get(d) ?? []).filter((c) => hourOf(c) === h)} tz={p.tz} today={p.today} onOpen={p.onOpen} onQuickCreate={p.onQuickCreate} />)}
          </div>
        ))}
      </div>
    </div>
  );
}

export function ListView({ days, byDay, tz, onOpen }: ViewProps) {
  const withCards = days.filter((d) => (byDay.get(d) ?? []).length > 0);
  if (!withCards.length) return null;
  return (
    <div className="space-y-4">
      {withCards.map((d) => (
        <section key={d} aria-labelledby={`list-${d}`}>
          <h3 id={`list-${d}`} className="mb-1 text-sm font-semibold">{keyLabel(d, { weekday: "long", month: "short", day: "numeric" })}</h3>
          <div className="hidden rounded-lg border md:block">
            <Table>
              <TableHeader><TableRow><TableHead className="w-20">Time</TableHead><TableHead>Post</TableHead><TableHead>Account</TableHead><TableHead>Status</TableHead></TableRow></TableHeader>
              <TableBody>
                {(byDay.get(d) ?? []).map((c) => (
                  <TableRow key={c.scheduled_post_id ?? c.id} className="cursor-pointer" onClick={() => onOpen(c)}>
                    <TableCell className="tabular-nums">{cardTime(c) ? timeLabel(cardTime(c) as string, tz) : "—"}</TableCell>
                    <TableCell><span className="flex items-center gap-1.5">{c.platform && <PlatformIcon platform={c.platform} size={16} />}<span className="truncate">{c.title}</span></span></TableCell>
                    <TableCell className="text-sm text-muted-foreground">{c.social_account?.display_name ?? "—"}</TableCell>
                    <TableCell><StatusChip status={c.status} /></TableCell>
                  </TableRow>
                ))}
              </TableBody>
            </Table>
          </div>
          <ul className="space-y-1.5 md:hidden">{(byDay.get(d) ?? []).map((c) => <li key={c.scheduled_post_id ?? c.id}><CalendarCard card={c} tz={tz} onOpen={onOpen} /></li>)}</ul>
        </section>
      ))}
    </div>
  );
}

export function BoardView({ cards, tz, onOpen }: { cards: Card[]; tz: string; onOpen: (c: Card) => void }) {
  return (
    <div className="flex gap-3 overflow-x-auto pb-2">
      {BOARD_COLUMNS.map((s) => {
        const col = cards.filter((c) => (c.status === "queued" || c.status === "paused" ? "scheduled" : c.status) === s);
        return (
          <section key={s} className="w-56 shrink-0 rounded-lg bg-muted/40 p-2" aria-label={s}>
            <div className="mb-2 flex items-center justify-between"><StatusChip status={s} /><span className="text-xs text-muted-foreground">{col.length}</span></div>
            <div className="space-y-1.5">
              {col.map((c) => (
                <div key={c.scheduled_post_id ?? c.id}>
                  {cardTime(c) && <p className="mb-0.5 text-[10px] text-muted-foreground">{keyLabel(dayKey(new Date(cardTime(c) as string), tz), { month: "short", day: "numeric" })}</p>}
                  <CalendarCard card={c} tz={tz} onOpen={onOpen} />
                </div>
              ))}
              {col.length === 0 && <p className="py-4 text-center text-xs text-muted-foreground">Empty</p>}
            </div>
          </section>
        );
      })}
    </div>
  );
}

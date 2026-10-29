"use client";
/** Kanban by status; dragging a card to another column updates it (Promoted → creates a Studio draft). */
import { DndContext, KeyboardSensor, PointerSensor, useDraggable, useDroppable, useSensor, useSensors, type DragEndEvent } from "@dnd-kit/core";
import { GripVertical } from "lucide-react";
import { cn } from "@/lib/utils";
import { useCan } from "@/lib/permissions";
import { IDEA_STATUSES, type Idea } from "../types";
import { IdeaCard, type IdeaActions } from "./idea-card";

const LABELS: Record<string, string> = { new: "New", shortlisted: "Shortlisted", promoted: "Promoted", discarded: "Discarded" };

function DraggableIdea({ idea, pillarName, actions, disabled }: { idea: Idea; pillarName?: string; actions: IdeaActions; disabled: boolean }) {
  const { attributes, listeners, setNodeRef, transform, isDragging } = useDraggable({ id: idea.id, disabled });
  const style = transform ? { transform: `translate3d(${transform.x}px, ${transform.y}px, 0)` } : undefined;
  return (
    <div ref={setNodeRef} style={style} className={cn(isDragging && "relative z-10 opacity-80 shadow-lg")}>
      <IdeaCard idea={idea} pillarName={pillarName} actions={actions}
                dragHandle={!disabled ? (
                  <button type="button" className="mt-0.5 cursor-grab touch-none text-muted-foreground hover:text-foreground" aria-label={`Drag ${idea.title}`} {...attributes} {...listeners}>
                    <GripVertical className="h-4 w-4" />
                  </button>
                ) : undefined} />
    </div>
  );
}

function Column({ status, children, count }: { status: string; children: React.ReactNode; count: number }) {
  const { setNodeRef, isOver } = useDroppable({ id: status });
  return (
    <section ref={setNodeRef} aria-label={`${LABELS[status]} ideas`} className={cn("flex min-h-40 w-72 shrink-0 flex-col gap-2 rounded-xl bg-muted/40 p-2 md:w-auto", isOver && "ring-2 ring-primary/50")}>
      <h3 className="px-1 text-xs font-semibold uppercase tracking-wide text-muted-foreground">{LABELS[status]} ({count})</h3>
      {children}
    </section>
  );
}

export function IdeasBoard({ ideas, pillarNames, actions }: { ideas: Idea[]; pillarNames: Record<string, string>; actions: IdeaActions }) {
  const can = useCan();
  const sensors = useSensors(useSensor(PointerSensor, { activationConstraint: { distance: 5 } }), useSensor(KeyboardSensor));
  function onDragEnd(e: DragEndEvent) {
    const to = e.over?.id ? String(e.over.id) : null;
    const idea = ideas.find((i) => i.id === e.active.id);
    if (!to || !idea || idea.status === to) return;
    if (to === "promoted") actions.onPromote(idea);
    else actions.onStatus(idea, to);
  }
  return (
    <DndContext sensors={sensors} onDragEnd={onDragEnd}>
      <div className="-mx-4 flex gap-3 overflow-x-auto px-4 pb-2 md:mx-0 md:grid md:grid-cols-4 md:px-0">
        {IDEA_STATUSES.map((status) => {
          const col = ideas.filter((i) => (i.status || "new") === status);
          return (
            <Column key={status} status={status} count={col.length}>
              {col.map((i) => <DraggableIdea key={i.id} idea={i} pillarName={i.pillar_id ? pillarNames[i.pillar_id] : undefined} actions={actions} disabled={!can.create || status === "promoted"} />)}
              {!col.length && <p className="p-3 text-center text-xs text-muted-foreground">Drop ideas here</p>}
            </Column>
          );
        })}
      </div>
    </DndContext>
  );
}

"use client";
import { Handle, Position, type Node, type NodeProps } from "@xyflow/react";
import { ArrowLeftRight, BarChart3, Bell, CalendarClock, CheckSquare, Cog, Diamond, Hourglass, Search, Send, Sparkles, SquarePen, Webhook, Zap, type LucideIcon } from "lucide-react";
import { TaskGlyph } from "@/features/common/components/run-card";
import { cn } from "@/lib/utils";

export interface WFData extends Record<string, unknown> {
  type: string;
  label: string;
  config: Record<string, unknown>;
  typeLabel: string;
  sideEffect?: string;
  branches?: string[];
  invalid?: boolean;
  runStatus?: string | null;
  dryRun?: boolean;
}
export type WFNode = Node<WFData, "workflow">;

export const NODE_ICONS: Record<string, LucideIcon> = {
  trigger: Zap, condition: Diamond, ai_agent: Sparkles, research: Search, generate: SquarePen, transform: ArrowLeftRight, approve: CheckSquare,
  schedule: CalendarClock, publish: Send, wait: Hourglass, webhook: Webhook, notification: Bell, analytics: BarChart3, action: Cog,
};
const SE_STYLE: Record<string, string> = {
  EXTERNAL_WRITE: "border-destructive/40 text-destructive  ",
  SPEND: "border-ai/40 text-ai  ",
  APPROVAL: "border-warning/40 text-warning  ",
  EXTERNAL_READ: "border-info/40 text-info  ",
};
const RUN_RING: Record<string, string> = { succeeded: "ring-2 ring-emerald-500", failed: "ring-2 ring-destructive/40", running: "ring-2 ring-blue-500", awaiting_approval: "ring-2 ring-amber-500", waiting: "ring-2 ring-amber-500" };

/** Canvas node: icon, label, type, side-effect class, branch handles, validation outline and run-status overlay. */
export function WorkflowNodeView({ data, selected }: NodeProps<WFNode>) {
  const Icon = NODE_ICONS[data.type] ?? Cog;
  const isTrigger = data.type === "trigger" || data.type.startsWith("trigger.");
  const branches = data.branches ?? [];
  return (
    <div className={cn("w-60 rounded-lg border bg-card px-3 py-2 text-xs text-card-foreground shadow-sm", selected && "ring-2 ring-primary", data.invalid && "border-destructive/40 border-2", data.runStatus && RUN_RING[data.runStatus])}>
      {!isTrigger && <Handle type="target" position={Position.Top} className="!h-2.5 !w-2.5 !bg-muted-foreground" />}
      <div className="flex items-center gap-2">
        <Icon className={cn("h-4 w-4 shrink-0", data.type === "ai_agent" || data.type === "generate" ? "text-ai" : "text-muted-foreground")} aria-hidden />
        <span className="min-w-0 flex-1 truncate font-medium">{data.label || data.typeLabel}</span>
        {data.runStatus && <TaskGlyph status={data.runStatus} />}
        {data.invalid && <span className="text-destructive" aria-label="invalid">⚠</span>}
      </div>
      <div className="mt-1 flex items-center gap-1 text-[10px] text-muted-foreground">
        <span>{data.typeLabel}</span>
        {data.sideEffect && data.sideEffect !== "READ" && <span className={cn("rounded border px-1 uppercase", SE_STYLE[data.sideEffect] ?? "")}>{data.sideEffect.replace(/_/g, " ").toLowerCase()}</span>}
        {data.dryRun && data.sideEffect === "EXTERNAL_WRITE" && <span className="rounded bg-muted px-1">dry run</span>}
      </div>
      {branches.length > 0 ? (
        <>
          <div className="mt-1 flex justify-around text-[10px] text-muted-foreground">{branches.map((b) => <span key={b}>{b}</span>)}</div>
          {branches.map((b, i) => <Handle key={b} type="source" id={b} position={Position.Bottom} style={{ left: `${((i + 1) * 100) / (branches.length + 1)}%` }} className="!h-2.5 !w-2.5 !bg-primary" />)}
        </>
      ) : <Handle type="source" position={Position.Bottom} className="!h-2.5 !w-2.5 !bg-primary" />}
    </div>
  );
}

export const NODE_TYPES = { workflow: WorkflowNodeView };

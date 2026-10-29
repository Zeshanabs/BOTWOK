import type { LucideIcon } from "lucide-react";
import { Button } from "@/components/ui/button";
import { cn } from "@/lib/utils";

/** Empty state: icon, one sentence, one primary CTA (doc 23 §23.4). */
export function EmptyState({ icon: Icon, title, description, action, secondary, className, children }: {
  icon: LucideIcon; title: string; description?: string;
  action?: { label: string; onClick: () => void; icon?: LucideIcon };
  secondary?: { label: string; onClick: () => void };
  className?: string; children?: React.ReactNode;
}) {
  const ActionIcon = action?.icon;
  return (
    <div className={cn("flex flex-col items-center justify-center rounded-xl border border-dashed bg-dotgrid px-6 py-12 text-center", className)}>
      <div className="mb-4 flex h-12 w-12 items-center justify-center rounded-2xl bg-primary/10 text-primary ring-8 ring-primary/[0.04]">
        <Icon className="h-5 w-5" strokeWidth={1.75} aria-hidden />
      </div>
      <h3 className="font-display text-base font-semibold tracking-tight">{title}</h3>
      {description && <p className="mt-1 max-w-sm text-sm leading-relaxed text-muted-foreground">{description}</p>}
      {(action || secondary) && (
        <div className="mt-5 flex flex-wrap items-center justify-center gap-2">
          {action && <Button size="sm" onClick={action.onClick}>{ActionIcon && <ActionIcon />}{action.label}</Button>}
          {secondary && <Button size="sm" variant="ghost" onClick={secondary.onClick}>{secondary.label}</Button>}
        </div>
      )}
      {children}
    </div>
  );
}

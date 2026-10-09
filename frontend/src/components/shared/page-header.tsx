import { cn } from "@/lib/utils";

/**
 * Page header: display title, one-line description, right-aligned actions; optional toolbar/tabs below.
 * Owns the bottom spacing so pages can start directly with content.
 */
export function PageHeader({ title, description, actions, eyebrow, children, className }: {
  title: React.ReactNode; description?: React.ReactNode; actions?: React.ReactNode; eyebrow?: React.ReactNode; children?: React.ReactNode; className?: string;
}) {
  return (
    <header className={cn("mb-6", className)}>
      <div className="flex flex-col gap-3 sm:flex-row sm:items-start sm:justify-between">
        <div className="min-w-0">
          {eyebrow && <p className="mb-1 text-[11px] font-semibold uppercase tracking-[0.12em] text-muted-foreground">{eyebrow}</p>}
          <h1 className="font-display text-2xl font-bold leading-tight tracking-tight text-foreground sm:text-[26px]">{title}</h1>
          {description && <p className="mt-1 max-w-2xl text-sm leading-relaxed text-muted-foreground">{description}</p>}
        </div>
        {actions ? <div className="flex shrink-0 flex-wrap items-center gap-2 sm:justify-end">{actions}</div> : null}
      </div>
      {children && <div className="mt-4">{children}</div>}
    </header>
  );
}

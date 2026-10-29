import { cn } from "@/lib/utils";

/** Botwok mark: a wok with a spark above it ("where content gets cooked"). Inherits `currentColor`. */
export function LogoMark({ className, ...props }: React.SVGProps<SVGSVGElement>) {
  return (
    <svg viewBox="0 0 24 24" fill="none" aria-hidden className={cn("h-5 w-5", className)} {...props}>
      <path d="M3.5 10.5h17c0 4.7-3.8 8.5-8.5 8.5s-8.5-3.8-8.5-8.5Z" fill="currentColor" />
      <path d="M2 10.5h20" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round" />
      <path d="M12 2.2l1 2.3 2.3 1-2.3 1-1 2.3-1-2.3-2.3-1 2.3-1 1-2.3Z" fill="currentColor" />
    </svg>
  );
}

/** Mark on a primary tile, with the wordmark beside it. */
export function Logo({ size = "md", wordmark = true, className }: { size?: "sm" | "md" | "lg"; wordmark?: boolean; className?: string }) {
  const tile = size === "lg" ? "h-10 w-10 rounded-xl" : size === "sm" ? "h-7 w-7 rounded-lg" : "h-8 w-8 rounded-lg";
  const mark = size === "lg" ? "h-6 w-6" : size === "sm" ? "h-4 w-4" : "h-[18px] w-[18px]";
  const text = size === "lg" ? "text-2xl" : "text-[17px]";
  return (
    <span className={cn("inline-flex items-center gap-2.5", className)}>
      <span className={cn("inline-flex shrink-0 items-center justify-center bg-primary text-primary-foreground shadow-card", tile)}>
        <LogoMark className={mark} />
      </span>
      {wordmark && <span className={cn("font-display font-bold tracking-tight", text)}>Botwok</span>}
    </span>
  );
}

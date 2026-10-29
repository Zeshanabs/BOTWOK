import { Globe, Store } from "lucide-react";
import { platformMeta } from "@/lib/platforms";
import { cn } from "@/lib/utils";

/** Brand-coloured glyph tiles. Platform brand colour is the only place a non-semantic colour appears (doc 23 §23.3). */
const GLYPHS: Record<string, React.ReactNode> = {
  facebook: <path d="M13.6 21v-7.2h2.5l.4-2.9h-2.9V9.1c0-.8.3-1.4 1.5-1.4h1.5V5.1c-.3 0-1.2-.1-2.2-.1-2.2 0-3.7 1.3-3.7 3.8v2.1H8.2v2.9h2.5V21h2.9Z" fill="currentColor" />,
  instagram: (
    <>
      <rect x="4" y="4" width="16" height="16" rx="4.5" stroke="currentColor" strokeWidth="1.9" fill="none" />
      <circle cx="12" cy="12" r="3.6" stroke="currentColor" strokeWidth="1.9" fill="none" />
      <circle cx="16.6" cy="7.4" r="1.1" fill="currentColor" />
    </>
  ),
  threads: <path d="M12.3 21c-2.4 0-4.3-.8-5.6-2.3-1.2-1.4-1.8-3.3-1.8-5.7 0-2.5.6-4.4 1.8-5.8C8 5.8 9.9 5 12.3 5c1.9 0 3.5.5 4.7 1.5l-1.2 1.5c-.9-.8-2.1-1.2-3.5-1.2-1.8 0-3.1.6-4 1.7-.9 1-1.3 2.5-1.3 4.5s.4 3.5 1.3 4.5c.9 1.1 2.2 1.7 4 1.7 1.3 0 2.3-.3 3.1-.9.8-.6 1.1-1.3 1.1-2.1 0-.7-.3-1.3-.9-1.7-.5-.4-1.3-.6-2.2-.7-.1 1.1-.4 2-1 2.7-.6.6-1.4 1-2.3 1-.9 0-1.6-.3-2.2-.8-.6-.5-.9-1.2-.9-2 0-1 .4-1.8 1.3-2.4.8-.6 2-.9 3.5-.9h.5c-.1-.6-.3-1.1-.6-1.4-.3-.3-.8-.5-1.4-.5-.9 0-1.6.3-2.2 1l-1.4-1c.9-1.1 2.2-1.7 3.7-1.7 1.3 0 2.2.4 2.9 1.1.6.7 1 1.6 1.1 2.8 1.4.2 2.5.7 3.2 1.4.8.8 1.2 1.7 1.2 2.9 0 1.5-.6 2.7-1.8 3.6-1.1.9-2.7 1.4-4.5 1.4Zm-.3-7.9c-1 0-1.7.2-2.2.5-.4.3-.6.6-.6 1 0 .3.1.6.4.8.3.2.6.3 1 .3.6 0 1-.2 1.4-.6.3-.4.5-1 .6-1.9h-.6Z" fill="currentColor" />,
  linkedin: <path d="M6.9 9.5h2.7V19H6.9V9.5Zm1.4-4.3a1.6 1.6 0 1 1 0 3.2 1.6 1.6 0 0 1 0-3.2ZM11.3 9.5h2.6v1.3c.4-.7 1.3-1.5 2.8-1.5 2.9 0 3.5 1.9 3.5 4.4V19h-2.7v-4.7c0-1.1 0-2.6-1.6-2.6s-1.8 1.2-1.8 2.5V19h-2.7V9.5Z" fill="currentColor" />,
  x: <path d="M17.2 4h2.9l-6.4 7.3L21.2 21h-5.9l-4.6-6-5.3 6H2.5l6.9-7.8L2.2 4h6l4.2 5.5L17.2 4Zm-1 15.3h1.6L7.6 5.6H5.9l10.3 13.7Z" fill="currentColor" />,
  tiktok: <path d="M13.9 3h3c.2 1.7 1.3 3.2 3.1 3.6v3c-1.3 0-2.5-.4-3.6-1.1v6.3c0 3.1-2.5 5.6-5.6 5.6S5.2 17.9 5.2 14.8s2.5-5.6 5.6-5.6c.3 0 .6 0 .9.1v3.1a2.6 2.6 0 0 0-.9-.2 2.6 2.6 0 1 0 2.6 2.6V3h.5Z" fill="currentColor" />,
  youtube: (
    <>
      <rect x="3" y="6" width="18" height="12" rx="3.5" fill="currentColor" />
      <path d="M10.2 9.3v5.4l4.6-2.7-4.6-2.7Z" fill="var(--pi-bg, #fff)" />
    </>
  ),
  pinterest: <path d="M12.2 3C7.3 3 4.5 6.5 4.5 9.9c0 1.7.6 3.2 2 3.7.2.1.4 0 .5-.2l.2-.8c.1-.3 0-.4-.1-.6-.4-.5-.7-1.2-.7-2.1 0-2.7 2-5.1 5.3-5.1 2.9 0 4.5 1.8 4.5 4.1 0 3.1-1.4 5.7-3.4 5.7-1.1 0-2-.9-1.7-2.1.3-1.4 1-2.9 1-3.9 0-.9-.5-1.6-1.5-1.6-1.2 0-2.1 1.2-2.1 2.8 0 1 .3 1.7.3 1.7l-1.4 5.9c-.4 1.7-.1 3.9 0 4.1 0 .1.2.2.3.1.1-.2 1.6-2 2.1-3.8l.8-3.1c.4.8 1.5 1.4 2.8 1.4 3.6 0 6.1-3.3 6.1-7.7C19.6 6.2 16.6 3 12.2 3Z" fill="currentColor" />,
};

export function PlatformIcon({ platform, size = 16, className, title }: { platform: string; size?: number; className?: string; title?: string }) {
  const meta = platformMeta(platform || "web");
  const isWeb = !platform || platform === "web" || !GLYPHS[platform] && platform !== "gbp";
  const monochrome = meta.color.toLowerCase() === "#000000";
  const label = title ?? (isWeb ? "Web" : meta.label);
  const style = monochrome || isWeb ? undefined : { background: meta.color, color: "#fff", ["--pi-bg" as string]: meta.color };
  const glyphSize = Math.round(size * 0.78);
  return (
    <span
      role="img"
      aria-label={label}
      title={label}
      className={cn(
        "inline-flex shrink-0 items-center justify-center overflow-hidden rounded-[28%] align-middle leading-none select-none",
        isWeb && "bg-muted text-muted-foreground",
        monochrome && "bg-foreground text-background [--pi-bg:var(--background)]",
        className,
      )}
      style={{ width: size, height: size, ...style }}
    >
      {isWeb ? <Globe style={{ width: glyphSize, height: glyphSize }} strokeWidth={2} aria-hidden />
        : platform === "gbp" ? <Store style={{ width: glyphSize, height: glyphSize }} strokeWidth={2.2} aria-hidden />
        : <svg viewBox="0 0 24 24" width={size} height={size} aria-hidden>{GLYPHS[platform]}</svg>}
    </span>
  );
}

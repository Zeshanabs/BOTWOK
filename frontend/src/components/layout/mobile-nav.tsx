"use client";
import { useEffect, useState } from "react";
import Link from "next/link";
import { usePathname } from "next/navigation";
import { CalendarDays, CheckSquare, LayoutDashboard, Menu, Sparkles } from "lucide-react";
import { Logo } from "@/components/brand/logo";
import { Sheet, SheetContent, SheetDescription, SheetHeader, SheetTitle } from "@/components/ui/sheet";
import { cn } from "@/lib/utils";
import { useSession } from "@/stores/session";
import { NAV, SETTINGS_NAV } from "./nav";
import { NavLink, useApprovalsBadge, WorkspaceSwitcher } from "./sidebar";
import { ThemeToggle } from "./theme-toggle";

/** Bottom tab bar (doc 23 §23.2) plus the full navigation drawer opened by "Menu" or the header's hamburger. */
export function MobileNav() {
  const slug = useSession((s) => s.workspaceSlug) ?? "w";
  const pathname = usePathname();
  const [open, setOpen] = useState(false);
  const pending = useApprovalsBadge();
  useEffect(() => {
    const onOpen = () => setOpen(true);
    document.addEventListener("botwok:mobile-nav", onOpen);
    return () => document.removeEventListener("botwok:mobile-nav", onOpen);
  }, []);
  const items = [
    { href: "dashboard", label: "Home", icon: LayoutDashboard },
    { href: "studio", label: "Studio", icon: Sparkles },
    { href: "calendar", label: "Calendar", icon: CalendarDays },
    { href: "approvals", label: "Approvals", icon: CheckSquare, badge: pending },
  ];
  return (
    <>
      <nav className="fixed inset-x-0 bottom-0 z-40 flex border-t bg-background/95 pb-[env(safe-area-inset-bottom)] backdrop-blur md:hidden" aria-label="Primary (mobile)">
        {items.map((it) => {
          const Icon = it.icon;
          const active = pathname?.includes(`/w/${slug}/${it.href}`);
          return (
            <Link key={it.href} href={`/w/${slug}/${it.href}`} aria-current={active ? "page" : undefined}
                  className={cn("relative flex flex-1 flex-col items-center gap-0.5 py-2 text-[11px] font-medium", active ? "text-primary" : "text-muted-foreground")}>
              <span className={cn("flex h-6 w-10 items-center justify-center rounded-full transition-colors", active && "bg-primary/10")}><Icon className="h-[18px] w-[18px]" /></span>
              {it.label}
              {it.badge ? <span className="absolute right-[calc(50%-20px)] top-1 flex h-4 min-w-4 items-center justify-center rounded-full bg-warning px-1 text-[9.5px] font-semibold text-warning-foreground">{it.badge}</span> : null}
            </Link>
          );
        })}
        <button type="button" onClick={() => setOpen(true)} className="flex flex-1 flex-col items-center gap-0.5 py-2 text-[11px] font-medium text-muted-foreground" aria-label="Open menu">
          <span className="flex h-6 w-10 items-center justify-center"><Menu className="h-[18px] w-[18px]" /></span>Menu
        </button>
      </nav>
      <Sheet open={open} onOpenChange={setOpen}>
        <SheetContent side="left" className="w-[300px] bg-sidebar p-0 sm:max-w-[300px]">
          <SheetHeader className="border-b border-sidebar-border px-4 py-3 text-left">
            <SheetTitle className="flex items-center pr-8"><Logo /></SheetTitle>
            <SheetDescription className="sr-only">Navigation</SheetDescription>
          </SheetHeader>
          <div className="px-2 pt-2"><WorkspaceSwitcher /></div>
          <nav className="flex-1 space-y-4 overflow-y-auto px-2 py-2" aria-label="Primary">
            {NAV.map((g, gi) => (
              <div key={gi} className="space-y-0.5">
                {g.group && <p className="px-2.5 pb-1.5 pt-1 text-[10.5px] font-semibold uppercase tracking-[0.12em] text-muted-foreground/80">{g.group}</p>}
                {g.items.map((it) => <NavLink key={it.href} item={it} slug={slug} badge={it.href === "approvals" ? pending : undefined} onNavigate={() => setOpen(false)} />)}
              </div>
            ))}
            <div className="flex items-center gap-1 border-t border-sidebar-border pt-2"><div className="flex-1"><NavLink item={SETTINGS_NAV} slug={slug} onNavigate={() => setOpen(false)} /></div><ThemeToggle align="end" /></div>
          </nav>
        </SheetContent>
      </Sheet>
    </>
  );
}

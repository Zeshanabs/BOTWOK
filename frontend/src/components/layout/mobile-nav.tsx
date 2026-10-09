"use client";
import Link from "next/link";
import { usePathname } from "next/navigation";
import { CalendarDays, CheckSquare, LayoutDashboard, MoreHorizontal, Sparkles } from "lucide-react";
import { cn } from "@/lib/utils";
import { useSession } from "@/stores/session";

export function MobileNav() {
  const slug = useSession((s) => s.workspaceSlug) ?? "w";
  const pathname = usePathname();
  const items = [
    { href: "dashboard", label: "Home", icon: LayoutDashboard }, { href: "studio", label: "Studio", icon: Sparkles },
    { href: "calendar", label: "Calendar", icon: CalendarDays }, { href: "approvals", label: "Approvals", icon: CheckSquare },
    { href: "settings/brand", label: "More", icon: MoreHorizontal },
  ];
  return (
    <nav className="fixed inset-x-0 bottom-0 z-40 flex border-t bg-background md:hidden">
      {items.map((it) => { const Icon = it.icon; const active = pathname?.includes(`/w/${slug}/${it.href.split("/")[0]}`);
        return <Link key={it.href} href={`/w/${slug}/${it.href}`} className={cn("flex flex-1 flex-col items-center gap-0.5 py-2 text-[11px]", active ? "text-primary" : "text-muted-foreground")}><Icon className="h-5 w-5" />{it.label}</Link>; })}
    </nav>
  );
}

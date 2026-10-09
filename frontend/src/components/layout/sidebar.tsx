"use client";
import Link from "next/link";
import { usePathname } from "next/navigation";
import { BarChart3, Bot, CalendarDays, CheckSquare, FileText, Image as ImageIcon, LayoutDashboard, Lightbulb, Radar, Search, Send, Settings, Sparkles, TrendingUp, Users, Workflow } from "lucide-react";
import type { LucideIcon } from "lucide-react";
import { cn } from "@/lib/utils";
import { useUI } from "@/stores/ui";
import { useSession } from "@/stores/session";

type NavItem = { href: string; label: string; icon: LucideIcon; ai?: boolean; match?: string };
const NAV: { group: string; items: NavItem[] }[] = [
  { group: "", items: [
    { href: "dashboard", label: "Dashboard", icon: LayoutDashboard },
    { href: "command-center", label: "Command Center", icon: Bot, ai: true },
  ]},
  { group: "Intelligence", items: [
    { href: "research", label: "Research", icon: Search },
    { href: "competitors", label: "Competitors", icon: Users },
    { href: "trends", label: "Trends", icon: TrendingUp },
    { href: "ideas", label: "Ideas", icon: Lightbulb },
  ]},
  { group: "Content", items: [
    { href: "studio", label: "Studio", icon: Sparkles },
    { href: "media", label: "Media Library", icon: ImageIcon },
    { href: "calendar", label: "Calendar", icon: CalendarDays },
    { href: "approvals", label: "Approvals", icon: CheckSquare },
    { href: "publishing", label: "Publishing", icon: Send },
  ]},
  { group: "Insight", items: [
    { href: "analytics", label: "Analytics", icon: BarChart3 },
    { href: "reports", label: "Reports", icon: FileText },
    { href: "automations", label: "Automations", icon: Workflow },
  ]},
  { group: "", items: [
    { href: "settings/brand", label: "Settings", icon: Settings, match: "settings" },
  ]},
];

export function Sidebar() {
  const pathname = usePathname();
  const collapsed = useUI((s) => s.sidebarCollapsed);
  const slug = useSession((s) => s.workspaceSlug) ?? "w";
  return (
    <aside className={cn("hidden h-screen shrink-0 flex-col border-r bg-sidebar text-sidebar-foreground md:flex", collapsed ? "w-16" : "w-60")}>
      <div className="flex h-14 items-center gap-2 border-b px-4">
        <Radar className="h-5 w-5 text-primary" />
        {!collapsed && <span className="font-semibold">Botwok</span>}
      </div>
      <nav className="flex-1 overflow-y-auto px-2 py-3">
        {NAV.map((g, gi) => (
          <div key={gi} className="mb-3">
            {g.group && !collapsed && <p className="px-2 pb-1 text-[11px] font-medium uppercase tracking-wide text-muted-foreground">{g.group}</p>}
            {g.items.map((it) => {
              const href = `/w/${slug}/${it.href}`;
              const active = pathname?.includes(`/w/${slug}/${it.match ?? it.href}`);
              const Icon = it.icon;
              return (
                <Link key={it.href} href={href} title={it.label}
                      className={cn("mb-0.5 flex items-center gap-2 rounded-md px-2 py-1.5 text-sm transition-colors",
                        active ? "bg-sidebar-accent font-medium text-sidebar-accent-foreground" : "text-muted-foreground hover:bg-sidebar-accent hover:text-sidebar-accent-foreground",
                        collapsed && "justify-center")}>
                  <Icon className={cn("h-4 w-4 shrink-0", it.ai && "text-ai")} />
                  {!collapsed && <span className="truncate">{it.label}</span>}
                </Link>
              );
            })}
          </div>
        ))}
      </nav>
    </aside>
  );
}

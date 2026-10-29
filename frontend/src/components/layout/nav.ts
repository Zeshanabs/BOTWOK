import { BarChart3, Bot, CalendarDays, CheckSquare, FileText, Image as ImageIcon, LayoutDashboard, Lightbulb, Search, Settings, Sparkles, TrendingUp, Users, Workflow, Send } from "lucide-react";
import type { LucideIcon } from "lucide-react";

export type NavItem = { href: string; label: string; icon: LucideIcon; ai?: boolean; match?: string; hint?: string };
export type NavGroup = { group: string; items: NavItem[] };

/** Primary navigation shared by the sidebar, the mobile drawer and the ⌘K palette. */
export const NAV: NavGroup[] = [
  { group: "", items: [
    { href: "dashboard", label: "Dashboard", icon: LayoutDashboard, hint: "What needs action today" },
    { href: "command-center", label: "Command Center", icon: Bot, ai: true, hint: "Run and watch AI agents" },
  ]},
  { group: "Intelligence", items: [
    { href: "research", label: "Research", icon: Search, hint: "Sources with citations" },
    { href: "competitors", label: "Competitors", icon: Users, hint: "Profiles, posts, gaps" },
    { href: "trends", label: "Trends", icon: TrendingUp, hint: "What is rising" },
    { href: "ideas", label: "Ideas", icon: Lightbulb, hint: "Backlog of angles" },
  ]},
  { group: "Content", items: [
    { href: "studio", label: "Studio", icon: Sparkles, hint: "Write, critique, repurpose" },
    { href: "media", label: "Media Library", icon: ImageIcon, hint: "Assets and renditions" },
    { href: "calendar", label: "Calendar", icon: CalendarDays, hint: "Plan the week" },
    { href: "approvals", label: "Approvals", icon: CheckSquare, hint: "Review before it ships" },
    { href: "publishing", label: "Publishing", icon: Send, hint: "Queue and delivery" },
  ]},
  { group: "Insight", items: [
    { href: "analytics", label: "Analytics", icon: BarChart3, hint: "Normalized metrics" },
    { href: "reports", label: "Reports", icon: FileText, hint: "Weekly packs" },
    { href: "automations", label: "Automations", icon: Workflow, hint: "No-code workflows" },
  ]},
];

export const SETTINGS_NAV: NavItem = { href: "settings/brand", label: "Settings", icon: Settings, match: "settings" };

/** Human title for the current route, used by the header breadcrumb. */
export function titleForPath(pathname: string | null, slug: string | null | undefined): string | null {
  if (!pathname) return null;
  const after = pathname.split(`/w/${slug ?? ""}/`)[1] ?? "";
  const head = after.split("/")[0]?.split("?")[0];
  if (!head) return null;
  if (head === "settings") {
    const sub = after.split("/")[1]?.split("?")[0] ?? "";
    const map: Record<string, string> = { brand: "Brand", social: "Social accounts", "social-accounts": "Social accounts", ai: "AI", team: "Team", system: "System" };
    return map[sub] ? `Settings · ${map[sub]}` : "Settings";
  }
  for (const g of NAV) for (const it of g.items) if (it.href === head) return it.label;
  return head.replace(/-/g, " ").replace(/\b\w/g, (c) => c.toUpperCase());
}

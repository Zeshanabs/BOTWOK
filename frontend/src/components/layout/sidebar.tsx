"use client";
import Link from "next/link";
import { usePathname, useRouter } from "next/navigation";
import { useQuery } from "@tanstack/react-query";
import { Check, ChevronsLeft, ChevronsRight, ChevronsUpDown, Plus } from "lucide-react";
import { Logo, LogoMark } from "@/components/brand/logo";
import { DropdownMenu, DropdownMenuContent, DropdownMenuItem, DropdownMenuLabel, DropdownMenuSeparator, DropdownMenuTrigger } from "@/components/ui/dropdown-menu";
import { approvalsApi } from "@/features/approvals/api";
import { toItems } from "@/features/common/utils";
import { cn } from "@/lib/utils";
import { useSession } from "@/stores/session";
import { useUI } from "@/stores/ui";
import { NAV, SETTINGS_NAV, type NavItem } from "./nav";

function initials(name: string | undefined | null): string {
  return (name ?? "W").split(/\s+/).map((w) => w[0]).filter(Boolean).slice(0, 2).join("").toUpperCase();
}

/** Workspace identity + switcher at the top of the sidebar. */
export function WorkspaceSwitcher({ collapsed }: { collapsed?: boolean }) {
  const router = useRouter();
  const { memberships, workspaceSlug, setWorkspace } = useSession();
  const current = memberships.find((m) => m.workspace.slug === workspaceSlug) ?? memberships[0];
  return (
    <DropdownMenu>
      <DropdownMenuTrigger asChild>
        <button
          type="button"
          aria-label="Switch workspace"
          className={cn(
            "group flex w-full items-center gap-2.5 rounded-lg px-2 py-1.5 text-left text-sm transition-colors hover:bg-sidebar-accent focus-visible:outline-none focus-visible:ring-[3px] focus-visible:ring-ring/50",
            collapsed && "justify-center px-0",
          )}
        >
          <span className="flex h-7 w-7 shrink-0 items-center justify-center rounded-md bg-primary/12 text-[11px] font-bold text-primary">{initials(current?.workspace.name)}</span>
          {!collapsed && (
            <>
              <span className="min-w-0 flex-1">
                <span className="block truncate font-medium leading-tight">{current?.workspace.name ?? "Workspace"}</span>
                <span className="block truncate text-[11px] capitalize leading-tight text-muted-foreground">{current?.role ?? "member"}</span>
              </span>
              <ChevronsUpDown className="h-3.5 w-3.5 shrink-0 text-muted-foreground opacity-60 group-hover:opacity-100" aria-hidden />
            </>
          )}
        </button>
      </DropdownMenuTrigger>
      <DropdownMenuContent align="start" className="w-60">
        <DropdownMenuLabel className="text-xs text-muted-foreground">Workspaces</DropdownMenuLabel>
        {memberships.map((m) => (
          <DropdownMenuItem key={m.workspace.id} onClick={() => { setWorkspace(m.workspace.slug); router.push(`/w/${m.workspace.slug}/dashboard`); }}>
            <span className="flex h-6 w-6 items-center justify-center rounded-md bg-muted text-[10px] font-bold">{initials(m.workspace.name)}</span>
            <span className="min-w-0 flex-1 truncate">{m.workspace.name}</span>
            <span className="text-[11px] capitalize text-muted-foreground">{m.role}</span>
            {m.workspace.slug === current?.workspace.slug && <Check className="h-3.5 w-3.5 text-primary" />}
          </DropdownMenuItem>
        ))}
        <DropdownMenuSeparator />
        <DropdownMenuItem onClick={() => router.push("/onboarding?step=1")}><Plus className="h-4 w-4" /> New workspace</DropdownMenuItem>
      </DropdownMenuContent>
    </DropdownMenu>
  );
}

/** One nav row; shared by the desktop sidebar and the mobile drawer. */
export function NavLink({ item, slug, collapsed, badge, onNavigate }: { item: NavItem; slug: string; collapsed?: boolean; badge?: number; onNavigate?: () => void }) {
  const pathname = usePathname();
  const href = `/w/${slug}/${item.href}`;
  const active = !!pathname?.includes(`/w/${slug}/${item.match ?? item.href}`);
  const Icon = item.icon;
  return (
    <Link
      href={href}
      title={collapsed ? item.label : item.hint}
      aria-current={active ? "page" : undefined}
      onClick={onNavigate}
      className={cn(
        "group relative flex h-9 items-center gap-2.5 rounded-lg px-2.5 text-[13.5px] font-medium transition-colors",
        active ? "bg-sidebar-accent text-sidebar-accent-foreground" : "text-sidebar-foreground/70 hover:bg-sidebar-accent/70 hover:text-sidebar-accent-foreground",
        collapsed && "justify-center px-0",
      )}
    >
      {active && <span className="absolute left-0 top-1/2 h-5 w-[3px] -translate-y-1/2 rounded-r-full bg-primary" aria-hidden />}
      <Icon className={cn("h-4 w-4 shrink-0 transition-colors", item.ai ? "text-ai" : active ? "text-primary" : "text-muted-foreground group-hover:text-foreground")} strokeWidth={active ? 2.25 : 2} aria-hidden />
      {!collapsed && <span className="min-w-0 flex-1 truncate">{item.label}</span>}
      {badge ? (
        <span className={cn("flex h-[18px] min-w-[18px] items-center justify-center rounded-full bg-warning/15 px-1 text-[10.5px] font-semibold tabular-nums text-warning", collapsed && "absolute -right-0.5 -top-0.5 h-4 min-w-4 text-[9.5px]")}>{badge > 99 ? "99+" : badge}</span>
      ) : null}
    </Link>
  );
}

export function useApprovalsBadge() {
  const { workspaceSlug, brandId } = useSession();
  const q = useQuery({
    queryKey: ["approvals", "list", "pending", "badge", brandId],
    queryFn: () => approvalsApi.list({ status: "pending", brand_id: brandId }),
    enabled: !!workspaceSlug,
    retry: false,
    refetchInterval: 60_000,
    staleTime: 30_000,
  });
  return toItems(q.data).length;
}

export function Sidebar() {
  const { sidebarCollapsed: collapsed, toggleSidebar } = useUI();
  const slug = useSession((s) => s.workspaceSlug) ?? "w";
  const pending = useApprovalsBadge();
  return (
    <aside
      data-collapsed={collapsed}
      className={cn("hidden h-dvh shrink-0 flex-col border-r border-sidebar-border bg-sidebar text-sidebar-foreground transition-[width] duration-200 md:flex", collapsed ? "w-[68px]" : "w-[248px]")}
    >
      <div className={cn("flex h-14 items-center px-3", collapsed && "justify-center px-0")}>
        <Link href={`/w/${slug}/dashboard`} className="rounded-lg focus-visible:outline-none focus-visible:ring-[3px] focus-visible:ring-ring/50" aria-label="Botwok home">
          {collapsed ? <span className="flex h-8 w-8 items-center justify-center rounded-lg bg-primary text-primary-foreground"><LogoMark className="h-[18px] w-[18px]" /></span> : <Logo />}
        </Link>
      </div>
      <div className={cn("px-2 pb-2", collapsed && "px-2")}>
        <WorkspaceSwitcher collapsed={collapsed} />
      </div>
      <nav className="flex-1 space-y-4 overflow-y-auto px-2 py-2" aria-label="Primary">
        {NAV.map((g, gi) => (
          <div key={gi} className="space-y-0.5">
            {g.group && !collapsed && <p className="px-2.5 pb-1.5 pt-1 text-[10.5px] font-semibold uppercase tracking-[0.12em] text-muted-foreground/80">{g.group}</p>}
            {g.group && collapsed && gi > 0 && <div className="mx-3 my-2 h-px bg-sidebar-border" aria-hidden />}
            {g.items.map((it) => <NavLink key={it.href} item={it} slug={slug} collapsed={collapsed} badge={it.href === "approvals" ? pending : undefined} />)}
          </div>
        ))}
      </nav>
      <div className="space-y-0.5 border-t border-sidebar-border p-2">
        <NavLink item={SETTINGS_NAV} slug={slug} collapsed={collapsed} />
        <button
          type="button"
          onClick={toggleSidebar}
          aria-label={collapsed ? "Expand sidebar" : "Collapse sidebar"}
          className={cn("flex h-9 w-full items-center gap-2.5 rounded-lg px-2.5 text-[13px] text-muted-foreground transition-colors hover:bg-sidebar-accent/70 hover:text-foreground", collapsed && "justify-center px-0")}
        >
          {collapsed ? <ChevronsRight className="h-4 w-4" /> : <ChevronsLeft className="h-4 w-4" />}
          {!collapsed && <span>Collapse</span>}
          {!collapsed && <kbd className="ml-auto rounded border bg-background px-1 font-mono text-[10px] text-muted-foreground">[</kbd>}
        </button>
      </div>
    </aside>
  );
}

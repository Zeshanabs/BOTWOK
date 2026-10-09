"use client";
import { useEffect } from "react";
import Link from "next/link";
import { usePathname, useRouter } from "next/navigation";
import { Bell, Check, ChevronDown, LogOut, Menu, PanelLeft, Plus, Search, Settings, Sparkles } from "lucide-react";
import { useQuery } from "@tanstack/react-query";
import { Button } from "@/components/ui/button";
import { DropdownMenu, DropdownMenuContent, DropdownMenuItem, DropdownMenuLabel, DropdownMenuSeparator, DropdownMenuTrigger } from "@/components/ui/dropdown-menu";
import { Avatar, AvatarFallback } from "@/components/ui/avatar";
import { api } from "@/lib/api";
import { cn } from "@/lib/utils";
import { useSession } from "@/stores/session";
import { useUI } from "@/stores/ui";
import { ThemeToggle } from "./theme-toggle";
import { titleForPath } from "./nav";

interface Brand { id: string; name: string }
type Notification = { id: string; read_at: string | null };

export function Header() {
  const router = useRouter();
  const pathname = usePathname();
  const { user, workspaceSlug, brandId, setBrand, clear } = useSession();
  const { toggleSidebar, setAiDrawer, aiDrawerOpen } = useUI();
  const brands = useQuery({ queryKey: ["brands"], queryFn: () => api.get<{ items: Brand[] } | Brand[]>("/brands"), enabled: !!workspaceSlug });
  const brandList: Brand[] = Array.isArray(brands.data) ? brands.data : (brands.data?.items ?? []);
  const notifications = useQuery({ queryKey: ["notifications", "unread"], queryFn: () => api.get<{ items: Notification[] } | Notification[]>("/notifications?unread=true"), enabled: !!workspaceSlug, refetchInterval: 60_000 });
  const unread = (Array.isArray(notifications.data) ? notifications.data : notifications.data?.items ?? []).filter((n) => !n.read_at).length;
  const activeBrand = brandList.find((b) => b.id === brandId) ?? brandList[0];
  useEffect(() => { if (activeBrand && activeBrand.id !== brandId) setBrand(activeBrand.id); }, [activeBrand, brandId, setBrand]);
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      const el = e.target as HTMLElement | null;
      if (el && (el.isContentEditable || ["INPUT", "TEXTAREA", "SELECT"].includes(el.tagName))) return;
      if (e.key === "[" && !e.metaKey && !e.ctrlKey && !e.altKey) { e.preventDefault(); toggleSidebar(); }
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [toggleSidebar]);

  async function logout() { try { await api.post("/auth/logout"); } catch { /* ignore */ } clear(); router.push("/login"); }
  const title = titleForPath(pathname, workspaceSlug);

  return (
    <header className="flex h-14 shrink-0 items-center gap-2 border-b bg-background/95 px-3 backdrop-blur supports-[backdrop-filter]:bg-background/80 sm:px-4">
      <Button variant="ghost" size="icon" className="md:hidden" onClick={() => document.dispatchEvent(new CustomEvent("botwok:mobile-nav"))} aria-label="Open menu"><Menu className="h-5 w-5" /></Button>
      <Button variant="ghost" size="icon" className="hidden text-muted-foreground md:inline-flex" onClick={toggleSidebar} aria-label="Toggle sidebar" title="Toggle sidebar ( [ )"><PanelLeft className="h-4 w-4" /></Button>

      <div className="flex min-w-0 items-center gap-1.5">
        <DropdownMenu>
          <DropdownMenuTrigger asChild>
            <button type="button" className="flex h-8 max-w-[200px] items-center gap-1.5 rounded-lg border bg-card px-2.5 text-sm font-medium shadow-card transition-colors hover:bg-accent focus-visible:outline-none focus-visible:ring-[3px] focus-visible:ring-ring/50" aria-label="Switch brand">
              <span className="h-2 w-2 shrink-0 rounded-full bg-primary" aria-hidden />
              <span className="truncate">{activeBrand?.name ?? (brands.isLoading ? "Loading…" : "No brand")}</span>
              <ChevronDown className="h-3.5 w-3.5 shrink-0 text-muted-foreground" aria-hidden />
            </button>
          </DropdownMenuTrigger>
          <DropdownMenuContent align="start" className="w-56">
            <DropdownMenuLabel className="text-xs text-muted-foreground">Brands</DropdownMenuLabel>
            {brandList.map((b) => (
              <DropdownMenuItem key={b.id} onClick={() => setBrand(b.id)}>
                <span className="truncate">{b.name}</span>
                {b.id === activeBrand?.id && <Check className="ml-auto h-3.5 w-3.5 text-primary" />}
              </DropdownMenuItem>
            ))}
            {brandList.length === 0 && <DropdownMenuItem disabled>No brands yet</DropdownMenuItem>}
            <DropdownMenuSeparator />
            <DropdownMenuItem onClick={() => router.push(`/w/${workspaceSlug}/settings/brand?new=1`)}><Plus className="h-4 w-4" /> New brand</DropdownMenuItem>
          </DropdownMenuContent>
        </DropdownMenu>
        {title && (
          <>
            <span className="hidden text-muted-foreground/50 sm:inline" aria-hidden>/</span>
            <span className="hidden truncate text-sm text-muted-foreground sm:inline">{title}</span>
          </>
        )}
      </div>

      <div className="ml-auto flex items-center gap-1">
        <button
          type="button"
          onClick={() => document.dispatchEvent(new CustomEvent("botwok:command-palette"))}
          className="hidden h-8 w-48 items-center gap-2 rounded-lg border bg-muted/50 px-2.5 text-sm text-muted-foreground transition-colors hover:border-foreground/15 hover:bg-muted md:flex lg:w-64"
          aria-label="Search or run a command"
        >
          <Search className="h-3.5 w-3.5" />
          <span className="flex-1 text-left">Search or jump to…</span>
          <kbd className="rounded border bg-background px-1.5 font-mono text-[10px]">⌘K</kbd>
        </button>
        <Button variant="ghost" size="icon" className="md:hidden" onClick={() => document.dispatchEvent(new CustomEvent("botwok:command-palette"))} aria-label="Search"><Search className="h-4 w-4" /></Button>

        <Button
          variant={aiDrawerOpen ? "secondary" : "ghost"}
          size="sm"
          className={cn("gap-1.5 px-2.5", aiDrawerOpen ? "text-foreground" : "text-muted-foreground hover:text-foreground")}
          aria-pressed={aiDrawerOpen}
          aria-label="AI assistant"
          title="AI assistant (⌘J)"
          onClick={() => setAiDrawer(!aiDrawerOpen)}
        >
          <Sparkles className="h-4 w-4 text-ai" /> <span className="hidden lg:inline">Ask AI</span>
        </Button>

        <Button variant="ghost" size="icon" aria-label={unread ? `${unread} unread notifications` : "Notifications"} className="relative text-muted-foreground" onClick={() => router.push(`/w/${workspaceSlug}/settings/system?tab=notifications`)}>
          <Bell className="h-4 w-4" />
          {unread > 0 && <span className="absolute right-1 top-1 flex h-4 min-w-4 items-center justify-center rounded-full bg-destructive px-1 text-[9.5px] font-semibold text-destructive-foreground">{unread > 9 ? "9+" : unread}</span>}
        </Button>
        <ThemeToggle className="hidden sm:inline-flex" />

        <DropdownMenu>
          <DropdownMenuTrigger asChild>
            <button className="ml-1 rounded-full focus-visible:outline-none focus-visible:ring-[3px] focus-visible:ring-ring/50" aria-label="User menu">
              <Avatar className="h-8 w-8 border"><AvatarFallback className="bg-primary/10 text-xs font-semibold text-primary">{(user?.full_name ?? "?").split(/\s+/).map((w) => w[0]).join("").slice(0, 2).toUpperCase()}</AvatarFallback></Avatar>
            </button>
          </DropdownMenuTrigger>
          <DropdownMenuContent align="end" className="w-56">
            <DropdownMenuLabel className="font-normal"><p className="truncate text-sm font-medium">{user?.full_name}</p><p className="truncate text-xs text-muted-foreground">{user?.email}</p></DropdownMenuLabel>
            <DropdownMenuSeparator />
            <DropdownMenuItem asChild><Link href={`/w/${workspaceSlug}/settings/system`}><Settings className="h-4 w-4" /> Settings</Link></DropdownMenuItem>
            <DropdownMenuItem onClick={logout}><LogOut className="h-4 w-4" /> Sign out</DropdownMenuItem>
          </DropdownMenuContent>
        </DropdownMenu>
      </div>
    </header>
  );
}

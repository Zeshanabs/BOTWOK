"use client";
import { useEffect } from "react";
import { useRouter } from "next/navigation";
import { Bell, Bot, ChevronDown, LogOut, Menu, Search } from "lucide-react";
import { useQuery } from "@tanstack/react-query";
import { Button } from "@/components/ui/button";
import { DropdownMenu, DropdownMenuContent, DropdownMenuItem, DropdownMenuLabel, DropdownMenuSeparator, DropdownMenuTrigger } from "@/components/ui/dropdown-menu";
import { Avatar, AvatarFallback } from "@/components/ui/avatar";
import { api } from "@/lib/api";
import { useSession } from "@/stores/session";
import { useUI } from "@/stores/ui";

interface Brand { id: string; name: string }

export function Header() {
  const router = useRouter();
  const { user, memberships, workspaceSlug, brandId, setWorkspace, setBrand, clear } = useSession();
  const { toggleSidebar, setAiDrawer, aiDrawerOpen } = useUI();
  const brands = useQuery({ queryKey: ["brands"], queryFn: () => api.get<{ items: Brand[] } | Brand[]>("/brands"), enabled: !!workspaceSlug });
  const brandList: Brand[] = Array.isArray(brands.data) ? brands.data : (brands.data?.items ?? []);
  const notifications = useQuery({ queryKey: ["notifications", "unread"], queryFn: () => api.get<{ items: { id: string; read_at: string | null }[] } | { id: string; read_at: string | null }[]>("/notifications?unread=true"), enabled: !!workspaceSlug, refetchInterval: 60_000 });
  const unread = (Array.isArray(notifications.data) ? notifications.data : notifications.data?.items ?? []).filter((n) => !n.read_at).length;
  const activeBrand = brandList.find((b) => b.id === brandId) ?? brandList[0];
  useEffect(() => { if (activeBrand && activeBrand.id !== brandId) setBrand(activeBrand.id); }, [activeBrand, brandId, setBrand]);

  async function logout() { try { await api.post("/auth/logout"); } catch { /* ignore */ } clear(); router.push("/login"); }

  return (
    <header className="flex h-14 items-center gap-2 border-b bg-background px-3 sm:px-4">
      <Button variant="ghost" size="icon" onClick={toggleSidebar} aria-label="Toggle sidebar"><Menu className="h-4 w-4" /></Button>
      <DropdownMenu>
        <DropdownMenuTrigger asChild><Button variant="outline" size="sm" className="max-w-[160px]"><span className="truncate">{memberships.find((m) => m.workspace.slug === workspaceSlug)?.workspace.name ?? "Workspace"}</span><ChevronDown className="ml-1 h-3 w-3" /></Button></DropdownMenuTrigger>
        <DropdownMenuContent align="start">
          <DropdownMenuLabel>Workspaces</DropdownMenuLabel>
          {memberships.map((m) => <DropdownMenuItem key={m.workspace.id} onClick={() => { setWorkspace(m.workspace.slug); router.push(`/w/${m.workspace.slug}/dashboard`); }}>{m.workspace.name} <span className="ml-auto text-xs text-muted-foreground">{m.role}</span></DropdownMenuItem>)}
        </DropdownMenuContent>
      </DropdownMenu>
      <DropdownMenu>
        <DropdownMenuTrigger asChild><Button variant="outline" size="sm" className="max-w-[180px]"><span className="truncate">{activeBrand?.name ?? "No brand"}</span><ChevronDown className="ml-1 h-3 w-3" /></Button></DropdownMenuTrigger>
        <DropdownMenuContent align="start">
          <DropdownMenuLabel>Brands</DropdownMenuLabel>
          {brandList.map((b) => <DropdownMenuItem key={b.id} onClick={() => setBrand(b.id)}>{b.name}</DropdownMenuItem>)}
          <DropdownMenuSeparator />
          <DropdownMenuItem onClick={() => router.push(`/w/${workspaceSlug}/settings/brand?new=1`)}>+ New brand</DropdownMenuItem>
        </DropdownMenuContent>
      </DropdownMenu>
      <div className="ml-auto flex items-center gap-1">
        <Button variant="ghost" size="sm" className="hidden gap-2 text-muted-foreground md:flex" onClick={() => document.dispatchEvent(new CustomEvent("botwok:command-palette"))}>
          <Search className="h-4 w-4" /> Search <kbd className="rounded border px-1 text-[10px]">⌘K</kbd>
        </Button>
        <Button variant={aiDrawerOpen ? "secondary" : "ghost"} size="icon" aria-label="AI assistant" onClick={() => setAiDrawer(!aiDrawerOpen)}><Bot className="h-4 w-4 text-ai" /></Button>
        <Button variant="ghost" size="icon" aria-label="Notifications" className="relative" onClick={() => router.push(`/w/${workspaceSlug}/settings/system?tab=notifications`)}>
          <Bell className="h-4 w-4" />{unread > 0 && <span className="absolute right-1 top-1 h-2 w-2 rounded-full bg-red-500" />}
        </Button>
        <DropdownMenu>
          <DropdownMenuTrigger asChild><button className="ml-1 rounded-full" aria-label="User menu"><Avatar className="h-8 w-8"><AvatarFallback>{(user?.full_name ?? "?").slice(0, 2).toUpperCase()}</AvatarFallback></Avatar></button></DropdownMenuTrigger>
          <DropdownMenuContent align="end">
            <DropdownMenuLabel className="font-normal"><p className="text-sm font-medium">{user?.full_name}</p><p className="text-xs text-muted-foreground">{user?.email}</p></DropdownMenuLabel>
            <DropdownMenuSeparator />
            <DropdownMenuItem onClick={() => router.push(`/w/${workspaceSlug}/settings/system`)}>Settings</DropdownMenuItem>
            <DropdownMenuItem onClick={logout}><LogOut className="mr-2 h-4 w-4" /> Sign out</DropdownMenuItem>
          </DropdownMenuContent>
        </DropdownMenu>
      </div>
    </header>
  );
}

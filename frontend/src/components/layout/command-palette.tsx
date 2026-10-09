"use client";
/**
 * ⌘K command palette (doc 23 §23.4, doc 24 §0.2): navigate, create, run AI slash commands.
 * Opens on ⌘K / Ctrl+K and on the `botwok:command-palette` DOM event (dispatched by the header search button).
 * Mounted from src/app/w/[workspace]/template.tsx.
 */
import { useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import type { LucideIcon } from "lucide-react";
import {
  BarChart3, Bell, Bot, CalendarDays, CheckSquare, FileText, Image as ImageIcon, KeyRound, LayoutDashboard, Lightbulb, Palette, Plus, Search,
  Send, Settings, Share2, Sparkles, TrendingUp, UserPlus, Users, Workflow,
} from "lucide-react";
import { CommandDialog, CommandEmpty, CommandGroup, CommandInput, CommandItem, CommandList, CommandSeparator, CommandShortcut } from "@/components/ui/command";
import { useSession } from "@/stores/session";
import { useBrands } from "@/features/brand/hooks";
import { SLASH_COMMANDS } from "@/features/ai/components/composer";

interface NavEntry { label: string; href: string; icon: LucideIcon; keywords?: string[]; shortcut?: string }

const NAV: NavEntry[] = [
  { label: "Dashboard", href: "dashboard", icon: LayoutDashboard, shortcut: "G D" },
  { label: "Command Center", href: "command-center", icon: Bot, keywords: ["ai", "assistant", "runs"], shortcut: "G C" },
  { label: "Research", href: "research", icon: Search, keywords: ["sources"] },
  { label: "Competitors", href: "competitors", icon: Users },
  { label: "Trends", href: "trends", icon: TrendingUp },
  { label: "Ideas", href: "ideas", icon: Lightbulb },
  { label: "Studio", href: "studio", icon: Sparkles, keywords: ["content", "write"], shortcut: "G S" },
  { label: "Media Library", href: "media", icon: ImageIcon, keywords: ["images", "video"] },
  { label: "Calendar", href: "calendar", icon: CalendarDays, shortcut: "G L" },
  { label: "Approvals", href: "approvals", icon: CheckSquare, shortcut: "G A" },
  { label: "Publishing", href: "publishing", icon: Send, keywords: ["queue"], shortcut: "G P" },
  { label: "Analytics", href: "analytics", icon: BarChart3 },
  { label: "Reports", href: "reports", icon: FileText },
  { label: "Automations", href: "automations", icon: Workflow, keywords: ["workflows"] },
  { label: "Settings › Brand", href: "settings/brand", icon: Palette, keywords: ["voice", "pillars"] },
  { label: "Settings › Social Accounts", href: "settings/social", icon: Share2, keywords: ["connect", "instagram", "linkedin"] },
  { label: "Settings › AI", href: "settings/ai", icon: Bot, keywords: ["providers", "models", "budget", "cost", "prompts"] },
  { label: "Settings › Team", href: "settings/team", icon: Users, keywords: ["members", "invite", "roles"] },
  { label: "Settings › System", href: "settings/system", icon: Settings, keywords: ["workspace", "export"] },
  { label: "Notifications", href: "settings/system?tab=notifications", icon: Bell },
  { label: "API keys", href: "settings/system?tab=api-keys", icon: KeyRound },
];

const CREATE: NavEntry[] = [
  { label: "New research run", href: "research", icon: Search },
  { label: "Generate ideas", href: "ideas", icon: Lightbulb },
  { label: "New AI run", href: "command-center", icon: Bot },
  { label: "New brand", href: "settings/brand?new=1", icon: Plus },
  { label: "Invite teammate", href: "settings/team", icon: UserPlus },
];

const GO_KEYS: Record<string, string> = { d: "dashboard", c: "command-center", s: "studio", l: "calendar", a: "approvals", p: "publishing" };

function isTyping(t: EventTarget | null): boolean {
  const el = t as HTMLElement | null;
  return !!el && (el.isContentEditable || ["INPUT", "TEXTAREA", "SELECT"].includes(el.tagName));
}

export function CommandPalette() {
  const router = useRouter();
  const slug = useSession((s) => s.workspaceSlug);
  const setBrand = useSession((s) => s.setBrand);
  const brands = useBrands();
  const [open, setOpen] = useState(false);
  const [query, setQuery] = useState("");

  useEffect(() => {
    const onToggle = () => setOpen((o) => !o);
    let gPressed = 0;
    const onKey = (e: KeyboardEvent) => {
      if ((e.metaKey || e.ctrlKey) && e.key.toLowerCase() === "k") { e.preventDefault(); setOpen((o) => !o); return; }
      if (isTyping(e.target) || e.metaKey || e.ctrlKey || e.altKey) return;
      // `g` then a letter jumps to a section (doc 24 §0.8)
      if (e.key === "g") { gPressed = Date.now(); return; }
      if (gPressed && Date.now() - gPressed < 1000 && GO_KEYS[e.key] && slug) { gPressed = 0; router.push(`/w/${slug}/${GO_KEYS[e.key]}`); }
    };
    document.addEventListener("botwok:command-palette", onToggle);
    window.addEventListener("keydown", onKey);
    return () => { document.removeEventListener("botwok:command-palette", onToggle); window.removeEventListener("keydown", onKey); };
  }, [router, slug]);

  function go(href: string) {
    setOpen(false);
    setQuery("");
    router.push(`/w/${slug}/${href}`);
  }
  function runAi(prompt: string) {
    go(`command-center?prompt=${encodeURIComponent(prompt)}`);
  }

  const q = query.trim();
  const isSlash = q.startsWith("/");

  return (
    <CommandDialog open={open} onOpenChange={(o) => { setOpen(o); if (!o) setQuery(""); }} title="Command palette" description="Navigate, create, or run an AI command">
      <CommandInput placeholder="Search or type / to run an AI command…" value={query} onValueChange={setQuery} />
      <CommandList>
        <CommandEmpty>No matches. Press Enter on “Ask AI” to send it to the Command Center.</CommandEmpty>
        {q && isSlash && (
          <CommandGroup heading="AI">
            <CommandItem forceMount value={`run ${q}`} onSelect={() => runAi(q)}>
              <Bot className="text-ai" /> Run: <span className="font-mono">{q}</span>
              <CommandShortcut>↵</CommandShortcut>
            </CommandItem>
          </CommandGroup>
        )}
        {(!q || isSlash) && (
          <CommandGroup heading="AI commands">
            {SLASH_COMMANDS.filter((c) => !isSlash || c.cmd.startsWith(q.split(/\s/)[0])).slice(0, isSlash ? 12 : 4).map((c) => (
              <CommandItem key={c.cmd} value={`${c.cmd} ${c.hint}`} onSelect={() => (q.includes(" ") ? runAi(q) : setQuery(`${c.cmd} `))}>
                <Sparkles className="text-ai" /> <span className="font-mono">{c.cmd} …</span><span className="truncate text-xs text-muted-foreground">{c.hint}</span>
              </CommandItem>
            ))}
          </CommandGroup>
        )}
        {!isSlash && (
          <>
            <CommandSeparator />
            <CommandGroup heading="Navigate">
              {NAV.map((n) => (
                <CommandItem key={n.href} value={n.label} keywords={n.keywords} onSelect={() => go(n.href)}>
                  <n.icon /> {n.label}{n.shortcut && <CommandShortcut>{n.shortcut}</CommandShortcut>}
                </CommandItem>
              ))}
            </CommandGroup>
            <CommandSeparator />
            <CommandGroup heading="Create">
              {CREATE.map((n) => <CommandItem key={n.label} value={n.label} onSelect={() => go(n.href)}><n.icon /> {n.label}</CommandItem>)}
            </CommandGroup>
            {q && (
              <CommandGroup heading="AI">
                {/* value deliberately excludes the query so navigation matches rank first */}
                <CommandItem forceMount value="__ask_ai__" onSelect={() => runAi(q)}><Bot className="text-ai" /> Ask AI: “{q}”</CommandItem>
              </CommandGroup>
            )}
            {(brands.data ?? []).length > 1 && (
              <>
                <CommandSeparator />
                <CommandGroup heading="Switch brand">
                  {(brands.data ?? []).map((b) => (
                    <CommandItem key={b.id} value={`brand ${b.name}`} onSelect={() => { setBrand(b.id); setOpen(false); setQuery(""); }}><Palette /> {b.name}</CommandItem>
                  ))}
                </CommandGroup>
              </>
            )}
          </>
        )}
      </CommandList>
    </CommandDialog>
  );
}

"use client";
import Link from "next/link";
import { useParams, usePathname } from "next/navigation";
import { Bot, Palette, Server, Share2, Users } from "lucide-react";
import { cn } from "@/lib/utils";

const ITEMS = [
  { href: "brand", label: "Brand", hint: "Voice, pillars, audience", icon: Palette },
  { href: "social", label: "Social accounts", hint: "Connections and health", icon: Share2 },
  { href: "ai", label: "AI", hint: "Providers, models, budgets", icon: Bot },
  { href: "team", label: "Team", hint: "Members, roles, invites", icon: Users },
  { href: "system", label: "System", hint: "Workspace, keys, exports", icon: Server },
];

export default function SettingsLayout({ children }: { children: React.ReactNode }) {
  const { workspace } = useParams<{ workspace: string }>();
  const pathname = usePathname();
  return (
    <div className="flex flex-col gap-6 lg:flex-row lg:gap-8">
      <nav aria-label="Settings" className="-mx-4 flex shrink-0 gap-1 overflow-x-auto border-b px-4 pb-2 lg:sticky lg:top-0 lg:mx-0 lg:w-56 lg:flex-col lg:self-start lg:border-b-0 lg:px-0 lg:pb-0">
        <p className="hidden px-2.5 pb-2 text-[10.5px] font-semibold uppercase tracking-[0.12em] text-muted-foreground/80 lg:block">Settings</p>
        {ITEMS.map((it) => {
          const href = `/w/${workspace}/settings/${it.href}`;
          const active = pathname?.startsWith(href) || (it.href === "social" && pathname?.includes("/settings/social-accounts"));
          const Icon = it.icon;
          return (
            <Link key={it.href} href={href} aria-current={active ? "page" : undefined}
                  className={cn("group relative flex shrink-0 items-center gap-2.5 rounded-lg px-2.5 py-2 text-sm whitespace-nowrap transition-colors",
                    active ? "bg-accent font-medium text-accent-foreground" : "text-muted-foreground hover:bg-accent/60 hover:text-foreground")}>
              {active && <span className="absolute left-0 top-1/2 hidden h-5 w-[3px] -translate-y-1/2 rounded-r-full bg-primary lg:block" aria-hidden />}
              <Icon className={cn("h-4 w-4 shrink-0", active ? "text-primary" : "text-muted-foreground group-hover:text-foreground")} />
              <span className="min-w-0">
                <span className="block leading-tight">{it.label}</span>
                <span className="hidden text-[11px] font-normal leading-tight text-muted-foreground lg:block">{it.hint}</span>
              </span>
            </Link>
          );
        })}
      </nav>
      <div className="min-w-0 flex-1">{children}</div>
    </div>
  );
}

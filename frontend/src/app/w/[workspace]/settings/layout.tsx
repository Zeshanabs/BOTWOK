"use client";
import Link from "next/link";
import { useParams, usePathname } from "next/navigation";
import { Bot, Palette, Server, Share2, Users } from "lucide-react";
import { cn } from "@/lib/utils";

const ITEMS = [
  { href: "brand", label: "Brand", icon: Palette },
  { href: "social", label: "Social Accounts", icon: Share2 },
  { href: "ai", label: "AI", icon: Bot },
  { href: "team", label: "Team", icon: Users },
  { href: "system", label: "System", icon: Server },
];

export default function SettingsLayout({ children }: { children: React.ReactNode }) {
  const { workspace } = useParams<{ workspace: string }>();
  const pathname = usePathname();
  return (
    <div className="flex flex-col gap-6 lg:flex-row">
      <nav aria-label="Settings" className="-mx-4 flex shrink-0 gap-1 overflow-x-auto border-b px-4 pb-2 lg:mx-0 lg:w-48 lg:flex-col lg:border-b-0 lg:px-0 lg:pb-0">
        <p className="hidden px-2 pb-1 text-[11px] font-medium uppercase tracking-wide text-muted-foreground lg:block">Settings</p>
        {ITEMS.map((it) => {
          const href = `/w/${workspace}/settings/${it.href}`;
          const active = pathname?.startsWith(href) || (it.href === "social" && pathname?.includes("/settings/social-accounts"));
          const Icon = it.icon;
          return (
            <Link key={it.href} href={href} aria-current={active ? "page" : undefined}
                  className={cn("flex shrink-0 items-center gap-2 rounded-md px-2 py-1.5 text-sm whitespace-nowrap", active ? "bg-accent font-medium text-accent-foreground" : "text-muted-foreground hover:bg-accent hover:text-accent-foreground")}>
              <Icon className="h-4 w-4" /> {it.label}
            </Link>
          );
        })}
      </nav>
      <div className="min-w-0 flex-1">{children}</div>
    </div>
  );
}

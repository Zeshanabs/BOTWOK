"use client";
import Link from "next/link";
import { PlatformIcon } from "@/components/data/platform-icon";
import { Skeleton } from "@/components/ui/skeleton";
import { useSocialAccounts, useWorkspacePath } from "@/features/common/hooks";
import type { SocialAccount } from "@/features/common/types";
import { relTime, toItems } from "@/features/common/utils";
import { cn } from "@/lib/utils";

export function accountHealth(a: SocialAccount): { tone: "ok" | "warn" | "bad" | "muted"; label: string } {
  if (a.status === "expired" || a.status === "revoked") return { tone: "bad", label: `${a.status} — reconnect` };
  if (a.status === "error") return { tone: "bad", label: a.health?.last_error ?? "error" };
  if (a.status === "disconnected") return { tone: "muted", label: "disconnected" };
  if (a.health?.audit_pending) return { tone: "muted", label: "audit pending" };
  const rl = a.health?.rate_limited_until;
  if (rl && new Date(rl).getTime() > new Date().getTime()) return { tone: "warn", label: `rate-limited, resets ${relTime(rl)}` };
  if (a.health?.token_valid === false) return { tone: "bad", label: "token invalid" };
  const exp = a.token_expires_at ?? a.health?.expires_at ?? null;
  if (exp) {
    const days = (new Date(exp).getTime() - new Date().getTime()) / 86_400_000;
    if (days < 0) return { tone: "bad", label: "token expired — reconnect" };
    if (days < 7) return { tone: "warn", label: `token expires ${relTime(exp)}` };
  }
  return { tone: "ok", label: "ok" };
}
const DOT = { ok: "bg-emerald-500", warn: "bg-amber-500", bad: "bg-red-500", muted: "bg-zinc-400" };

/** Per-platform account health strip (doc 24 §16): ok, rate-limited with reset, expiring, audit pending, broken. */
export function AccountHealthStrip({ brandId, compact }: { brandId?: string | null; compact?: boolean }) {
  const ws = useWorkspacePath();
  const q = useSocialAccounts(brandId);
  const accounts = toItems(q.data).filter((a) => a.status !== "disconnected");
  if (q.isLoading) return <Skeleton className="h-8 w-full" />;
  if (q.error) return <p className="text-xs text-muted-foreground">Account health unavailable.</p>;
  if (!accounts.length) return <p className="text-sm text-muted-foreground">No connected accounts. <Link className="text-primary hover:underline" href={ws("settings/social-accounts")}>Connect one</Link></p>;
  return (
    <ul className={cn("flex flex-wrap gap-2", compact && "flex-col")} aria-label="Account health">
      {accounts.map((a) => {
        const h = accountHealth(a);
        return (
          <li key={a.id} className="flex items-center gap-1.5 rounded-full border px-2 py-1 text-xs">
            <PlatformIcon platform={a.platform} size={16} />
            <span className="max-w-[140px] truncate">{a.display_name}</span>
            <span className={cn("h-2 w-2 rounded-full", DOT[h.tone])} aria-hidden />
            <span className={cn(h.tone === "bad" ? "text-red-600" : h.tone === "warn" ? "text-amber-700 dark:text-amber-300" : "text-muted-foreground")}>{h.label}</span>
            {h.tone === "bad" && <Link href={ws("settings/social-accounts")} className="text-primary hover:underline">Fix</Link>}
          </li>
        );
      })}
    </ul>
  );
}

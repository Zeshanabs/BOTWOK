"use client";
import { useState } from "react";
import { toast } from "sonner";
import { Check, Minus, TriangleAlert } from "lucide-react";
import { Avatar, AvatarFallback, AvatarImage } from "@/components/ui/avatar";
import { Button } from "@/components/ui/button";
import { Card, CardContent } from "@/components/ui/card";
import { Progress } from "@/components/ui/progress";
import { StatusChip } from "@/components/data/status-chip";
import { PlatformIcon } from "@/components/data/platform-icon";
import { errorMessage } from "@/components/data/async-states";
import { fmtRelative, humanize, msSince } from "@/lib/formatters";
import { useCan } from "@/lib/permissions";
import { cn } from "@/lib/utils";
import { useSocialMutations } from "../hooks";
import { SCOPE_LABELS } from "../requirements";
import { capabilityState, tokenExpiry, type AccountHealth, type SocialAccount } from "../types";

const DAY = 86_400_000;

function Expiry({ at, now }: { at: string | null; now: number }) {
  if (!at) return <p className="text-xs text-muted-foreground">Token: no expiry reported</p>;
  const left = -(msSince(at, now) ?? 0);
  const days = Math.floor(left / DAY);
  if (left <= 0) return <p className="text-xs font-medium text-red-700 dark:text-red-300">Token expired {fmtRelative(at)} — reconnect to resume publishing</p>;
  const warn = days < 7;
  return (
    <div className="space-y-1">
      <p className={cn("text-xs", warn ? "font-medium text-amber-700 dark:text-amber-300" : "text-muted-foreground")}>Token: {days >= 1 ? `${days} day${days === 1 ? "" : "s"}` : `${Math.max(1, Math.round(left / 3_600_000))} h`} left</p>
      <Progress value={Math.max(2, Math.min(100, (left / (60 * DAY)) * 100))} className={cn("h-1.5", warn && "[&>*]:bg-amber-500")} aria-label="Token lifetime remaining" />
    </div>
  );
}

export function AccountCard({ account, now, highlight, onReconnect, onDisconnect }: { account: SocialAccount; now: number; highlight?: boolean; onReconnect: () => void; onDisconnect: () => void }) {
  const can = useCan();
  const { test, refresh } = useSocialMutations();
  const [showScopes, setShowScopes] = useState(false);
  const [health, setHealth] = useState<AccountHealth | null>(null);
  const scopes = account.scopes ?? [];
  const caps = Object.entries(account.capabilities ?? {});
  const inactive = account.status !== "active";

  return (
    <Card className={cn("gap-3 py-4", highlight && "ring-2 ring-primary")}>
      <CardContent className="space-y-3 px-4 text-sm">
        <div className="flex items-start gap-3">
          <div className="relative">
            <Avatar className="h-10 w-10"><AvatarImage src={account.avatar_url ?? undefined} alt="" /><AvatarFallback>{account.display_name.slice(0, 2).toUpperCase()}</AvatarFallback></Avatar>
            <PlatformIcon platform={account.platform} size={18} className="absolute -bottom-1 -right-1 ring-2 ring-background" />
          </div>
          <div className="min-w-0 flex-1">
            <p className="truncate font-medium">{account.display_name}</p>
            <p className="truncate text-xs text-muted-foreground">{account.handle ? `@${account.handle.replace(/^@/, "")} · ` : ""}{humanize(account.account_type ?? "account")}{account.auth_flavor ? ` · ${humanize(account.auth_flavor)}` : ""}</p>
          </div>
          <StatusChip status={account.status} />
        </div>

        <Expiry at={tokenExpiry(account)} now={now} />
        {account.refresh_strategy && <p className="text-xs text-muted-foreground">Auto-refresh: {account.refresh_strategy === "reauth" ? "not available — reconnect before expiry" : "available"}</p>}
        {account.scheduled_posts_count ? <p className="text-xs text-muted-foreground">{account.scheduled_posts_count} scheduled post{account.scheduled_posts_count === 1 ? "" : "s"} use this account</p> : null}

        {scopes.length > 0 && (
          <div className="text-xs">
            <span className="text-muted-foreground">Scopes </span>
            {(showScopes ? scopes : scopes.slice(0, 3)).map((s, i) => (
              <span key={s}>{i > 0 && ", "}<span title={s}>{SCOPE_LABELS[s] ?? s}</span>{SCOPE_LABELS[s] && <span className="font-mono text-[10px] text-muted-foreground"> ({s})</span>}</span>
            ))}
            {scopes.length > 3 && <button type="button" className="ml-1 text-primary hover:underline" onClick={() => setShowScopes((v) => !v)}>{showScopes ? "less" : `+${scopes.length - 3} more`}</button>}
          </div>
        )}

        {caps.length > 0 && (
          <div className="flex flex-wrap gap-1" aria-label="Capabilities">
            {caps.map(([k, v]) => {
              const st = capabilityState(v);
              const reason = v && typeof v === "object" ? v.reason : null;
              return (
                <span key={k} title={reason ?? undefined} className={cn("inline-flex items-center gap-0.5 rounded-full border px-1.5 py-0.5 text-[11px]",
                  st === "available" ? "border-green-300 text-green-800 dark:border-green-800 dark:text-green-200" : st === "degraded" ? "border-amber-300 text-amber-800 dark:border-amber-800 dark:text-amber-200" : "border-zinc-300 text-zinc-500 dark:border-zinc-700")}>
                  {st === "available" ? <Check className="h-3 w-3" /> : st === "degraded" ? <TriangleAlert className="h-3 w-3" /> : <Minus className="h-3 w-3" />}
                  {k.replace(/^publish\./, "").replace(/[._]/g, " ")}
                </span>
              );
            })}
          </div>
        )}

        {account.health?.error && <p className="text-xs text-red-700 dark:text-red-300">{account.health.error}</p>}
        {health && (
          <div className={cn("rounded-md p-2 text-xs", health.token_valid === false ? "bg-red-50 text-red-900 dark:bg-red-950/40 dark:text-red-200" : "bg-muted")}>
            <p className="font-medium">Test: {health.token_valid === false ? "token invalid" : "token valid"}</p>
            {(health.scopes_missing?.length ?? 0) > 0 && <p>Missing permissions: {health.scopes_missing?.join(", ")}</p>}
            {health.error && <p>{health.error}</p>}
          </div>
        )}
        {account.last_probe_at && <p className="text-[11px] text-muted-foreground">Last checked {fmtRelative(account.last_probe_at)}</p>}

        {can.manage && (
          <div className="flex flex-wrap gap-2 pt-1">
            {inactive ? <Button size="sm" onClick={onReconnect}>Reconnect</Button> : (
              <Button size="sm" variant="outline" disabled={test.isPending}
                      onClick={() => test.mutate(account.id, { onSuccess: (h) => { setHealth(h ?? {}); toast.success("Connection tested"); }, onError: (e) => toast.error(errorMessage(e)) })}>
                {test.isPending ? "Testing…" : "Test"}
              </Button>
            )}
            {!inactive && <Button size="sm" variant="outline" disabled={refresh.isPending} onClick={() => refresh.mutate(account.id, { onSuccess: () => toast.success("Token refreshed"), onError: (e) => toast.error(errorMessage(e)) })}>Refresh</Button>}
            {!inactive && <Button size="sm" variant="ghost" onClick={onReconnect}>Reconnect</Button>}
            {account.status !== "disconnected" && <Button size="sm" variant="ghost" className="text-destructive" onClick={onDisconnect}>Disconnect</Button>}
          </div>
        )}
      </CardContent>
    </Card>
  );
}

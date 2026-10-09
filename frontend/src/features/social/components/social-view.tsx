"use client";
import { useEffect, useRef, useState } from "react";
import { usePathname, useRouter, useSearchParams } from "next/navigation";
import { toast } from "sonner";
import { AlertCircle, Share2 } from "lucide-react";
import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert";
import { Button } from "@/components/ui/button";
import { Checkbox } from "@/components/ui/checkbox";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { PageHeader } from "@/components/shared/page-header";
import { PlatformIcon } from "@/components/shared/platform-icon";
import { ConfirmDialog } from "@/components/shared/confirm-dialog";
import { CardGridSkeleton, QueryError, errorMessage } from "@/components/shared/async-states";
import { ApiError } from "@/lib/api";
import { PLATFORMS, platformMeta } from "@/lib/platforms";
import { useCan } from "@/lib/permissions";
import { useNow } from "@/hooks/useNow";
import { useActiveBrandId, useBrands } from "@/features/brand/hooks";
import { useSocialAccounts, useSocialMutations } from "../hooks";
import type { SocialAccount } from "../types";
import { AccountCard } from "./account-card";
import { ConnectDialog } from "./connect-dialog";
import { SelectionDialog } from "./selection-dialog";

const ALL = "all";
const STATUSES = ["active", "expired", "revoked", "error", "disconnected"];

export function SocialView() {
  const router = useRouter();
  const pathname = usePathname();
  const sp = useSearchParams();
  const can = useCan();
  const brandId = useActiveBrandId();
  const brandName = useBrands().data?.find((b) => b.id === brandId)?.name;
  const accounts = useSocialAccounts(brandId);
  const { disconnect } = useSocialMutations();
  const now = useNow(true, 60_000);
  const [status, setStatus] = useState(ALL);
  const [platform, setPlatform] = useState(ALL);
  const [connectPlatform, setConnectPlatform] = useState<string | null>(null);
  const [reconnectId, setReconnectId] = useState<string | undefined>(undefined);
  const [disconnecting, setDisconnecting] = useState<SocialAccount | null>(null);
  const [force, setForce] = useState(false);
  const [conflict, setConflict] = useState<string | null>(null);
  const handled = useRef<string | null>(null);

  const connected = sp.get("connected");
  const selectToken = sp.get("select") ?? sp.get("selection_token") ?? sp.get("state_ref");
  const oauthError = sp.get("error");

  // `?connected=<id>` after OAuth callback: toast once, keep highlight, then clean the URL
  useEffect(() => {
    if (connected && handled.current !== connected) {
      handled.current = connected;
      toast.success("Account connected — checking its capabilities");
    }
  }, [connected]);

  function clearParams(keep?: Record<string, string>) {
    const p = new URLSearchParams();
    for (const [k, v] of Object.entries(keep ?? {})) p.set(k, v);
    const s = p.toString();
    router.replace(s ? `${pathname}?${s}` : pathname);
  }

  const list = (accounts.data ?? [])
    .filter((a) => status === ALL || a.status === status)
    .filter((a) => platform === ALL || a.platform === platform);

  return (
    <div>
      <PageHeader
        title={`Social Accounts${brandName ? ` · ${brandName}` : ""}`}
        description="Connect, monitor and reconnect accounts. Each card shows what the platform allows for that account."
        actions={
          <>
            <Select value={status} onValueChange={setStatus}>
              <SelectTrigger size="sm" aria-label="Status"><SelectValue /></SelectTrigger>
              <SelectContent><SelectItem value={ALL}>All statuses</SelectItem>{STATUSES.map((s) => <SelectItem key={s} value={s}>{s}</SelectItem>)}</SelectContent>
            </Select>
            <Select value={platform} onValueChange={setPlatform}>
              <SelectTrigger size="sm" aria-label="Platform"><SelectValue /></SelectTrigger>
              <SelectContent><SelectItem value={ALL}>All platforms</SelectItem>{PLATFORMS.map((p) => <SelectItem key={p.id} value={p.id}>{p.label}</SelectItem>)}</SelectContent>
            </Select>
          </>
        }
      />

      {oauthError && (
        <Alert variant="destructive" className="mb-4">
          <AlertCircle />
          <AlertTitle>{oauthError === "access_denied" ? "Connection cancelled" : oauthError === "invalid_oauth_state" || oauthError === "invalid_state" ? "This sign-in link expired" : "The platform returned an error"}</AlertTitle>
          <AlertDescription>
            <p>{sp.get("message") ?? sp.get("error_description") ?? (oauthError === "access_denied" ? "Nothing was connected. You can start again whenever you're ready." : "Start the connection again. If it keeps failing, check the platform app settings in System settings.")}</p>
            <Button size="sm" variant="outline" className="mt-2" onClick={() => clearParams()}>Dismiss</Button>
          </AlertDescription>
        </Alert>
      )}

      {accounts.isLoading ? <CardGridSkeleton count={4} className="lg:grid-cols-2 xl:grid-cols-2" /> : accounts.error ? (
        <QueryError error={accounts.error} onRetry={() => accounts.refetch()} title="Couldn't load connected accounts" />
      ) : list.length ? (
        <div className="grid gap-4 lg:grid-cols-2">
          {list.map((a) => (
            <AccountCard key={a.id} account={a} now={now} highlight={a.id === connected}
                         onReconnect={() => { setReconnectId(a.id); setConnectPlatform(a.platform); }}
                         onDisconnect={() => { setDisconnecting(a); setForce(false); setConflict(null); }} />
          ))}
        </div>
      ) : (accounts.data ?? []).length ? (
        <p className="rounded-lg border border-dashed p-6 text-center text-sm text-muted-foreground">No accounts match these filters.</p>
      ) : (
        <div className="rounded-xl border border-dashed p-8 text-center">
          <Share2 className="mx-auto mb-3 h-8 w-8 text-muted-foreground" />
          <p className="font-medium">No accounts connected{brandName ? ` for ${brandName}` : ""}</p>
          <p className="mt-1 text-sm text-muted-foreground">Connect a platform below. Each one shows its real requirements before you leave Botwok.</p>
        </div>
      )}

      <section className="mt-8">
        <h2 className="mb-3 text-sm font-semibold uppercase tracking-wide text-muted-foreground">Connect</h2>
        {!can.manage ? <p className="text-sm text-muted-foreground">Only owners and admins can connect or disconnect accounts.</p> : (
          <div className="grid grid-cols-2 gap-2 sm:grid-cols-3 lg:grid-cols-5">
            {PLATFORMS.map((p) => (
              <Button key={p.id} variant="outline" className="h-auto justify-start gap-2 py-2.5" disabled={!brandId} onClick={() => { setReconnectId(undefined); setConnectPlatform(p.id); }}>
                <PlatformIcon platform={p.id} size={20} /> {p.label}
              </Button>
            ))}
          </div>
        )}
      </section>

      <ConnectDialog platform={connectPlatform} brandId={brandId} reconnectAccountId={reconnectId} onOpenChange={(o) => { if (!o) { setConnectPlatform(null); setReconnectId(undefined); } }} />
      <SelectionDialog key={selectToken ?? "none"} token={selectToken} platform={sp.get("platform")} onClose={(id) => clearParams(id ? { connected: id } : undefined)} />
      <ConfirmDialog
        open={!!disconnecting} onOpenChange={(o) => { if (!o) setDisconnecting(null); }}
        title={`Disconnect ${disconnecting?.display_name ?? "account"}?`} confirmLabel="Disconnect" busy={disconnect.isPending}
        typeToConfirm={disconnecting?.display_name}
        description={
          <div className="space-y-1">
            <p>Botwok revokes its tokens where {platformMeta(disconnecting?.platform ?? "").label} supports it and stops publishing and analytics for this account. Already-published posts stay on the platform.</p>
            {disconnecting?.scheduled_posts_count ? <p className="font-medium">{disconnecting.scheduled_posts_count} scheduled posts use this account.</p> : null}
          </div>
        }
        onConfirm={() => disconnecting && disconnect.mutate({ id: disconnecting.id, force }, {
          onSuccess: () => { toast.success("Account disconnected"); setDisconnecting(null); },
          onError: (e) => {
            if (e instanceof ApiError && e.status === 409) setConflict(e.problem.detail ?? "This account has live scheduled posts.");
            else toast.error(errorMessage(e));
          },
        })}
      >
        {conflict && (
          <div className="space-y-2 rounded-md bg-warning/[0.08] p-3 text-sm text-warning">
            <p>{conflict}</p>
            <label className="flex items-center gap-2"><Checkbox checked={force} onCheckedChange={(c) => setForce(!!c)} /> Cancel those scheduled posts and disconnect anyway</label>
          </div>
        )}
      </ConfirmDialog>
    </div>
  );
}

"use client";
/** Account picker after the OAuth callback returned more than one connectable account (`?select=<token>`). */
import { useState } from "react";
import { toast } from "sonner";
import { Avatar, AvatarFallback, AvatarImage } from "@/components/ui/avatar";
import { Button } from "@/components/ui/button";
import { Dialog, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle } from "@/components/ui/dialog";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { ListSkeleton, QueryError } from "@/components/shared/async-states";
import { FormError } from "@/components/shared/form-errors";
import { PLATFORMS, platformMeta } from "@/lib/platforms";
import { cn } from "@/lib/utils";
import { useSelection, useSocialMutations } from "../hooks";

export function SelectionDialog({ token, platform: initialPlatform, onClose }: { token: string | null; platform: string | null; onClose: (connectedId?: string) => void }) {
  const [platform, setPlatform] = useState<string | null>(initialPlatform);
  const [picked, setPicked] = useState<string | null>(null);
  const [manualId, setManualId] = useState("");
  const list = useSelection(platform, token);
  const { select } = useSocialMutations();
  const accounts = list.data ?? [];
  const chosen = picked ?? (accounts.length === 1 && !accounts[0].already_connected ? accounts[0].external_id : null);
  const externalId = chosen ?? (manualId.trim() || null);

  return (
    <Dialog open={!!token} onOpenChange={(o) => { if (!o) onClose(); }}>
      <DialogContent>
        <DialogHeader>
          <DialogTitle>Choose the account to connect</DialogTitle>
          <DialogDescription>Your sign-in gave access to several {platform ? platformMeta(platform).label : ""} accounts. Pick the one this brand should use — nothing is connected until you confirm.</DialogDescription>
        </DialogHeader>
        {!platform ? (
          <div className="space-y-1">
            <Label htmlFor="sel-platform">Platform</Label>
            <Select onValueChange={setPlatform}>
              <SelectTrigger id="sel-platform" className="w-full"><SelectValue placeholder="Which platform did you just sign in to?" /></SelectTrigger>
              <SelectContent>{PLATFORMS.map((p) => <SelectItem key={p.id} value={p.id}>{p.label}</SelectItem>)}</SelectContent>
            </Select>
          </div>
        ) : list.isLoading ? <ListSkeleton rows={3} /> : list.error ? (
          <div className="space-y-3">
            <QueryError error={list.error} title="Couldn't load the account list" notAvailableText="The account list for this sign-in couldn't be loaded (it may have expired after 15 minutes). Start the connection again, or enter the account ID if you know it." />
            <div className="space-y-1"><Label htmlFor="sel-manual">Account ID</Label><Input id="sel-manual" value={manualId} onChange={(e) => setManualId(e.target.value)} /></div>
          </div>
        ) : !accounts.length ? (
          <p className="rounded-lg border border-dashed p-4 text-sm text-muted-foreground">No connectable accounts were found. For Instagram, convert to a Professional account and link it to a Facebook Page you manage, then start again.</p>
        ) : (
          <ul className="max-h-80 space-y-2 overflow-y-auto" role="radiogroup">
            {accounts.map((a) => {
              const disabled = !!a.already_connected || !!a.disabled_reason;
              return (
                <li key={a.external_id}>
                  <button type="button" role="radio" aria-checked={chosen === a.external_id} disabled={disabled} onClick={() => setPicked(a.external_id)}
                          className={cn("flex w-full items-center gap-3 rounded-lg border p-3 text-left text-sm", chosen === a.external_id && "border-primary bg-primary/5", disabled && "opacity-60")}>
                    <Avatar className="h-8 w-8"><AvatarImage src={a.avatar_url ?? undefined} alt="" /><AvatarFallback>{(a.display_name ?? a.handle ?? "?").slice(0, 2).toUpperCase()}</AvatarFallback></Avatar>
                    <span className="min-w-0 flex-1">
                      <span className="block truncate font-medium">{a.display_name ?? a.handle ?? a.external_id}</span>
                      <span className="block truncate text-xs text-muted-foreground">{[a.handle && `@${a.handle}`, a.account_type, a.linked_page && `Page: ${a.linked_page}`].filter(Boolean).join(" · ")}</span>
                      {a.already_connected && <span className="text-xs text-muted-foreground">Already connected</span>}
                      {a.disabled_reason && <span className="text-xs text-warning">{a.disabled_reason}</span>}
                    </span>
                  </button>
                </li>
              );
            })}
          </ul>
        )}
        <FormError error={select.error} />
        <DialogFooter>
          <Button variant="outline" onClick={() => onClose()}>Cancel</Button>
          <Button disabled={!platform || !token || !externalId || select.isPending}
                  onClick={() => platform && token && externalId && select.mutate({ platform, selection_token: token, external_id: externalId }, {
                    onSuccess: (acc) => { toast.success(`${acc?.display_name ?? "Account"} connected`); onClose(acc?.id); },
                  })}>
            {select.isPending ? "Connecting…" : "Connect account"}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}

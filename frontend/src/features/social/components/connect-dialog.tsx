"use client";
import { useState } from "react";
import { CheckCircle2, Info } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Dialog, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle } from "@/components/ui/dialog";
import { PlatformIcon } from "@/components/data/platform-icon";
import { FormError } from "@/components/data/form-errors";
import { NotAvailable, isNotAvailable } from "@/components/data/async-states";
import { platformMeta } from "@/lib/platforms";
import { cn } from "@/lib/utils";
import { useSocialMutations } from "../hooks";
import { REQUIREMENTS } from "../requirements";

export function ConnectDialog({ platform, brandId, reconnectAccountId, onOpenChange }: { platform: string | null; brandId: string | null; reconnectAccountId?: string; onOpenChange: (o: boolean) => void }) {
  const { connect } = useSocialMutations();
  const req = platform ? REQUIREMENTS[platform] : undefined;
  const [flavor, setFlavor] = useState<string | undefined>(undefined);
  const chosen = flavor ?? req?.flavors?.[0]?.id;
  const meta = platformMeta(platform ?? "");

  function go() {
    if (!platform) return;
    connect.mutate({ platform, brand_id: brandId, flavor: chosen, reconnect_account_id: reconnectAccountId }, {
      onSuccess: (d) => {
        try {
          const u = new URL(d.auth_url);
          if (u.protocol === "https:" || u.protocol === "http:") window.location.assign(u.toString());
        } catch { /* invalid URL from server — surfaced below */ }
      },
    });
  }

  return (
    <Dialog open={!!platform} onOpenChange={(o) => { if (!o) { connect.reset(); setFlavor(undefined); } onOpenChange(o); }}>
      <DialogContent className="sm:max-w-lg">
        <DialogHeader>
          <DialogTitle className="flex items-center gap-2"><PlatformIcon platform={platform ?? ""} size={22} /> {reconnectAccountId ? "Reconnect" : "Connect"} {meta.label}</DialogTitle>
          {req && <DialogDescription>{req.summary}</DialogDescription>}
        </DialogHeader>
        {req && (
          <div className="space-y-4 text-sm">
            <section>
              <h3 className="mb-1 font-medium">Before you continue</h3>
              <ul className="space-y-1">{req.checklist.map((c) => <li key={c} className="flex gap-2"><CheckCircle2 className="mt-0.5 h-4 w-4 shrink-0 text-muted-foreground" />{c}</li>)}</ul>
            </section>
            {req.flavors && (
              <fieldset className="space-y-2">
                <legend className="font-medium">Connection type</legend>
                {req.flavors.map((f) => (
                  <label key={f.id} className={cn("flex cursor-pointer gap-3 rounded-lg border p-3", chosen === f.id && "border-primary bg-primary/5")}>
                    <input type="radio" name="flavor" value={f.id} checked={chosen === f.id} onChange={() => setFlavor(f.id)} className="mt-1 accent-[var(--primary)]" />
                    <span><span className="font-medium">{f.label}</span><span className="block text-xs text-muted-foreground">{f.description}</span></span>
                  </label>
                ))}
              </fieldset>
            )}
            {req.notes?.map((n) => <p key={n} className="flex gap-2 rounded-md bg-amber-50 p-2 text-xs text-amber-900 dark:bg-amber-950/40 dark:text-amber-200"><Info className="mt-0.5 h-3.5 w-3.5 shrink-0" />{n}</p>)}
            <p className="text-xs text-muted-foreground">You&apos;ll be sent to {meta.label} to approve access. Botwok stores tokens encrypted and never shows them.</p>
          </div>
        )}
        {isNotAvailable(connect.error) ? <NotAvailable title={`${meta.label} isn't configured yet`} description="This install has no app credentials for this platform yet. An admin can add them under System settings." /> : <FormError error={connect.error} />}
        <DialogFooter>
          <Button variant="outline" onClick={() => onOpenChange(false)}>Cancel</Button>
          <Button onClick={go} disabled={!brandId || connect.isPending || connect.isSuccess}>{connect.isPending || connect.isSuccess ? "Redirecting…" : `Continue to ${meta.label}`}</Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}

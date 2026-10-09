"use client";
import { useState } from "react";
import { toast } from "sonner";
import { Button } from "@/components/ui/button";
import { Dialog, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle } from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { PlatformIcon } from "@/components/data/platform-icon";
import { AvailabilityBadge } from "@/components/data/availability-badge";
import { FieldError, FormError, problemFieldErrors } from "@/components/data/form-errors";
import { PLATFORMS } from "@/lib/platforms";
import { useSocialAccounts } from "@/features/social/hooks";
import { capabilityState, type SocialAccount } from "@/features/social/types";
import { useCompetitorMutations } from "../hooks";

/**
 * Projected availability while typing: `official_api` only when an active connected account on that platform
 * advertises a competitor-lookup capability; otherwise `not_collected`. The server's classify_availability() decides.
 */
function projected(platform: string, handle: string, accounts: SocialAccount[]): string | null {
  if (!handle.trim()) return null;
  const lookup = accounts.some((a) => a.platform === platform && a.status === "active" &&
    Object.entries(a.capabilities ?? {}).some(([k, v]) => /lookup|competitor/.test(k) && capabilityState(v) !== "unsupported"));
  return lookup ? "official_api" : "not_collected";
}

export function AddCompetitorDialog({ open, onOpenChange, brandId, onCreated }: {
  open: boolean; onOpenChange: (o: boolean) => void; brandId: string | null; onCreated?: (id: string) => void;
}) {
  const { create } = useCompetitorMutations();
  const accounts = useSocialAccounts(brandId);
  const [name, setName] = useState("");
  const [website, setWebsite] = useState("");
  const [frequency, setFrequency] = useState("weekly");
  const [handles, setHandles] = useState<Record<string, string>>({});
  const errors = problemFieldErrors(create.error);

  function reset() { setName(""); setWebsite(""); setFrequency("weekly"); setHandles({}); create.reset(); }

  function submit(e: React.FormEvent) {
    e.preventDefault();
    if (!brandId) { toast.error("Select a brand first"); return; }
    const profiles = Object.entries(handles).filter(([, v]) => v.trim()).map(([platform, v]) => (
      /^https?:\/\//.test(v.trim()) ? { platform, url: v.trim() } : { platform, handle: v.trim().replace(/^@/, "") }
    ));
    create.mutate(
      { brand_id: brandId, name: name.trim(), website: website.trim() || null, profiles, monitoring_frequency: frequency },
      { onSuccess: (c) => { toast.success(`${c?.name ?? name} added — syncing now`); reset(); onOpenChange(false); if (c?.id) onCreated?.(c.id); } },
    );
  }

  return (
    <Dialog open={open} onOpenChange={(o) => { if (!o) reset(); onOpenChange(o); }}>
      <DialogContent className="max-h-[90vh] overflow-y-auto sm:max-w-lg">
        <DialogHeader>
          <DialogTitle>Add competitor</DialogTitle>
          <DialogDescription>Botwok only uses official APIs, the competitor&apos;s public website and search. Platforms without a permitted source are stored as handles only.</DialogDescription>
        </DialogHeader>
        <form id="add-competitor" onSubmit={submit} className="space-y-4">
          <div className="grid gap-3 sm:grid-cols-2">
            <div className="space-y-1">
              <Label htmlFor="c-name">Name</Label>
              <Input id="c-name" value={name} onChange={(e) => setName(e.target.value)} required aria-invalid={!!errors.name} />
              <FieldError errors={errors} name="name" />
            </div>
            <div className="space-y-1">
              <Label htmlFor="c-web">Website</Label>
              <Input id="c-web" value={website} onChange={(e) => setWebsite(e.target.value)} placeholder="https://example.com" aria-invalid={!!errors.website} />
              <FieldError errors={errors} name="website" />
            </div>
          </div>
          <div className="space-y-1">
            <Label htmlFor="c-freq">Sync frequency</Label>
            <Select value={frequency} onValueChange={setFrequency}>
              <SelectTrigger id="c-freq" className="w-full"><SelectValue /></SelectTrigger>
              <SelectContent><SelectItem value="daily">Daily</SelectItem><SelectItem value="weekly">Weekly</SelectItem><SelectItem value="monthly">Monthly</SelectItem></SelectContent>
            </Select>
          </div>
          <fieldset className="space-y-2">
            <legend className="text-sm font-medium">Handles or profile URLs</legend>
            {PLATFORMS.map((p) => {
              const v = handles[p.id] ?? "";
              const proj = projected(p.id, v, accounts.data ?? []);
              return (
                <div key={p.id} className="flex items-center gap-2">
                  <PlatformIcon platform={p.id} size={22} />
                  <Label htmlFor={`h-${p.id}`} className="sr-only">{p.label} handle</Label>
                  <Input id={`h-${p.id}`} value={v} onChange={(e) => setHandles((h) => ({ ...h, [p.id]: e.target.value }))} placeholder={`${p.label} @handle or URL`} className="h-8" />
                  <span className="hidden w-32 shrink-0 sm:block">{proj && <AvailabilityBadge availability={proj} short />}</span>
                </div>
              );
            })}
            <FieldError errors={errors} name="profiles" />
            <p className="text-xs text-muted-foreground">Badges are a preview; the final data source is decided when the profile is checked.</p>
          </fieldset>
          <FormError error={Object.keys(errors).length ? null : create.error} />
        </form>
        <DialogFooter>
          <Button variant="outline" onClick={() => onOpenChange(false)}>Cancel</Button>
          <Button type="submit" form="add-competitor" disabled={!name.trim() || create.isPending}>{create.isPending ? "Adding…" : "Add & sync"}</Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}

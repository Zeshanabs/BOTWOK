"use client";
import { useState } from "react";
import { toast } from "sonner";
import { KeyRound, RefreshCw, TriangleAlert } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Dialog, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle } from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { Switch } from "@/components/ui/switch";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { StatusChip } from "@/components/shared/status-chip";
import { FormError } from "@/components/shared/form-errors";
import { ListSkeleton, QueryError, errorMessage } from "@/components/shared/async-states";
import { fmtRelative } from "@/lib/formatters";
import { useAgents, useOllama, useProviderActions, useSaveAiSettings } from "../hooks";
import { PROVIDERS, TIERS, fallbackText, type AiSettings, type Route, type Tier } from "../types";

const NONE = "__none";

function providerStatus(s: AiSettings["providers"], name: string): string {
  const p = s?.[name];
  if (!p) return "not_set";
  if (p.status) return p.status === "valid" ? "active" : p.status;
  return p.configured || p.last4 ? "active" : "not_set";
}

function KeyDialog({ provider, onClose }: { provider: string | null; onClose: () => void }) {
  const { setKey } = useProviderActions();
  const [key, setKeyValue] = useState("");
  const label = PROVIDERS.find((p) => p.name === provider)?.label ?? provider;
  return (
    <Dialog open={!!provider} onOpenChange={(o) => { if (!o) { setKeyValue(""); setKey.reset(); onClose(); } }}>
      <DialogContent>
        <DialogHeader>
          <DialogTitle>API key · {label}</DialogTitle>
          <DialogDescription>Keys are write-only: stored encrypted on this machine and never shown again (only the last 4 characters).</DialogDescription>
        </DialogHeader>
        <form id="key-form" onSubmit={(e) => { e.preventDefault(); if (!provider || !key.trim()) return; setKey.mutate({ provider, key: key.trim() }, { onSuccess: () => { toast.success(`${label} key saved`); setKeyValue(""); onClose(); } }); }} className="space-y-2">
          <Label htmlFor="api-key">Key</Label>
          <Input id="api-key" type="password" autoComplete="off" value={key} onChange={(e) => setKeyValue(e.target.value)} />
          <FormError error={setKey.error} />
        </form>
        <DialogFooter><Button variant="outline" onClick={onClose}>Cancel</Button><Button type="submit" form="key-form" disabled={!key.trim() || setKey.isPending}>{setKey.isPending ? "Saving…" : "Save key"}</Button></DialogFooter>
      </DialogContent>
    </Dialog>
  );
}

export function ProvidersTab({ settings, readOnly }: { settings: AiSettings; readOnly: boolean }) {
  const save = useSaveAiSettings();
  const { test } = useProviderActions();
  const agents = useAgents();
  const ollama = useOllama();
  const [keyFor, setKeyFor] = useState<string | null>(null);
  const r = settings.routing ?? {};
  const [routes, setRoutes] = useState<Record<string, { primary: string; fallback: string }>>(() =>
    Object.fromEntries([...TIERS, "embeddings"].map((t) => { const x = (r as Record<string, Route | undefined>)[t]; return [t, { primary: x?.primary ?? x?.model ?? "", fallback: fallbackText(x?.fallback) }]; })));
  const [perAgent, setPerAgent] = useState<Record<string, string>>(() => Object.fromEntries(Object.entries(r.per_agent ?? {}).map(([k, v]) => [k, v?.primary ?? v?.model ?? ""])));
  const [fallbackOn, setFallbackOn] = useState<boolean>(r.fallback_on_error !== false);
  const [image, setImage] = useState(settings.media?.image_provider ?? NONE);
  const [video, setVideo] = useState(settings.media?.video_provider ?? NONE);
  const [search, setSearch] = useState(settings.search?.provider ?? settings.search?.order?.[0] ?? NONE);
  const writerModel = perAgent.writer || routes.powerful?.primary;
  const criticModel = perAgent.critic || routes.balanced?.primary;
  const sameFamily = !!writerModel && !!criticModel && writerModel.split("/")[0] === criticModel.split("/")[0];

  function onSave() {
    const routing: NonNullable<AiSettings["routing"]> = { ...r, fallback_on_error: fallbackOn, per_agent: {} };
    for (const t of [...TIERS, "embeddings"]) {
      const v = routes[t];
      const fb = v.fallback.split(",").map((s) => s.trim()).filter(Boolean);
      (routing as Record<string, unknown>)[t] = { ...((r as Record<string, unknown>)[t] as object), primary: v.primary.trim() || null, fallback: fb.length > 1 ? fb : fb[0] ?? null };
    }
    for (const [k, v] of Object.entries(perAgent)) if (v.trim()) routing.per_agent![k] = { primary: v.trim() };
    save.mutate(
      { routing, media: { ...(settings.media ?? {}), image_provider: image === NONE ? null : image, video_provider: video === NONE ? null : video }, search: { ...(settings.search ?? {}), provider: search === NONE ? null : search } },
      { onSuccess: () => toast.success("AI routing saved"), onError: (e) => toast.error(errorMessage(e)) },
    );
  }

  return (
    <div className="space-y-6">
      <Card>
        <CardHeader><CardTitle className="text-sm">Provider keys</CardTitle><CardDescription>AI features stay off until a provider key or a local model is configured.</CardDescription></CardHeader>
        <CardContent className="overflow-x-auto">
          <Table>
            <TableHeader><TableRow><TableHead>Provider</TableHead><TableHead>Status</TableHead><TableHead>Key</TableHead><TableHead>Verified</TableHead><TableHead /></TableRow></TableHeader>
            <TableBody>
              {PROVIDERS.map((p) => {
                const st = providerStatus(settings.providers, p.name);
                const info = settings.providers?.[p.name];
                return (
                  <TableRow key={p.name}>
                    <TableCell className="font-medium">{p.label}</TableCell>
                    <TableCell><StatusChip status={st} />{info?.error && <p className="mt-1 text-xs text-destructive">{info.error}</p>}</TableCell>
                    <TableCell className="font-mono text-xs">{info?.last4 ? `••••${info.last4}` : "—"}</TableCell>
                    <TableCell className="text-xs text-muted-foreground">{info?.last_verified_at ? fmtRelative(info.last_verified_at) : "—"}</TableCell>
                    <TableCell className="whitespace-nowrap text-right">
                      {!readOnly && <Button size="xs" variant="outline" onClick={() => setKeyFor(p.name)}><KeyRound className="h-3 w-3" /> {st === "not_set" ? "Add key" : "Rotate"}</Button>}
                      {!readOnly && st !== "not_set" && (
                        <Button size="xs" variant="ghost" disabled={test.isPending && test.variables === p.name}
                                onClick={() => test.mutate(p.name, { onSuccess: (d) => (d?.ok === false || d?.error ? toast.error(`${p.label}: ${d?.error ?? "test failed"}`) : toast.success(`${p.label} OK${d?.latency_ms ? ` · ${d.latency_ms} ms` : ""}`)), onError: (e) => toast.error(errorMessage(e)) })}>Test</Button>
                      )}
                    </TableCell>
                  </TableRow>
                );
              })}
            </TableBody>
          </Table>
        </CardContent>
      </Card>

      <Card>
        <CardHeader className="flex flex-row items-start justify-between">
          <div><CardTitle className="text-sm">Ollama (local models)</CardTitle><CardDescription>Detected from this browser at localhost:11434.</CardDescription></div>
          <Button size="icon-sm" variant="ghost" aria-label="Re-detect" onClick={() => ollama.refetch()}><RefreshCw className={ollama.isFetching ? "h-4 w-4 animate-spin" : "h-4 w-4"} /></Button>
        </CardHeader>
        <CardContent className="text-sm">
          {ollama.isLoading ? "Checking…" : ollama.data ? (
            <div><p className="text-success">● Running · {ollama.data.length} model{ollama.data.length === 1 ? "" : "s"}</p>
              {ollama.data.length > 0 && <p className="mt-1 font-mono text-xs text-muted-foreground">{ollama.data.join(", ")}</p>}
              <p className="mt-1 text-xs text-muted-foreground">Use them in routing as <span className="font-mono">ollama/&lt;model&gt;</span>.</p></div>
          ) : <p className="text-muted-foreground">○ Not detected (not running, or the browser blocked the request). The backend may still reach it.</p>}
        </CardContent>
      </Card>

      <Card>
        <CardHeader><CardTitle className="text-sm">Model routing per tier</CardTitle><CardDescription>Format <span className="font-mono">provider/model</span>. Fallbacks are used on provider errors or 429s (comma-separated).</CardDescription></CardHeader>
        <CardContent className="space-y-3">
          <div className="grid gap-2 text-sm">
            {[...TIERS, "embeddings"].map((t) => (
              <div key={t} className="grid items-center gap-2 sm:grid-cols-[7rem_1fr_1fr]">
                <span className="font-medium capitalize">{t}</span>
                <Input aria-label={`${t} primary model`} placeholder="primary, e.g. anthropic/claude-…" value={routes[t]?.primary ?? ""} disabled={readOnly} onChange={(e) => setRoutes((s) => ({ ...s, [t]: { ...s[t], primary: e.target.value } }))} />
                <Input aria-label={`${t} fallback model`} placeholder="fallback" value={routes[t]?.fallback ?? ""} disabled={readOnly} onChange={(e) => setRoutes((s) => ({ ...s, [t]: { ...s[t], fallback: e.target.value } }))} />
              </div>
            ))}
          </div>
          <label className="flex items-center gap-2 text-sm"><Switch checked={fallbackOn} onCheckedChange={setFallbackOn} disabled={readOnly} /> On provider error, fall back to the next model</label>
        </CardContent>
      </Card>

      <Card>
        <CardHeader><CardTitle className="text-sm">Per-agent overrides</CardTitle><CardDescription>Leave blank to use the agent&apos;s tier.</CardDescription></CardHeader>
        <CardContent>
          {sameFamily && <p className="mb-3 flex items-center gap-1 text-xs text-warning"><TriangleAlert className="h-3 w-3" /> The critic should use a different model family than the writer.</p>}
          {agents.isLoading ? <ListSkeleton rows={6} rowClassName="h-9" /> : agents.error ? <QueryError error={agents.error} onRetry={() => agents.refetch()} title="Couldn't load agents" /> : (
            <div className="grid gap-2 text-sm">
              {(agents.data ?? []).map((a) => (
                <div key={a.id} className="grid items-center gap-2 sm:grid-cols-[10rem_6rem_1fr]">
                  <span className="font-mono text-xs">{a.id}</span>
                  <span className="text-xs text-muted-foreground">{a.tier}</span>
                  <Input aria-label={`${a.id} model override`} className="h-8" placeholder={a.resolved_model ?? (routes[a.tier as Tier]?.primary || "tier default")} value={perAgent[a.id] ?? ""} disabled={readOnly}
                         onChange={(e) => setPerAgent((s) => ({ ...s, [a.id]: e.target.value }))} />
                </div>
              ))}
            </div>
          )}
        </CardContent>
      </Card>

      <Card>
        <CardHeader><CardTitle className="text-sm">Media & search providers</CardTitle></CardHeader>
        <CardContent className="grid gap-4 sm:grid-cols-3">
          {([["Image generation", image, setImage, ["openai", "google", "stability"]], ["Video generation", video, setVideo, ["google", "runway"]], ["Web search", search, setSearch, ["tavily", "brave", "exa"]]] as const).map(([label, val, set, opts]) => (
            <div key={label} className="space-y-1">
              <Label>{label}</Label>
              <Select value={val} onValueChange={set} disabled={readOnly}>
                <SelectTrigger className="w-full" aria-label={label}><SelectValue /></SelectTrigger>
                <SelectContent><SelectItem value={NONE}>None</SelectItem>{opts.map((o) => <SelectItem key={o} value={o}>{o}</SelectItem>)}</SelectContent>
              </Select>
            </div>
          ))}
        </CardContent>
      </Card>

      {!readOnly && <div className="flex justify-end"><Button onClick={onSave} disabled={save.isPending}>{save.isPending ? "Saving…" : "Save routing & providers"}</Button></div>}
      <FormError error={save.error} />
      <KeyDialog provider={keyFor} onClose={() => setKeyFor(null)} />
    </div>
  );
}

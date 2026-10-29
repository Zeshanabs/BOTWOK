"use client";
/** System › API keys, Export & backup, Notifications inbox, Danger zone. */
import { useState } from "react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { toast } from "sonner";
import { Bell, Copy, Download, KeyRound, Plus } from "lucide-react";
import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert";
import { Button } from "@/components/ui/button";
import { Checkbox } from "@/components/ui/checkbox";
import { Dialog, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle } from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { EmptyState } from "@/components/shared/empty-state";
import { StatusChip } from "@/components/shared/status-chip";
import { ConfirmDialog } from "@/components/shared/confirm-dialog";
import { FieldError, FormError, problemFieldErrors } from "@/components/shared/form-errors";
import { ListSkeleton, QueryError, errorMessage, isNotAvailable } from "@/components/shared/async-states";
import { fmtDate, fmtRelative } from "@/lib/formatters";
import { useCan } from "@/lib/permissions";
import { cn } from "@/lib/utils";
import { useSession } from "@/stores/session";
import { systemApi, type ApiKey, type ApiKeyCreated } from "../api";
import { useApiKeyMutations, useApiKeys, useExportStatus, useNotificationMutations, useNotifications } from "../hooks";

const SCOPES = ["content:read", "content:write", "research:run", "automations:run", "analytics:read", "webhooks:receive"];

export function ApiKeysSection() {
  const can = useCan();
  const keys = useApiKeys(can.manage);
  const { create, revoke } = useApiKeyMutations();
  const [open, setOpen] = useState(false);
  const [name, setName] = useState("");
  const [scopes, setScopes] = useState<string[]>(["content:read"]);
  const [created, setCreated] = useState<ApiKeyCreated | null>(null);
  const [revoking, setRevoking] = useState<ApiKey | null>(null);
  const errors = problemFieldErrors(create.error);
  if (!can.manage) return <p className="text-sm text-muted-foreground">Only owners and admins can manage API keys.</p>;

  return (
    <div className="space-y-4">
      <div className="flex items-center justify-between gap-2">
        <p className="text-sm text-muted-foreground">Keys let automations and scripts call the Botwok API (<span className="font-mono">X-API-Key</span>). Secrets are shown once.</p>
        <Button size="sm" onClick={() => { setOpen(true); setCreated(null); }}><Plus className="h-3 w-3" /> New key</Button>
      </div>
      {keys.isLoading ? <ListSkeleton rows={3} /> : keys.error ? <QueryError error={keys.error} onRetry={() => keys.refetch()} title="Couldn't load API keys" /> : !(keys.data ?? []).length ? (
        <EmptyState icon={KeyRound} title="No API keys" description="Create one for an automation or integration." />
      ) : (
        <div className="overflow-x-auto rounded-lg border">
          <Table>
            <TableHeader><TableRow><TableHead>Name</TableHead><TableHead>Prefix</TableHead><TableHead>Scopes</TableHead><TableHead>Last used</TableHead><TableHead>Created</TableHead><TableHead /></TableRow></TableHeader>
            <TableBody>
              {(keys.data ?? []).map((k) => (
                <TableRow key={k.id} className={cn(k.revoked_at && "opacity-60")}>
                  <TableCell className="font-medium">{k.name}</TableCell>
                  <TableCell className="font-mono text-xs">{k.key_prefix}…</TableCell>
                  <TableCell className="text-xs">{(k.scopes ?? []).join(", ") || "—"}</TableCell>
                  <TableCell className="text-xs text-muted-foreground">{k.last_used_at ? fmtRelative(k.last_used_at) : "never"}</TableCell>
                  <TableCell className="text-xs text-muted-foreground">{fmtDate(k.created_at)}</TableCell>
                  <TableCell className="text-right">{k.revoked_at ? <StatusChip status="revoked" /> : <Button size="xs" variant="ghost" className="text-destructive" onClick={() => setRevoking(k)}>Revoke</Button>}</TableCell>
                </TableRow>
              ))}
            </TableBody>
          </Table>
        </div>
      )}
      <Dialog open={open} onOpenChange={(o) => { if (!o) { setCreated(null); setName(""); create.reset(); } setOpen(o); }}>
        <DialogContent>
          <DialogHeader><DialogTitle>{created ? "Copy your new key" : "New API key"}</DialogTitle>
            <DialogDescription>{created ? "This is the only time the full key is shown. Store it somewhere safe." : "Grant only the scopes the integration needs."}</DialogDescription></DialogHeader>
          {created ? (
            <div className="flex items-center gap-2">
              <Input readOnly value={created.secret} className="font-mono text-xs" aria-label="API key secret" onFocus={(e) => e.currentTarget.select()} />
              <Button size="icon" variant="outline" aria-label="Copy key" onClick={() => navigator.clipboard?.writeText(created.secret).then(() => toast.success("Key copied"), () => undefined)}><Copy className="h-4 w-4" /></Button>
            </div>
          ) : (
            <form id="key-create" className="space-y-3" onSubmit={(e) => { e.preventDefault(); create.mutate({ name: name.trim(), scopes }, { onSuccess: (k) => setCreated(k) }); }}>
              <div className="space-y-1"><Label htmlFor="key-name">Name</Label><Input id="key-name" value={name} onChange={(e) => setName(e.target.value)} placeholder="e.g. n8n automation" aria-invalid={!!errors.name} /><FieldError errors={errors} name="name" /></div>
              <fieldset className="space-y-2"><legend className="text-sm font-medium">Scopes</legend>
                <div className="grid grid-cols-2 gap-2">{SCOPES.map((s) => (
                  <label key={s} className="flex items-center gap-2 font-mono text-xs"><Checkbox checked={scopes.includes(s)} onCheckedChange={(c) => setScopes((x) => (c ? [...x, s] : x.filter((y) => y !== s)))} />{s}</label>
                ))}</div>
              </fieldset>
              <FormError error={Object.keys(errors).length ? null : create.error} />
            </form>
          )}
          <DialogFooter>
            <Button variant="outline" onClick={() => setOpen(false)}>{created ? "Done" : "Cancel"}</Button>
            {!created && <Button type="submit" form="key-create" disabled={!name.trim() || create.isPending}>{create.isPending ? "Creating…" : "Create key"}</Button>}
          </DialogFooter>
        </DialogContent>
      </Dialog>
      <ConfirmDialog open={!!revoking} onOpenChange={(o) => { if (!o) setRevoking(null); }} title={`Revoke “${revoking?.name ?? ""}”?`} description="Integrations using this key stop working immediately." confirmLabel="Revoke" busy={revoke.isPending}
                     onConfirm={() => revoking && revoke.mutate(revoking.id, { onSuccess: () => { toast.success("Key revoked"); setRevoking(null); }, onError: (e) => toast.error(errorMessage(e)) })} />
    </div>
  );
}

export function ExportSection() {
  const can = useCan();
  const [jobId, setJobId] = useState<string | null>(null);
  const [startErr, setStartErr] = useState<unknown>(null);
  const [busy, setBusy] = useState(false);
  const status = useExportStatus(jobId);
  const url = status.data?.download_url ?? status.data?.url;
  async function start() {
    setBusy(true); setStartErr(null);
    try { const d = await systemApi.startExport(); setJobId(d.id); toast.success("Export started"); } catch (e) { setStartErr(e); } finally { setBusy(false); }
  }
  return (
    <div className="space-y-3 text-sm">
      <p className="text-muted-foreground">Exports all workspace data as JSON plus a media archive. Published platform posts are not affected.</p>
      {can.manage ? <Button onClick={start} disabled={busy || (!!jobId && !url && !status.error && status.data?.status !== "failed")}><Download className="h-4 w-4" /> {busy ? "Starting…" : "Export workspace"}</Button> : <p className="text-muted-foreground">Only owners and admins can export.</p>}
      {isNotAvailable(startErr) ? <p className="text-muted-foreground">Export isn&apos;t available on this install yet.</p> : <FormError error={startErr} />}
      {jobId && (
        <div className="flex flex-wrap items-center gap-2 rounded-md border p-3">
          <span>Export</span><StatusChip status={status.data?.status ?? "queued"} />
          {status.data?.error && <span className="text-xs text-destructive">{status.data.error}</span>}
          {url && <a href={url} className="text-primary hover:underline" download>Download</a>}
          {status.error != null && !isNotAvailable(status.error) && <span className="text-xs text-destructive">{errorMessage(status.error)}</span>}
          {isNotAvailable(status.error) && <span className="text-xs text-muted-foreground">Status tracking isn&apos;t available; you&apos;ll get a notification when it&apos;s ready.</span>}
        </div>
      )}
    </div>
  );
}

export function NotificationsSection() {
  const q = useNotifications();
  const { read, readAll } = useNotificationMutations();
  const slug = useSession((s) => s.workspaceSlug);
  if (q.isLoading) return <ListSkeleton rows={5} />;
  if (q.error) return <QueryError error={q.error} onRetry={() => q.refetch()} title="Couldn't load notifications" />;
  const items = q.data?.items ?? [];
  const unread = q.data?.unread ?? items.filter((n) => !n.read_at).length;
  const sev: Record<string, string> = { error: "bg-destructive", warning: "bg-warning", success: "bg-success", info: "bg-info" };
  return (
    <div className="space-y-3">
      <div className="flex items-center justify-between">
        <p className="text-sm text-muted-foreground">{unread} unread</p>
        <Button size="sm" variant="outline" disabled={!unread || readAll.isPending} onClick={() => readAll.mutate(undefined, { onError: (e) => toast.error(errorMessage(e)) })}>Mark all read</Button>
      </div>
      {!items.length ? <EmptyState icon={Bell} title="You're all caught up" description="Approvals, failed posts, expiring tokens and budget alerts show up here." /> : (
        <ul className="divide-y rounded-lg border">
          {items.map((n) => {
            const href = n.link ? (n.link.startsWith("/") && !n.link.startsWith("/w/") ? `/w/${slug}${n.link}` : n.link) : null;
            return (
              <li key={n.id} className={cn("flex items-start gap-3 p-3 text-sm", !n.read_at && "bg-accent/40")}>
                <span className={cn("mt-1.5 h-2 w-2 shrink-0 rounded-full", n.read_at ? "bg-transparent" : sev[n.severity ?? "info"] ?? "bg-info")} aria-label={n.read_at ? "Read" : "Unread"} />
                <div className="min-w-0 flex-1">
                  <p className="font-medium">{href ? <Link href={href} className="hover:underline" onClick={() => !n.read_at && read.mutate(n.id)}>{n.title}</Link> : n.title}</p>
                  {n.body && <p className="text-muted-foreground">{n.body}</p>}
                  <p className="text-xs text-muted-foreground">{n.kind.replace(/_/g, " ").toLowerCase()} · {fmtRelative(n.created_at)}</p>
                </div>
                {!n.read_at && <Button size="xs" variant="ghost" onClick={() => read.mutate(n.id)}>Mark read</Button>}
              </li>
            );
          })}
        </ul>
      )}
    </div>
  );
}

export function DangerZone() {
  const router = useRouter();
  const can = useCan();
  const ws = useSession((s) => s.workspaceId);
  const memberships = useSession((s) => s.memberships);
  const name = memberships.find((m) => m.workspace.id === ws)?.workspace.name ?? "";
  const [open, setOpen] = useState(false);
  const [busy, setBusy] = useState(false);
  return (
    <div className="space-y-3">
      <Alert variant="destructive">
        <AlertTitle>Delete workspace</AlertTitle>
        <AlertDescription>
          <p>Removes all brands, content, research, schedules and connected accounts from this install. Posts already published on platforms remain there.</p>
          {can.owner ? <Button variant="destructive" size="sm" className="mt-2" onClick={() => setOpen(true)}>Delete workspace…</Button> : <p className="mt-1">Only the owner can delete the workspace.</p>}
        </AlertDescription>
      </Alert>
      <ConfirmDialog open={open} onOpenChange={setOpen} title={`Delete ${name}?`} typeToConfirm={name} confirmLabel="Delete forever" busy={busy}
                     description="This cannot be undone. Export first if you need a backup."
                     onConfirm={async () => {
                       if (!ws) return;
                       setBusy(true);
                       try { await systemApi.deleteWorkspace(ws); toast.success("Workspace deleted"); router.replace("/"); } catch (e) { toast.error(errorMessage(e)); } finally { setBusy(false); }
                     }} />
    </div>
  );
}

"use client";
import { useState } from "react";
import { toast } from "sonner";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Skeleton } from "@/components/ui/skeleton";
import { Switch } from "@/components/ui/switch";
import { FieldError, FormError, problemFieldErrors } from "@/components/data/form-errors";
import { QueryError, errorMessage } from "@/components/data/async-states";
import { useCan } from "@/lib/permissions";
import { useSession } from "@/stores/session";
import { TimezoneInput } from "@/features/brand/components/timezone-input";
import type { WorkspaceSettings } from "../api";
import { useSaveWorkspaceSettings, useWorkspaceSettings } from "../hooks";

function Form({ ws, readOnly }: { ws: WorkspaceSettings; readOnly: boolean }) {
  const save = useSaveWorkspaceSettings();
  const ch = ws.notification_channels ?? {};
  const [name, setName] = useState(ws.name);
  const [timezone, setTimezone] = useState(ws.timezone ?? "UTC");
  const [retention, setRetention] = useState(ws.retention_days != null ? String(ws.retention_days) : "");
  const [inApp, setInApp] = useState(ch.in_app ?? true);
  const [email, setEmail] = useState(ch.email ?? false);
  const [slack, setSlack] = useState("");
  const [webhook, setWebhook] = useState("");
  const [clearSlack, setClearSlack] = useState(false);
  const [clearWebhook, setClearWebhook] = useState(false);
  const errors = problemFieldErrors(save.error);

  function onSave() {
    const channels: { in_app: boolean; email: boolean; slack_webhook_url?: string; webhook_url?: string } = { in_app: inApp, email };
    if (slack.trim() || clearSlack) channels.slack_webhook_url = clearSlack ? "" : slack.trim();
    if (webhook.trim() || clearWebhook) channels.webhook_url = clearWebhook ? "" : webhook.trim();
    save.mutate({ name: name.trim(), timezone: timezone.trim(), retention_days: retention ? Number(retention) : null, notification_channels: channels }, {
      onSuccess: () => { toast.success("Workspace settings saved"); setSlack(""); setWebhook(""); setClearSlack(false); setClearWebhook(false); },
      onError: (e) => toast.error(errorMessage(e)),
    });
  }

  return (
    <div className="space-y-6">
      <section className="grid gap-4 sm:grid-cols-2">
        <div className="space-y-1"><Label htmlFor="ws-name">Workspace name</Label><Input id="ws-name" value={name} onChange={(e) => setName(e.target.value)} disabled={readOnly} aria-invalid={!!errors.name} /><FieldError errors={errors} name="name" /></div>
        <div className="space-y-1"><Label htmlFor="ws-slug">URL</Label><Input id="ws-slug" value={`/w/${ws.slug}`} disabled readOnly className="font-mono" /></div>
        <div className="space-y-1"><Label htmlFor="ws-tz">Timezone</Label><TimezoneInput id="ws-tz" value={timezone} onChange={setTimezone} disabled={readOnly} invalid={!!errors.timezone} /><FieldError errors={errors} name="timezone" /></div>
        <div className="space-y-1">
          <Label htmlFor="ws-ret">Data retention (days)</Label>
          <Input id="ws-ret" inputMode="numeric" value={retention} onChange={(e) => setRetention(e.target.value.replace(/[^0-9]/g, ""))} disabled={readOnly} placeholder="keep forever" />
          <p className="text-xs text-muted-foreground">Applies to research documents, AI run logs and tool outputs.</p>
          <FieldError errors={errors} name="retention_days" />
        </div>
      </section>
      <section className="space-y-3">
        <h3 className="text-sm font-semibold">Notification channels</h3>
        <label className="flex items-center gap-2 text-sm"><Switch checked={inApp} onCheckedChange={setInApp} disabled={readOnly} /> In-app</label>
        <label className="flex items-center gap-2 text-sm"><Switch checked={email} onCheckedChange={setEmail} disabled={readOnly} /> Email (requires SMTP on this install)</label>
        <div className="grid gap-4 sm:grid-cols-2">
          <div className="space-y-1">
            <Label htmlFor="ws-slack">Slack incoming webhook</Label>
            <Input id="ws-slack" type="url" value={slack} onChange={(e) => setSlack(e.target.value)} disabled={readOnly || clearSlack} placeholder={ch.slack_configured ? `configured ${ch.slack_webhook_hint ?? ""} — paste to replace` : "https://hooks.slack.com/…"} />
            {ch.slack_configured && !readOnly && <label className="flex items-center gap-2 text-xs"><Switch checked={clearSlack} onCheckedChange={setClearSlack} /> Remove Slack webhook</label>}
            <FieldError errors={errors} name="slack_webhook_url" />
          </div>
          <div className="space-y-1">
            <Label htmlFor="ws-hook">Outgoing webhook</Label>
            <Input id="ws-hook" type="url" value={webhook} onChange={(e) => setWebhook(e.target.value)} disabled={readOnly || clearWebhook} placeholder={ch.webhook_configured ? `configured ${ch.webhook_url_hint ?? ""} — paste to replace` : "https://example.com/botwok"} />
            {ch.webhook_configured && !readOnly && <label className="flex items-center gap-2 text-xs"><Switch checked={clearWebhook} onCheckedChange={setClearWebhook} /> Remove webhook</label>}
            <FieldError errors={errors} name="webhook_url" />
          </div>
        </div>
      </section>
      <FormError error={Object.keys(errors).length ? null : save.error} />
      {!readOnly && <div className="flex justify-end"><Button onClick={onSave} disabled={save.isPending || !name.trim()}>{save.isPending ? "Saving…" : "Save"}</Button></div>}
    </div>
  );
}

export function GeneralSection() {
  const can = useCan();
  const q = useWorkspaceSettings();
  const wsId = useSession((s) => s.workspaceId);
  if (q.isLoading) return <div className="space-y-3"><Skeleton className="h-9 w-full" /><Skeleton className="h-9 w-full" /><Skeleton className="h-40 w-full" /></div>;
  if (q.error || !q.data) return <QueryError error={q.error} onRetry={() => q.refetch()} title="Couldn't load workspace settings" />;
  return <Form key={wsId ?? "ws"} ws={q.data} readOnly={!can.manage} />;
}

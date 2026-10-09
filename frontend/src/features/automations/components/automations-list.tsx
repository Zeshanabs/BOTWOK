"use client";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { LayoutTemplate, Play, Plus, Workflow } from "lucide-react";
import { toast } from "sonner";
import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert";
import { Button } from "@/components/ui/button";
import { Skeleton } from "@/components/ui/skeleton";
import { Switch } from "@/components/ui/switch";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { EmptyState } from "@/components/data/empty-state";
import { PageHeader } from "@/components/data/page-header";
import { StatusChip } from "@/components/data/status-chip";
import { QueryError } from "@/features/common/components/query-state";
import { TaskGlyph } from "@/features/common/components/run-card";
import { useActiveBrand, usePermissions, useWorkspacePath } from "@/features/common/hooks";
import { errorMessage, fmtPct, isNotAvailable, relTime, toItems } from "@/features/common/utils";
import { automationsApi, newsToLinkedInTemplate, type Automation } from "../api";

const ownerName = (o: Automation["owner"]) => (o == null ? "—" : typeof o === "string" ? o : o.name ?? o.full_name ?? "—");

/** Automations list (doc 24 §19): status, last/next run, success rate, enable/disable, run now, templates. */
export function AutomationsList() {
  const qc = useQueryClient();
  const router = useRouter();
  const ws = useWorkspacePath();
  const { brandId } = useActiveBrand();
  const { canManage, canCreate } = usePermissions();
  const list = useQuery({ queryKey: ["automations", "list"], queryFn: () => automationsApi.list(), retry: false });
  const missing = isNotAvailable(list.error);
  const items = toItems(list.data);
  const create = useMutation({
    mutationFn: async (template: boolean) => {
      if (template) {
        // Prefer the backend template (validated node configs). The template contains a Schedule node, which the backend
        // only allows when autonomous actions are enabled; the Approve node before it still gates every schedule.
        try {
          return await automationsApi.fromTemplate("industry_news_linkedin", { brand_id: brandId, autonomous_actions_enabled: true });
        } catch (e) {
          if (!isNotAvailable(e)) throw e;
        }
      }
      const t = template ? newsToLinkedInTemplate() : { name: "Untitled automation", nodes: [], edges: [] };
      return automationsApi.create({ name: t.name, brand_id: brandId, nodes: t.nodes, edges: t.edges });
    },
    onSuccess: (a) => { void qc.invalidateQueries({ queryKey: ["automations"] }); router.push(ws(`automations/${a.id}`)); },
    onError: (e, template) => {
      if (isNotAvailable(e)) router.push(ws(`automations/new${template ? "?template=news-linkedin" : ""}`));
      else toast.error(errorMessage(e));
    },
  });
  const toggle = useMutation({
    mutationFn: (a: Automation) => (a.status === "active" ? automationsApi.disable(a.id) : automationsApi.enable(a.id)),
    onMutate: async (a) => {
      await qc.cancelQueries({ queryKey: ["automations", "list"] });
      const prev = qc.getQueryData(["automations", "list"]);
      qc.setQueryData(["automations", "list"], (old: typeof list.data) => {
        const flip = (x: Automation) => (x.id === a.id ? { ...x, status: a.status === "active" ? "paused" : "active" } : x);
        return Array.isArray(old) ? old.map(flip) : old ? { ...old, items: old.items.map(flip) } : old;
      });
      return { prev };
    },
    onError: (e, a, ctx) => { qc.setQueryData(["automations", "list"], ctx?.prev); toast.error(`${a.name}: ${errorMessage(e)}`); },
    onSuccess: (_r, a) => toast.success(a.status === "active" ? `Disabled “${a.name}”` : `Enabled “${a.name}”`),
    onSettled: () => { void qc.invalidateQueries({ queryKey: ["automations"] }); },
  });
  const runNow = useMutation({
    mutationFn: (a: Automation) => automationsApi.run(a.id, { dry_run: false }),
    onSuccess: (_r, a) => toast.success(`Started “${a.name}”`, { action: { label: "View runs", onClick: () => router.push(ws(`automations/${a.id}`)) } }),
    onError: (e) => toast.error(errorMessage(e)),
  });
  const newButtons = canManage && (
    <>
      <Button variant="outline" onClick={() => create.mutate(true)} disabled={create.isPending}><LayoutTemplate /> News → LinkedIn template</Button>
      <Button onClick={() => create.mutate(false)} disabled={create.isPending}><Plus /> New automation</Button>
    </>
  );

  return (
    <div>
      <PageHeader title="Automations" description="No-code workflows run by the automation engine; agents are nodes and approval nodes always halt for a human." actions={newButtons} />
      {list.isLoading ? <div className="space-y-2">{Array.from({ length: 4 }).map((_, i) => <Skeleton key={i} className="h-12" />)}</div>
        : missing ? (
          <div className="space-y-4">
            <Alert><Workflow /><AlertTitle>Automation backend not enabled yet</AlertTitle><AlertDescription>Automations are a V2 backend module. You can still open the builder and design a workflow; it’s kept in this browser until the engine is enabled.</AlertDescription></Alert>
            <TemplateCards onPick={(t) => router.push(ws(`automations/new${t ? "?template=news-linkedin" : ""}`))} disabled={!canManage} />
          </div>
        ) : list.error ? <QueryError error={list.error} onRetry={() => list.refetch()} title="Couldn't load automations" />
        : items.length === 0 ? (
          <div className="space-y-4">
            <EmptyState icon={Workflow} title="No automations yet" description="Start from a template or a blank canvas." />
            <TemplateCards onPick={(t) => create.mutate(t)} disabled={!canManage || create.isPending} />
          </div>
        ) : (
          <>
            <div className="hidden rounded-lg border md:block">
              <Table>
                <TableHeader><TableRow><TableHead>Name</TableHead><TableHead>Trigger</TableHead><TableHead>Enabled</TableHead><TableHead>Last run</TableHead><TableHead>Next run</TableHead><TableHead className="text-right">Success 30d</TableHead><TableHead>Owner</TableHead><TableHead /></TableRow></TableHeader>
                <TableBody>
                  {items.map((a) => (
                    <TableRow key={a.id}>
                      <TableCell><Link className="font-medium hover:underline" href={ws(`automations/${a.id}`)}>{a.name}</Link>{a.status === "draft" && <StatusChip status="draft" className="ml-2" />}</TableCell>
                      <TableCell className="max-w-[200px] truncate text-sm text-muted-foreground">{a.trigger_summary ?? "—"}</TableCell>
                      <TableCell><Switch checked={a.status === "active"} onCheckedChange={() => toggle.mutate(a)} disabled={!canManage || toggle.isPending} aria-label={`${a.status === "active" ? "Disable" : "Enable"} ${a.name}`} /></TableCell>
                      <TableCell className="text-sm">{a.last_run_at ? <span className="flex items-center gap-1">{a.last_run_status && <TaskGlyph status={a.last_run_status} />}{relTime(a.last_run_at)}</span> : "—"}</TableCell>
                      <TableCell className="text-sm text-muted-foreground">{a.status === "active" && a.next_run_at ? relTime(a.next_run_at) : "—"}</TableCell>
                      <TableCell className="text-right text-sm tabular-nums">{a.success_rate_30d == null ? "—" : fmtPct(a.success_rate_30d, 0)}</TableCell>
                      <TableCell className="text-sm">{ownerName(a.owner)}</TableCell>
                      <TableCell>{canCreate && a.status === "active" && <Button size="xs" variant="outline" onClick={() => runNow.mutate(a)} disabled={runNow.isPending}><Play /> Run now</Button>}</TableCell>
                    </TableRow>
                  ))}
                </TableBody>
              </Table>
            </div>
            <ul className="space-y-2 md:hidden">
              {items.map((a) => (
                <li key={a.id} className="flex items-center gap-3 rounded-lg border p-3">
                  <Link href={ws(`automations/${a.id}`)} className="min-w-0 flex-1"><p className="truncate font-medium">{a.name}</p><p className="text-xs text-muted-foreground">{a.trigger_summary ?? "—"} · last {relTime(a.last_run_at)}</p></Link>
                  <Switch checked={a.status === "active"} onCheckedChange={() => toggle.mutate(a)} disabled={!canManage} aria-label={`Toggle ${a.name}`} />
                </li>
              ))}
            </ul>
          </>
        )}
    </div>
  );
}

function TemplateCards({ onPick, disabled }: { onPick: (template: boolean) => void; disabled?: boolean }) {
  return (
    <div className="grid gap-3 sm:grid-cols-2">
      <button type="button" disabled={disabled} onClick={() => onPick(true)} className="rounded-xl border p-4 text-left hover:bg-accent disabled:opacity-60">
        <LayoutTemplate className="mb-2 h-5 w-5 text-ai" /><p className="font-medium">Industry news → LinkedIn post (with approval)</p>
        <p className="mt-1 text-xs text-muted-foreground">Trend detected → relevance gate → research → ideas → writer + critic → approval → schedule at the best time.</p>
      </button>
      <button type="button" disabled={disabled} onClick={() => onPick(false)} className="rounded-xl border border-dashed p-4 text-left hover:bg-accent disabled:opacity-60">
        <Plus className="mb-2 h-5 w-5 text-muted-foreground" /><p className="font-medium">Blank canvas</p><p className="mt-1 text-xs text-muted-foreground">Start with a trigger and add steps from the palette.</p>
      </button>
    </div>
  );
}

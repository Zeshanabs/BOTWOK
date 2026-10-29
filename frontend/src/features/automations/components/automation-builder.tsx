"use client";
import "@xyflow/react/dist/style.css";
import { useCallback, useState, useSyncExternalStore } from "react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { addEdge, Background, Controls, MarkerType, MiniMap, ReactFlow, ReactFlowProvider, useEdgesState, useNodesState, useReactFlow, type Connection, type Edge } from "@xyflow/react";
import { AlertTriangle, ArrowLeft, Ban, FlaskConical, Info, LayoutTemplate, Loader2, Play, Power, Save, Trash2 } from "lucide-react";
import { toast } from "sonner";
import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert";
import { Button } from "@/components/ui/button";
import { Dialog, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle } from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { Skeleton } from "@/components/ui/skeleton";
import { Switch } from "@/components/ui/switch";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { Textarea } from "@/components/ui/textarea";
import { StatusChip } from "@/components/shared/status-chip";
import { ConfirmDialog } from "@/features/common/components/confirm-dialog";
import { QueryError } from "@/features/common/components/query-state";
import { TaskGlyph } from "@/features/common/components/run-card";
import { useActiveBrand, useMediaQuery, usePermissions, useWorkspacePath } from "@/features/common/hooks";
import { errorMessage, fieldErrors, fmtDateTime, fmtUsd, isNotAvailable, relTime, toItems } from "@/features/common/utils";
import { cn } from "@/lib/utils";
import { automationsApi, BUILTIN_NODE_TYPES, newsToLinkedInTemplate, validateWorkflow, type Automation, type NodeType, type WorkflowEdgeDef, type WorkflowNodeDef } from "../api";
import { ConfigForm } from "./config-form";
import { NODE_ICONS, NODE_TYPES, type WFNode } from "./workflow-node";

const draftKey = (id: string) => `botwok:automation-draft:${id}`;
const noopSubscribe = () => () => {};

export function useNodeTypeCatalog() {
  const q = useQuery({ queryKey: ["automations", "node-types"], queryFn: () => automationsApi.nodeTypes(), retry: false, staleTime: 300_000 });
  const remote = toItems(q.data);
  return { types: remote.length ? remote : BUILTIN_NODE_TYPES, builtin: !remote.length };
}

function toRfNodes(defs: WorkflowNodeDef[], types: NodeType[]): WFNode[] {
  return defs.map((d) => {
    const t = types.find((x) => x.type === d.type);
    return { id: d.key, type: "workflow", position: d.position ?? { x: 0, y: 0 }, data: { type: d.type, label: d.label ?? t?.label ?? d.type, config: d.config ?? {}, typeLabel: t?.label ?? d.type, sideEffect: t?.side_effect, branches: t?.branches } };
  });
}
function edgeFor(e: WorkflowEdgeDef, i: number): Edge {
  return { id: `e-${e.from_node_key}-${e.to_node_key}-${e.branch ?? i}`, source: e.from_node_key, target: e.to_node_key, sourceHandle: e.branch ?? undefined, label: e.branch ?? undefined, data: { branch: e.branch ?? null }, markerEnd: { type: MarkerType.ArrowClosed } };
}
const fromRfNodes = (nodes: WFNode[]): WorkflowNodeDef[] => nodes.map((n) => ({ key: n.id, type: n.data.type, label: n.data.label, config: n.data.config, position: { x: Math.round(n.position.x), y: Math.round(n.position.y) } }));
const fromRfEdges = (edges: Edge[]): WorkflowEdgeDef[] => edges.map((e) => ({ from_node_key: e.source, to_node_key: e.target, branch: (e.data?.branch as string | null | undefined) ?? e.sourceHandle ?? null }));

/** Builder route: loads the workflow (or a template / local draft) and mounts the canvas. 404 → local-only mode with a banner. */
export function AutomationBuilder({ id, template }: { id: string; template?: string | null }) {
  const isNew = id === "new";
  const q = useQuery({ queryKey: ["automations", id], queryFn: () => automationsApi.get(id), enabled: !isNew, retry: false });
  const { types, builtin } = useNodeTypeCatalog();
  const draftRaw = useSyncExternalStore(noopSubscribe, () => { try { return window.localStorage.getItem(draftKey(id)); } catch { return null; } }, () => null);
  if (!isNew && q.isLoading) return <div className="space-y-3"><Skeleton className="h-9 w-1/2" /><Skeleton className="h-[60vh]" /></div>;
  if (q.error && !isNotAvailable(q.error)) return <QueryError error={q.error} onRetry={() => q.refetch()} title="Couldn't load this automation" />;
  let draft: { name: string; nodes: WorkflowNodeDef[]; edges: WorkflowEdgeDef[] } | null = null;
  try { draft = draftRaw ? JSON.parse(draftRaw) : null; } catch { draft = null; }
  const tpl = template === "news-linkedin" ? newsToLinkedInTemplate() : null;
  const initial: Automation = q.data ?? { id, name: draft?.name ?? tpl?.name ?? "Untitled automation", status: "draft", nodes: draft?.nodes ?? tpl?.nodes ?? [], edges: draft?.edges ?? tpl?.edges ?? [] };
  const backendMissing = isNotAvailable(q.error);
  return (
    <ReactFlowProvider>
      <BuilderInner key={`${id}:${q.data?.version ?? 0}:${draftRaw ? "draft" : "fresh"}:${template ?? ""}`} id={id} initial={initial} types={types} builtinTypes={builtin} initiallyMissing={backendMissing} />
    </ReactFlowProvider>
  );
}

function BuilderInner({ id, initial, types, builtinTypes, initiallyMissing }: { id: string; initial: Automation; types: NodeType[]; builtinTypes: boolean; initiallyMissing: boolean }) {
  const router = useRouter();
  const qc = useQueryClient();
  const ws = useWorkspacePath();
  const { brandId } = useActiveBrand();
  const { canManage } = usePermissions();
  const wide = useMediaQuery("(min-width: 1024px)", true);
  const editable = canManage && wide;
  const { screenToFlowPosition, setCenter } = useReactFlow();
  const [name, setName] = useState(initial.name);
  const [nodes, setNodes, onNodesChange] = useNodesState<WFNode>(toRfNodes(initial.nodes ?? [], types));
  const [edges, setEdges, onEdgesChange] = useEdgesState<Edge>((initial.edges ?? []).map(edgeFor));
  const [selectedNode, setSelectedNode] = useState<string | null>(null);
  const [selectedEdge, setSelectedEdge] = useState<string | null>(null);
  const [tab, setTab] = useState<"config" | "runs">("config");
  const [missing, setMissing] = useState(initiallyMissing);
  const [serverIssues, setServerIssues] = useState<{ node_key: string | null; message: string }[]>([]);
  const [dirty, setDirty] = useState(false);
  const [testOpen, setTestOpen] = useState(false);
  const [payload, setPayload] = useState('{\n  "title": "Sample industry news",\n  "relevance": 86\n}');
  const [runId, setRunId] = useState<string | null>(null);
  const [confirmDelete, setConfirmDelete] = useState(false);
  const [settings, setSettings] = useState<Record<string, unknown>>(initial.settings ?? { on_error: "notify", max_cost_usd: 1 });
  const [autonomous, setAutonomous] = useState(!!initial.autonomous_actions_enabled);
  const isNew = id === "new";
  const status = initial.status;

  const defs = fromRfNodes(nodes);
  const edgeDefs = fromRfEdges(edges);
  const issues = [...validateWorkflow(defs, edgeDefs, types), ...serverIssues];
  const invalidKeys = new Set(issues.map((i) => i.node_key).filter(Boolean) as string[]);
  const sideEffectNodes = defs.filter((d) => ["publish", "schedule", "webhook"].includes(d.type));

  const runs = useQuery({ queryKey: ["automations", id, "runs"], queryFn: () => automationsApi.runs(id), enabled: !isNew && !missing && tab === "runs", retry: false,
    refetchInterval: (q) => (toItems(q.state.data).some((r) => ["running", "waiting", "awaiting_approval"].includes(r.status)) ? 4000 : false) });
  const run = useQuery({ queryKey: ["automations", "runs", runId], queryFn: () => automationsApi.runDetail(runId as string), enabled: !!runId, retry: false,
    refetchInterval: (q) => (["running", "waiting"].includes(q.state.data?.status ?? "") ? 2000 : false) });
  const stepStatus = new Map((run.data?.steps ?? []).map((s) => [s.node_key, s.status]));
  const viewNodes = nodes.map((n) => ({ ...n, data: { ...n.data, invalid: invalidKeys.has(n.id), runStatus: runId ? stepStatus.get(n.id) ?? null : null, dryRun: run.data?.dry_run } }));

  const markDirty = () => setDirty(true);
  const uniqueKey = (type: string) => { let i = 1; while (nodes.some((n) => n.id === `${type}_${i}`)) i++; return `${type}_${i}`; };
  const addNode = (type: string, position?: { x: number; y: number }) => {
    const t = types.find((x) => x.type === type);
    const key = uniqueKey(type);
    const maxY = nodes.reduce((m, n) => Math.max(m, n.position.y), -120);
    setNodes((ns) => [...ns, { id: key, type: "workflow", position: position ?? { x: 250, y: maxY + 120 }, data: { type, label: t?.label ?? type, config: Object.fromEntries(Object.entries(t?.config_schema?.properties ?? {}).filter(([, p]) => p.default !== undefined).map(([k, p]) => [k, p.default])), typeLabel: t?.label ?? type, sideEffect: t?.side_effect, branches: t?.branches } }]);
    setSelectedNode(key); setSelectedEdge(null); setTab("config"); markDirty();
  };
  const onConnect = useCallback((c: Connection) => {
    setEdges((es) => addEdge({ ...c, id: `e-${c.source}-${c.target}-${c.sourceHandle ?? "out"}`, label: c.sourceHandle ?? undefined, data: { branch: c.sourceHandle ?? null }, markerEnd: { type: MarkerType.ArrowClosed } }, es));
    setDirty(true);
  }, [setEdges]);
  const focusNode = (key: string) => { const n = nodes.find((x) => x.id === key); if (n) { setSelectedNode(key); setTab("config"); void setCenter(n.position.x + 120, n.position.y + 30, { zoom: 1, duration: 300 }); } };
  const updateNode = (key: string, patch: { label?: string; config?: Record<string, unknown> }) => { setNodes((ns) => ns.map((n) => (n.id === key ? { ...n, data: { ...n.data, ...patch } } : n))); markDirty(); };
  const removeNode = (key: string) => { setNodes((ns) => ns.filter((n) => n.id !== key)); setEdges((es) => es.filter((e) => e.source !== key && e.target !== key)); setSelectedNode(null); markDirty(); };

  const saveLocal = () => { try { window.localStorage.setItem(draftKey(id), JSON.stringify({ name, nodes: defs, edges: edgeDefs })); } catch { /* ignore */ } };
  const save = useMutation({
    mutationFn: async () => {
      const body = { name: name.trim() || "Untitled automation", nodes: defs, edges: edgeDefs, settings, autonomous_actions_enabled: autonomous };
      if (isNew) return automationsApi.create({ ...body, brand_id: brandId }).then(async (a) => { try { await automationsApi.put(a.id, body); } catch { /* create may already persist the graph */ } return a; });
      return automationsApi.put(id, body);
    },
    onSuccess: (a) => {
      setDirty(false); setServerIssues([]);
      try { window.localStorage.removeItem(draftKey(id)); } catch { /* ignore */ }
      void qc.invalidateQueries({ queryKey: ["automations"] });
      toast.success(`Saved${a?.version ? ` · v${a.version}` : ""}`);
      if (isNew && a?.id) router.replace(ws(`automations/${a.id}`));
    },
    onError: (e) => {
      if (isNotAvailable(e)) { setMissing(true); saveLocal(); setDirty(false); toast.message("Saved in this browser — the automation backend isn't enabled yet"); return; }
      const fe = fieldErrors(e);
      setServerIssues(Object.entries(fe).map(([k, m]) => ({ node_key: nodes.some((n) => n.id === k) ? k : null, message: m })));
      toast.error(errorMessage(e));
    },
  });
  const toggle = useMutation({
    mutationFn: () => (status === "active" ? automationsApi.disable(id) : automationsApi.enable(id)),
    onSuccess: () => { toast.success(status === "active" ? "Disabled" : "Enabled — trigger registered"); void qc.invalidateQueries({ queryKey: ["automations"] }); },
    onError: (e) => { const fe = fieldErrors(e); setServerIssues(Object.entries(fe).map(([k, m]) => ({ node_key: nodes.some((n) => n.id === k) ? k : null, message: m }))); toast.error(isNotAvailable(e) ? "Automation backend not enabled yet" : errorMessage(e)); },
  });
  const test = useMutation({
    mutationFn: () => { let p: Record<string, unknown> | undefined; try { p = payload.trim() ? JSON.parse(payload) : undefined; } catch { throw new Error("Sample payload is not valid JSON"); } return automationsApi.run(id, { dry_run: true, payload: p }); },
    onSuccess: (r) => { setRunId(r.run_id); setTestOpen(false); setTab("runs"); toast.success("Test run started — side-effect nodes are simulated"); void qc.invalidateQueries({ queryKey: ["automations", id, "runs"] }); },
    onError: (e) => toast.error(isNotAvailable(e) ? "Test runs need the automation backend" : errorMessage(e)),
  });
  const cancelRun = useMutation({ mutationFn: (rid: string) => automationsApi.cancelRun(rid), onSuccess: () => { toast.success("Cancel requested"); void run.refetch(); }, onError: (e) => toast.error(errorMessage(e)) });
  const del = useMutation({ mutationFn: () => automationsApi.remove(id), onSuccess: () => { toast.success("Automation deleted"); router.push(ws("automations")); }, onError: (e) => toast.error(errorMessage(e)) });
  const applyTemplate = () => {
    const t = newsToLinkedInTemplate();
    setNodes(toRfNodes(t.nodes, types)); setEdges(t.edges.map(edgeFor)); if (!name || name === "Untitled automation") setName(t.name); markDirty();
  };

  const node = nodes.find((n) => n.id === selectedNode) ?? null;
  const nodeType = node ? types.find((t) => t.type === node.data.type) : undefined;
  const edge = edges.find((e) => e.id === selectedEdge) ?? null;

  return (
    <div className="flex flex-col gap-3">
      <div className="flex flex-wrap items-center gap-2">
        <Button asChild variant="ghost" size="icon-sm" aria-label="Back"><Link href={ws("automations")}><ArrowLeft /></Link></Button>
        <Input value={name} onChange={(e) => { setName(e.target.value); markDirty(); }} disabled={!canManage} aria-label="Automation name" className="h-9 w-full max-w-sm border-transparent text-lg font-semibold shadow-none hover:border-input" />
        <StatusChip status={status === "active" ? "active" : status === "paused" ? "paused" : "draft"} />
        {initial.version != null && <span className="text-xs text-muted-foreground">v{initial.version}{initial.updated_at ? ` · saved ${relTime(initial.updated_at)}` : ""}</span>}
        {dirty && <span className="text-xs text-warning">● unsaved</span>}
        <div className="ml-auto flex flex-wrap gap-2">
          {canManage && <Button size="sm" variant="ghost" onClick={applyTemplate}><LayoutTemplate /> News → LinkedIn template</Button>}
          <Button size="sm" variant="outline" disabled={isNew || missing} onClick={() => setTestOpen(true)} title={missing ? "Needs the automation backend" : undefined}><FlaskConical /> Test run</Button>
          {canManage && <Button size="sm" variant="outline" onClick={() => save.mutate()} disabled={save.isPending}>{save.isPending ? <Loader2 className="animate-spin" /> : <Save />} Save</Button>}
          {canManage && !isNew && <Button size="sm" onClick={() => toggle.mutate()} disabled={toggle.isPending || missing || dirty || (status !== "active" && issues.length > 0)} title={dirty ? "Save first" : issues.length ? "Fix validation issues first" : undefined}><Power /> {status === "active" ? "Disable" : "Enable"}</Button>}
          {canManage && !isNew && !missing && <Button size="icon-sm" variant="ghost" aria-label="Delete automation" onClick={() => setConfirmDelete(true)}><Trash2 /></Button>}
        </div>
      </div>

      {missing && (
        <Alert><Info /><AlertTitle>Automation backend not enabled yet</AlertTitle>
          <AlertDescription>You can design the workflow now; it’s kept in this browser. Saving, enabling and test runs work once the automation engine (V2) is enabled.</AlertDescription></Alert>
      )}
      {builtinTypes && !missing && <p className="text-xs text-muted-foreground">Using the built-in node catalog (node-types endpoint unavailable).</p>}
      {!canManage && <p className="text-sm text-muted-foreground">Read-only — owners and admins edit automations.</p>}
      {canManage && !wide && <p className="text-sm text-muted-foreground">The builder is read-only on small screens. Runs, enable/disable and cancel still work.</p>}
      {issues.length > 0 && (
        <div className="rounded-md border border-warning/40 bg-warning/[0.08] p-2 text-xs" role="status">
          <p className="mb-1 flex items-center gap-1 font-medium"><AlertTriangle className="h-3.5 w-3.5 text-warning" /> {issues.length} issue{issues.length === 1 ? "" : "s"} block enabling</p>
          <ul className="space-y-0.5">{issues.map((i, k) => <li key={k}>{i.node_key ? <button type="button" className="text-left underline-offset-2 hover:underline" onClick={() => focusNode(i.node_key as string)}>{i.message}</button> : i.message}</li>)}</ul>
        </div>
      )}
      {sideEffectNodes.length > 0 && !autonomous && <p className="text-xs text-muted-foreground">Schedule / Publish / Webhook nodes stay disabled until an admin enables autonomous actions. AI-generated content still needs human approval either way.</p>}

      <div className={cn("grid gap-3", wide && "lg:grid-cols-[170px_minmax(0,1fr)_320px]")}>
        {wide && (
          <aside aria-label="Node palette" className="space-y-1">
            <p className="text-[11px] font-semibold uppercase tracking-wide text-muted-foreground">Nodes</p>
            {types.map((t) => {
              const Icon = NODE_ICONS[t.type] ?? NODE_ICONS.action;
              return (
                <button key={t.type} type="button" draggable={editable} disabled={!editable} title={t.description}
                        onDragStart={(e) => { e.dataTransfer.setData("application/botwok-node", t.type); e.dataTransfer.effectAllowed = "move"; }}
                        onClick={() => addNode(t.type)} className="flex w-full items-center gap-2 rounded-md border px-2 py-1.5 text-left text-xs hover:bg-accent disabled:opacity-50">
                  <Icon className={cn("h-3.5 w-3.5", (t.type === "ai_agent" || t.type === "generate") && "text-ai")} />{t.label}
                </button>
              );
            })}
          </aside>
        )}
        <div className="h-[65vh] min-h-[420px] overflow-hidden rounded-lg border bg-muted/20"
             onDragOver={(e) => { if (editable) { e.preventDefault(); e.dataTransfer.dropEffect = "move"; } }}
             onDrop={(e) => { const type = e.dataTransfer.getData("application/botwok-node"); if (!type || !editable) return; e.preventDefault(); addNode(type, screenToFlowPosition({ x: e.clientX, y: e.clientY })); }}>
          <ReactFlow nodes={viewNodes} edges={edges} nodeTypes={NODE_TYPES} onNodesChange={(c) => { onNodesChange(c); if (c.some((x) => x.type === "position" || x.type === "remove")) setDirty(true); }}
                     onEdgesChange={(c) => { onEdgesChange(c); if (c.some((x) => x.type === "remove")) setDirty(true); }} onConnect={onConnect}
                     onNodeClick={(_e, n) => { setSelectedNode(n.id); setSelectedEdge(null); setTab("config"); }} onEdgeClick={(_e, ed) => { setSelectedEdge(ed.id); setSelectedNode(null); setTab("config"); }}
                     onPaneClick={() => { setSelectedNode(null); setSelectedEdge(null); }}
                     nodesDraggable={editable} nodesConnectable={editable} elementsSelectable deleteKeyCode={editable ? ["Backspace", "Delete"] : null} fitView proOptions={{ hideAttribution: true }}>
            <Background gap={16} />
            <Controls showInteractive={false} />
            {wide && <MiniMap pannable zoomable className="!bg-background" />}
          </ReactFlow>
        </div>
        <aside aria-label="Inspector" className="min-w-0">
          <Tabs value={tab} onValueChange={(v) => setTab(v as "config" | "runs")}>
            <TabsList className="w-full"><TabsTrigger value="config">{node ? "Node" : edge ? "Edge" : "Workflow"}</TabsTrigger><TabsTrigger value="runs">Runs</TabsTrigger></TabsList>
            <TabsContent value="config" className="space-y-3 pt-2">
              {node ? (
                <>
                  <div className="flex items-center gap-2"><p className="text-sm font-medium">{node.data.typeLabel}</p>{nodeType?.side_effect && <span className="rounded border px-1 text-[10px] uppercase text-muted-foreground">{nodeType.side_effect.replace(/_/g, " ").toLowerCase()}</span>}
                    {editable && <Button size="icon-xs" variant="ghost" className="ml-auto" aria-label="Delete node" onClick={() => removeNode(node.id)}><Trash2 /></Button>}</div>
                  {nodeType?.description && <p className="text-xs text-muted-foreground">{nodeType.description}</p>}
                  <div className="space-y-1"><Label htmlFor="node-label" className="text-xs">Name</Label><Input id="node-label" className="h-8" value={node.data.label} disabled={!editable} onChange={(e) => updateNode(node.id, { label: e.target.value })} /></div>
                  <ConfigForm key={node.id} nodeType={nodeType} config={node.data.config} onChange={(c) => updateNode(node.id, { config: c })} disabled={!editable} errors={issues.filter((i) => i.node_key === node.id).map((i) => i.message)} />
                  {nodeType?.branches && <p className="text-[11px] text-muted-foreground">Branches: {nodeType.branches.join(" /")} — drag from the matching handle.</p>}
                  <p className="font-mono text-[10px] text-muted-foreground">key: {node.id}</p>
                </>
              ) : edge ? (
                <>
                  <p className="text-sm font-medium">{edge.source} → {edge.target}</p>
                  <div className="space-y-1"><Label className="text-xs">Branch</Label>
                    <Select value={(edge.data?.branch as string | null) ?? "none"} onValueChange={(b) => { setEdges((es) => es.map((x) => (x.id === edge.id ? { ...x, label: b === "none" ? undefined : b, data: { branch: b === "none" ? null : b } } : x))); markDirty(); }} disabled={!editable}>
                      <SelectTrigger size="sm" className="w-full"><SelectValue /></SelectTrigger>
                      <SelectContent>{["none", "true", "false", "approved", "rejected", "error"].map((b) => <SelectItem key={b} value={b}>{b === "none" ? "always" : b}</SelectItem>)}</SelectContent></Select></div>
                  {editable && <Button size="sm" variant="outline" onClick={() => { setEdges((es) => es.filter((x) => x.id !== edge.id)); setSelectedEdge(null); markDirty(); }}><Trash2 /> Remove edge</Button>}
                </>
              ) : (
                <div className="space-y-3 text-sm">
                  <p className="text-xs text-muted-foreground">Select a node to configure it. Drag nodes from the palette or click to add; connect handles to create edges.</p>
                  <div className="space-y-1"><Label className="text-xs">On error</Label>
                    <Select value={String(settings.on_error ?? "notify")} onValueChange={(v) => { setSettings((s) => ({ ...s, on_error: v })); markDirty(); }} disabled={!canManage}><SelectTrigger size="sm" className="w-full"><SelectValue /></SelectTrigger>
                      <SelectContent><SelectItem value="stop">stop</SelectItem><SelectItem value="continue">continue</SelectItem><SelectItem value="notify">notify</SelectItem></SelectContent></Select></div>
                  <div className="space-y-1"><Label htmlFor="max-cost" className="text-xs">Max cost per run (USD)</Label><Input id="max-cost" type="number" step="0.01" className="h-8" value={String(settings.max_cost_usd ?? "")} disabled={!canManage} onChange={(e) => { setSettings((s) => ({ ...s, max_cost_usd: e.target.value === "" ? undefined : Number(e.target.value) })); markDirty(); }} /></div>
                  <div className="flex items-center justify-between gap-2"><Label htmlFor="autonomy" className="text-xs">Autonomous actions (schedule/publish/webhook)</Label><Switch id="autonomy" checked={autonomous} onCheckedChange={(c) => { setAutonomous(c); markDirty(); }} disabled={!canManage} /></div>
                  {autonomous && <p className="text-[11px] text-warning">Side-effect nodes may run without a person clicking. Approval nodes and the AI-content approval policy still apply.</p>}
                </div>
              )}
            </TabsContent>
            <TabsContent value="runs" className="space-y-2 pt-2">
              {isNew || missing ? <p className="text-sm text-muted-foreground">Run history appears once the workflow is saved on the backend.</p> : (
                <>
                  {runs.isLoading && <Skeleton className="h-20" />}
                  {runs.error && <QueryError error={runs.error} onRetry={() => runs.refetch()} notAvailableText="Run history isn't available yet." />}
                  {runs.data && toItems(runs.data).length === 0 && <p className="text-sm text-muted-foreground">No runs yet. Use Test run to try it safely.</p>}
                  <ul className="max-h-48 space-y-1 overflow-y-auto">
                    {toItems(runs.data).map((r) => (
                      <li key={r.id}><button type="button" onClick={() => setRunId(r.id === runId ? null : r.id)} className={cn("flex w-full items-center gap-2 rounded-md border px-2 py-1.5 text-left text-xs hover:bg-accent", r.id === runId && "border-primary bg-primary/5")}>
                        <TaskGlyph status={r.status} /><span className="flex-1">{r.trigger_type ?? "run"}{r.dry_run && " · dry run"}</span><span className="text-muted-foreground">{relTime(r.started_at)}</span>{r.cost_usd != null && <span className="text-muted-foreground">{fmtUsd(r.cost_usd)}</span>}
                      </button></li>
                    ))}
                  </ul>
                  {runId && (
                    <div className="space-y-2 rounded-md border p-2 text-xs">
                      {run.isLoading && <Skeleton className="h-16" />}
                      {run.data && (
                        <>
                          <div className="flex items-center gap-2"><StatusChip status={run.data.status} />{run.data.dry_run && <span className="rounded bg-muted px-1">dry run — side effects simulated</span>}
                            {["running", "waiting", "awaiting_approval"].includes(run.data.status) && <Button size="xs" variant="ghost" className="ml-auto" onClick={() => cancelRun.mutate(run.data!.id)}><Ban /> Cancel run</Button>}</div>
                          <p className="text-muted-foreground">Started {fmtDateTime(run.data.started_at)}{run.data.finished_at ? ` · took ${Math.max(1, Math.round((new Date(run.data.finished_at).getTime() - new Date(run.data.started_at).getTime()) / 1000))}s` : ""} · {fmtUsd(run.data.cost_usd)}</p>
                          {run.data.error && <p className="text-destructive">{run.data.error}</p>}
                          <ol className="space-y-1">
                            {(run.data.steps ?? []).map((s, i) => (
                              <li key={s.id ?? i}>
                                <details className="rounded border p-1.5">
                                  <summary className="flex cursor-pointer items-center gap-1.5"><TaskGlyph status={s.status} /><button type="button" className="hover:underline" onClick={(e) => { e.preventDefault(); focusNode(s.node_key); }}>{nodes.find((n) => n.id === s.node_key)?.data.label ?? s.node_key}</button>{(s.attempts ?? 0) > 1 && <span className="text-muted-foreground">×{s.attempts}</span>}</summary>
                                  {s.error && <p className="mt-1 text-destructive">{s.error}</p>}
                                  {s.ai_run_id && <Link className="mt-1 block text-primary hover:underline" href={ws(`command-center/${s.ai_run_id}`)}>AI run ↗</Link>}
                                  {s.input != null && <pre className="mt-1 max-h-32 overflow-auto rounded bg-muted p-1 text-[10px]">in: {JSON.stringify(s.input, null, 2)}</pre>}
                                  {s.output != null && <pre className="mt-1 max-h-32 overflow-auto rounded bg-muted p-1 text-[10px]">out: {JSON.stringify(s.output, null, 2)}</pre>}
                                </details>
                              </li>
                            ))}
                          </ol>
                        </>
                      )}
                      {run.error && <QueryError error={run.error} onRetry={() => run.refetch()} />}
                    </div>
                  )}
                </>
              )}
            </TabsContent>
          </Tabs>
        </aside>
      </div>

      <Dialog open={testOpen} onOpenChange={setTestOpen}>
        <DialogContent>
          <DialogHeader><DialogTitle>Test run</DialogTitle><DialogDescription>AI nodes run for real (and cost money); Schedule, Publish and Webhook nodes are simulated and labelled “dry run”.</DialogDescription></DialogHeader>
          <Label htmlFor="payload">Sample trigger payload (JSON)</Label>
          <Textarea id="payload" rows={8} className="font-mono text-xs" value={payload} onChange={(e) => setPayload(e.target.value)} />
          {typeof settings.max_cost_usd === "number" && <p className="text-xs text-muted-foreground">Capped at {fmtUsd(settings.max_cost_usd)} per run.</p>}
          <DialogFooter><Button variant="outline" onClick={() => setTestOpen(false)}>Cancel</Button><Button onClick={() => test.mutate()} disabled={test.isPending}>{test.isPending ? <Loader2 className="animate-spin" /> : <Play />} Start dry run</Button></DialogFooter>
        </DialogContent>
      </Dialog>
      <ConfirmDialog open={confirmDelete} onOpenChange={setConfirmDelete} destructive title={`Delete “${name}”?`} confirmLabel="Delete automation" pending={del.isPending} typeToConfirm={status === "active" ? name : undefined}
                     onConfirm={() => del.mutate()} description={<p>The workflow, its versions and trigger registration are removed. Past run history stays in the audit log.</p>} />
    </div>
  );
}

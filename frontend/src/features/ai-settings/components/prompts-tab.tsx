"use client";
import { useState } from "react";
import { toast } from "sonner";
import { FlaskConical, History } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Label } from "@/components/ui/label";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { Textarea } from "@/components/ui/textarea";
import { ListSkeleton, QueryError, errorMessage, isNotAvailable } from "@/components/data/async-states";
import { FormError } from "@/components/data/form-errors";
import { fmtDateTime } from "@/lib/formatters";
import { useActiveBrandId } from "@/features/brand/hooks";
import { RunProgress } from "@/features/ai/components/run-progress";
import { useStartRun } from "@/features/ai/hooks";
import { useAgents, usePrompt, useSavePrompt } from "../hooks";
import type { PromptTemplate } from "../types";

function variablesIn(body: string): string[] {
  return Array.from(new Set(Array.from(body.matchAll(/\{\{\s*([\w.]+)\s*\}\}/g)).map((m) => m[1])));
}

function Editor({ agentId, template, readOnly }: { agentId: string; template: PromptTemplate; readOnly: boolean }) {
  const brandId = useActiveBrandId();
  const save = useSavePrompt(agentId);
  const start = useStartRun();
  const [body, setBody] = useState(template.body ?? template.versions?.find((v) => v.is_active)?.body ?? "");
  const [sample, setSample] = useState('{\n  "topic": "Example topic",\n  "platform": "linkedin"\n}');
  const [testRun, setTestRun] = useState<string | null>(null);
  const vars = variablesIn(body);
  const versions = [...(template.versions ?? [])].sort((a, b) => b.version - a.version);
  const active = template.active_version ?? template.version ?? versions.find((v) => v.is_active)?.version;

  function runTest() {
    let inputs: Record<string, unknown> = {};
    try { inputs = sample.trim() ? JSON.parse(sample) : {}; } catch { toast.error("Sample inputs must be valid JSON"); return; }
    start.mutate({ mode: "tool", agent: agentId, message: `Prompt template test for ${agentId}`, brand_id: brandId, inputs: { ...inputs, prompt_override: body, dry_run: true }, budget_usd: 0.25 }, {
      onSuccess: (d) => setTestRun(d.run_id),
      onError: (e) => toast.error(isNotAvailable(e) ? "Test runs aren't available yet." : errorMessage(e)),
    });
  }

  return (
    <div className="grid gap-4 lg:grid-cols-[minmax(0,1fr)_260px]">
      <div className="space-y-3">
        <div className="space-y-1">
          <Label htmlFor="prompt-body">Template{active ? <span className="ml-2 font-normal text-muted-foreground">active v{active}</span> : null}</Label>
          <Textarea id="prompt-body" rows={18} className="font-mono text-xs" value={body} onChange={(e) => setBody(e.target.value)} disabled={readOnly} />
          <p className="text-xs text-muted-foreground">Variables: {vars.length ? vars.map((v) => <code key={v} className="mr-1 rounded bg-muted px-1">{`{{${v}}}`}</code>) : "none"}</p>
        </div>
        <FormError error={save.error} />
        {!readOnly && (
          <div className="flex justify-end">
            <Button disabled={save.isPending || !body.trim() || body === template.body} onClick={() => save.mutate({ body, variables: vars }, { onSuccess: () => toast.success("Saved as a new version") })}>
              {save.isPending ? "Saving…" : "Save new version"}
            </Button>
          </div>
        )}
        <Card>
          <CardHeader><CardTitle className="flex items-center gap-1 text-sm"><FlaskConical className="h-4 w-4" /> Test</CardTitle><CardDescription>Dry run with sample inputs; shows output, tokens and cost. Capped at $0.25.</CardDescription></CardHeader>
          <CardContent className="space-y-2">
            <Textarea aria-label="Sample inputs (JSON)" rows={5} className="font-mono text-xs" value={sample} onChange={(e) => setSample(e.target.value)} />
            <Button size="sm" variant="outline" disabled={start.isPending || readOnly} onClick={runTest}>{start.isPending ? "Starting…" : "Run test"}</Button>
            {testRun && <RunProgress runId={testRun} title="Test run" />}
          </CardContent>
        </Card>
      </div>
      <aside className="space-y-2">
        <h3 className="flex items-center gap-1 text-sm font-semibold"><History className="h-4 w-4" /> Versions</h3>
        {!versions.length ? <p className="text-xs text-muted-foreground">Only the built-in default exists.</p> : (
          <ul className="space-y-1">
            {versions.map((v) => (
              <li key={v.version} className="flex items-center justify-between gap-2 rounded-md border p-2 text-xs">
                <span>v{v.version}{v.is_active || v.version === active ? <span className="ml-1 text-green-700 dark:text-green-300">active</span> : null}<span className="block text-muted-foreground">{fmtDateTime(v.created_at)}{typeof v.created_by === "object" && v.created_by?.full_name ? ` · ${v.created_by.full_name}` : ""}</span></span>
                <span className="flex gap-1">
                  <Button size="xs" variant="ghost" onClick={() => setBody(v.body)}>Load</Button>
                  {!readOnly && v.version !== active && <Button size="xs" variant="outline" disabled={save.isPending} onClick={() => save.mutate({ body: v.body, restore_version: v.version }, { onSuccess: () => toast.success(`Restored v${v.version}`) })}>Restore</Button>}
                </span>
              </li>
            ))}
          </ul>
        )}
      </aside>
    </div>
  );
}

export function PromptsTab({ readOnly }: { readOnly: boolean }) {
  const agents = useAgents();
  const [agentId, setAgentId] = useState<string | null>(null);
  const current = agentId ?? agents.data?.[0]?.id ?? null;
  const prompt = usePrompt(current);
  if (agents.isLoading) return <ListSkeleton rows={4} />;
  if (agents.error) return <QueryError error={agents.error} onRetry={() => agents.refetch()} title="Couldn't load agents" />;
  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-center gap-2">
        <Label htmlFor="prompt-agent">Agent</Label>
        <Select value={current ?? undefined} onValueChange={setAgentId}>
          <SelectTrigger id="prompt-agent" className="w-64"><SelectValue placeholder="Choose an agent" /></SelectTrigger>
          <SelectContent>{(agents.data ?? []).map((a) => <SelectItem key={a.id} value={a.id}>{a.name ?? a.id}</SelectItem>)}</SelectContent>
        </Select>
        {current && <span className="text-xs text-muted-foreground">{agents.data?.find((a) => a.id === current)?.description}</span>}
      </div>
      {!current ? null : prompt.isLoading ? <ListSkeleton rows={6} /> : prompt.error ? (
        <QueryError error={prompt.error} onRetry={() => prompt.refetch()} title="Couldn't load the template" notAvailableText="Prompt templates for this agent aren't editable on this install yet." />
      ) : prompt.data ? <Editor key={`${current}-${prompt.data.active_version ?? prompt.data.version ?? 0}`} agentId={current} template={prompt.data} readOnly={readOnly} /> : null}
    </div>
  );
}

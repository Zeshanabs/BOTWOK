"use client";
import { useState } from "react";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { Switch } from "@/components/ui/switch";
import { Textarea } from "@/components/ui/textarea";
import type { NodeType, SchemaProp } from "../api";

function JsonField({ id, value, onChange, disabled }: { id: string; value: unknown; onChange: (v: unknown) => void; disabled?: boolean }) {
  const [text, setText] = useState(() => (value == null ? "" : JSON.stringify(value, null, 2)));
  const [err, setErr] = useState<string | null>(null);
  return (
    <>
      <Textarea id={id} rows={4} className="font-mono text-xs" value={text} disabled={disabled} aria-invalid={!!err}
                onChange={(e) => { setText(e.target.value); try { onChange(e.target.value.trim() ? JSON.parse(e.target.value) : undefined); setErr(null); } catch { setErr("Invalid JSON"); } }} />
      {err && <p className="text-xs text-destructive">{err}</p>}
    </>
  );
}

/** JSON-schema-ish form for a node's config (string/number/boolean/enum/textarea/json). */
export function ConfigForm({ nodeType, config, onChange, disabled, errors }: { nodeType: NodeType | undefined; config: Record<string, unknown>; onChange: (c: Record<string, unknown>) => void; disabled?: boolean; errors?: string[] }) {
  const props = Object.entries(nodeType?.config_schema?.properties ?? {});
  const required = new Set(nodeType?.config_schema?.required ?? []);
  const set = (k: string, v: unknown) => { const next = { ...config }; if (v === undefined || v === "") delete next[k]; else next[k] = v; onChange(next); };
  if (!props.length) return <p className="text-xs text-muted-foreground">This node has no settings.</p>;
  return (
    <div className="space-y-3">
      {props.map(([k, p]: [string, SchemaProp]) => {
        const id = `cfg-${k}`;
        const v = config[k] ?? p.default;
        const title = <Label htmlFor={id} className="text-xs">{p.title ?? k}{required.has(k) && <span className="text-destructive"> *</span>}</Label>;
        const help = p.description && <p className="text-[11px] text-muted-foreground">{p.description}</p>;
        if (p.type === "boolean") return <div key={k} className="flex items-center justify-between gap-2">{title}<Switch id={id} checked={v === true} onCheckedChange={(c) => set(k, c)} disabled={disabled} /></div>;
        if (p.enum) return (
          <div key={k} className="space-y-1">{title}
            <Select value={typeof v === "string" ? v : ""} onValueChange={(x) => set(k, x)} disabled={disabled}><SelectTrigger id={id} size="sm" className="w-full"><SelectValue placeholder="Choose…" /></SelectTrigger>
              <SelectContent>{p.enum.map((o) => <SelectItem key={o} value={o}>{o}</SelectItem>)}</SelectContent></Select>{help}</div>
        );
        if (p.type === "object" || p.format === "json") return <div key={k} className="space-y-1">{title}<JsonField id={id} value={v} onChange={(x) => set(k, x)} disabled={disabled} />{help}</div>;
        if (p.type === "number" || p.type === "integer") return (
          <div key={k} className="space-y-1">{title}<Input id={id} type="number" className="h-8" min={p.minimum} max={p.maximum} step={p.type === "integer" ? 1 : "any"} value={v == null ? "" : String(v)} disabled={disabled}
                 onChange={(e) => set(k, e.target.value === "" ? undefined : p.type === "integer" ? Math.round(Number(e.target.value)) : Number(e.target.value))} />{help}</div>
        );
        if (p.format === "textarea") return <div key={k} className="space-y-1">{title}<Textarea id={id} rows={3} value={typeof v === "string" ? v : ""} onChange={(e) => set(k, e.target.value)} disabled={disabled} />{help}</div>;
        return <div key={k} className="space-y-1">{title}<Input id={id} className={p.format === "expression" || p.format === "cron" ? "h-8 font-mono text-xs" : "h-8"} value={typeof v === "string" || typeof v === "number" ? String(v) : ""} onChange={(e) => set(k, e.target.value)} disabled={disabled} placeholder={p.format === "expression" ? "trigger.field" : undefined} />{help}</div>;
      })}
      {(errors ?? []).length > 0 && <ul className="space-y-0.5 text-xs text-destructive">{errors?.map((e, i) => <li key={i}>⚠ {e}</li>)}</ul>}
    </div>
  );
}

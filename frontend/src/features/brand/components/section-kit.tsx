"use client";
/** Small building blocks shared by the Brand Settings section editors. */
import { toast } from "sonner";
import { Plus, Trash2 } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Label } from "@/components/ui/label";
import { FormError } from "@/components/data/form-errors";
import { errorMessage } from "@/components/data/async-states";
import { useSaveSettings } from "../hooks";
import type { Brand, BrandSettings, BrandSettingsUpdate } from "../types";

export interface SectionProps { brand: Brand; settings: BrandSettings; readOnly: boolean }

export function useSectionSave(brandId: string) {
  const m = useSaveSettings(brandId);
  return {
    save: (body: BrandSettingsUpdate, onSaved?: () => void) =>
      m.mutate(body, { onSuccess: () => { toast.success("Saved — the AI context is updated"); onSaved?.(); }, onError: (e) => toast.error(errorMessage(e, "Couldn't save")) }),
    pending: m.isPending,
    error: m.error,
  };
}

export function Field({ label, htmlFor, hint, children }: { label: string; htmlFor?: string; hint?: string; children: React.ReactNode }) {
  return (
    <div className="space-y-1">
      <Label htmlFor={htmlFor}>{label}</Label>
      {children}
      {hint && <p className="text-xs text-muted-foreground">{hint}</p>}
    </div>
  );
}

export function SaveBar({ onSave, pending, error, readOnly, dirty = true }: { onSave: () => void; pending: boolean; error: unknown; readOnly: boolean; dirty?: boolean }) {
  if (readOnly) return <p className="text-xs text-muted-foreground">Only owners and admins can edit brand settings.</p>;
  return (
    <div className="space-y-2 border-t pt-4">
      <FormError error={error} />
      <div className="flex items-center justify-end gap-3">
        {dirty && <span className="text-xs text-muted-foreground">Unsaved changes</span>}
        <Button onClick={onSave} disabled={pending}>{pending ? "Saving…" : "Save"}</Button>
      </div>
    </div>
  );
}

/** Generic editable list of rows with add/remove. */
export function RowList<T>({ items, onChange, render, empty, addLabel, make, readOnly }: {
  items: T[]; onChange: (next: T[]) => void; render: (item: T, update: (patch: Partial<T>) => void, index: number) => React.ReactNode;
  empty: string; addLabel: string; make: () => T; readOnly: boolean;
}) {
  return (
    <div className="space-y-2">
      {!items.length && <p className="text-xs text-muted-foreground">{empty}</p>}
      {items.map((item, i) => (
        <div key={i} className="flex items-start gap-2 rounded-lg border p-3">
          <div className="min-w-0 flex-1 space-y-2">{render(item, (patch) => onChange(items.map((x, j) => (j === i ? { ...x, ...patch } : x))), i)}</div>
          {!readOnly && <Button type="button" variant="ghost" size="icon-sm" aria-label="Remove" onClick={() => onChange(items.filter((_, j) => j !== i))}><Trash2 className="h-4 w-4" /></Button>}
        </div>
      ))}
      {!readOnly && <Button type="button" variant="outline" size="sm" onClick={() => onChange([...items, make()])}><Plus className="h-3 w-3" /> {addLabel}</Button>}
    </div>
  );
}

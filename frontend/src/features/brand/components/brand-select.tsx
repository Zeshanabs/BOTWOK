"use client";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { useBrands } from "../hooks";

const NONE = "__none";

export function BrandSelect({ value, onChange, id, allowNone, className }: {
  value: string | null | undefined;
  onChange: (id: string | null) => void;
  id?: string;
  allowNone?: boolean;
  className?: string;
}) {
  const brands = useBrands();
  return (
    <Select value={value ?? NONE} onValueChange={(v) => onChange(v === NONE ? null : v)}>
      <SelectTrigger id={id} className={className ?? "w-full"} aria-label="Brand">
        <SelectValue placeholder={brands.isLoading ? "Loading brands…" : "Select a brand"} />
      </SelectTrigger>
      <SelectContent>
        {allowNone && <SelectItem value={NONE}>No brand</SelectItem>}
        {!allowNone && !value && <SelectItem value={NONE} disabled>Select a brand</SelectItem>}
        {(brands.data ?? []).map((b) => <SelectItem key={b.id} value={b.id}>{b.name}</SelectItem>)}
      </SelectContent>
    </Select>
  );
}

"use client";
import { useId } from "react";
import { Input } from "@/components/ui/input";

function zones(): string[] {
  try {
    return Intl.supportedValuesOf("timeZone");
  } catch {
    return ["UTC", "Europe/London", "Europe/Berlin", "America/New_York", "America/Los_Angeles", "Asia/Tokyo"];
  }
}

export function browserTimezone(): string {
  try { return Intl.DateTimeFormat().resolvedOptions().timeZone || "UTC"; } catch { return "UTC"; }
}

/** Free-text IANA timezone with suggestions. */
export function TimezoneInput({ id, value, onChange, disabled, invalid }: { id?: string; value: string; onChange: (v: string) => void; disabled?: boolean; invalid?: boolean }) {
  const listId = useId();
  return (
    <>
      <Input id={id} list={listId} value={value} onChange={(e) => onChange(e.target.value)} disabled={disabled} aria-invalid={invalid} placeholder="e.g. Europe/Berlin" autoComplete="off" />
      <datalist id={listId}>{zones().map((z) => <option key={z} value={z} />)}</datalist>
    </>
  );
}

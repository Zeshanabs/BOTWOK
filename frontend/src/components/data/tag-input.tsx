"use client";
/** Chip list input: Enter or comma adds a tag, Backspace on empty removes the last one. */
import { useId, useState } from "react";
import { X } from "lucide-react";
import { cn } from "@/lib/utils";

export function TagInput({ value, onChange, placeholder = "Type and press Enter", disabled, id, className, transform, ariaLabel }: {
  value: string[];
  onChange: (next: string[]) => void;
  placeholder?: string;
  disabled?: boolean;
  id?: string;
  className?: string;
  /** Normalizes each new tag (e.g. prefix "#"). */
  transform?: (s: string) => string;
  ariaLabel?: string;
}) {
  const [draft, setDraft] = useState("");
  const autoId = useId();
  const inputId = id ?? autoId;
  function add(raw: string) {
    const parts = raw.split(",").map((s) => s.trim()).filter(Boolean).map((s) => (transform ? transform(s) : s));
    if (!parts.length) return;
    const next = [...value];
    for (const p of parts) if (!next.includes(p)) next.push(p);
    onChange(next);
    setDraft("");
  }
  return (
    <div className={cn("flex min-h-9 flex-wrap items-center gap-1 rounded-md border border-input bg-transparent px-2 py-1 text-sm shadow-xs focus-within:ring-[3px] focus-within:ring-ring/50", disabled && "opacity-60", className)}>
      {value.map((t) => (
        <span key={t} className="inline-flex items-center gap-1 rounded-full bg-secondary px-2 py-0.5 text-xs">
          {t}
          {!disabled && (
            <button type="button" aria-label={`Remove ${t}`} className="rounded-full hover:text-destructive" onClick={() => onChange(value.filter((x) => x !== t))}>
              <X className="h-3 w-3" />
            </button>
          )}
        </span>
      ))}
      <input
        id={inputId}
        aria-label={ariaLabel}
        disabled={disabled}
        value={draft}
        placeholder={value.length ? "" : placeholder}
        className="min-w-[8rem] flex-1 bg-transparent py-1 outline-none placeholder:text-muted-foreground"
        onChange={(e) => {
          const v = e.target.value;
          if (v.includes(",")) add(v);
          else setDraft(v);
        }}
        onKeyDown={(e) => {
          if (e.key === "Enter") { e.preventDefault(); add(draft); }
          else if (e.key === "Backspace" && !draft && value.length) onChange(value.slice(0, -1));
        }}
        onBlur={() => add(draft)}
      />
    </div>
  );
}

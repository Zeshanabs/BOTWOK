"use client";
import { useRef, useState } from "react";
import { X } from "lucide-react";
import { cn } from "@/lib/utils";

/** Chips + input. Enter / comma / Tab adds, Backspace on an empty input removes the last chip, paste splits on commas and newlines. */
export function TagInput({ value, onChange, id, ariaLabel, placeholder = "Add and press Enter", disabled, transform, className, max }: {
  value: string[]; onChange: (tags: string[]) => void; id?: string; ariaLabel?: string; placeholder?: string; disabled?: boolean;
  transform?: (s: string) => string; className?: string; max?: number;
}) {
  const [draft, setDraft] = useState("");
  const inputRef = useRef<HTMLInputElement>(null);

  function commit(raw: string) {
    const parts = raw.split(/[,\n]/).map((s) => s.trim()).filter(Boolean).map((s) => (transform ? transform(s) : s));
    if (parts.length === 0) return;
    const next = [...value];
    for (const p of parts) if (!next.includes(p) && (max == null || next.length < max)) next.push(p);
    if (next.length !== value.length) onChange(next);
    setDraft("");
  }
  function remove(i: number) { onChange(value.filter((_, j) => j !== i)); }

  return (
    <div
      className={cn(
        "flex min-h-9 w-full flex-wrap items-center gap-1.5 rounded-md border border-input bg-transparent px-2 py-1 text-sm shadow-xs transition-[color,box-shadow] focus-within:border-ring focus-within:ring-[3px] focus-within:ring-ring/50 dark:bg-input/30",
        disabled && "cursor-not-allowed opacity-50",
        className,
      )}
      onClick={() => inputRef.current?.focus()}
    >
      {value.map((t, i) => (
        <span key={`${t}-${i}`} className="inline-flex h-6 items-center gap-1 rounded-md bg-secondary pl-2 pr-1 text-xs font-medium text-secondary-foreground">
          {t}
          {!disabled && (
            <button type="button" aria-label={`Remove ${t}`} className="rounded p-0.5 text-muted-foreground hover:bg-foreground/10 hover:text-foreground" onClick={(e) => { e.stopPropagation(); remove(i); }}>
              <X className="h-3 w-3" />
            </button>
          )}
        </span>
      ))}
      <input
        ref={inputRef}
        id={id}
        aria-label={ariaLabel}
        disabled={disabled}
        value={draft}
        placeholder={value.length === 0 ? placeholder : ""}
        className="h-6 min-w-[8rem] flex-1 bg-transparent text-sm outline-none placeholder:text-muted-foreground disabled:cursor-not-allowed"
        onChange={(e) => setDraft(e.target.value)}
        onKeyDown={(e) => {
          if (e.key === "Enter" || e.key === "," || (e.key === "Tab" && draft.trim())) { e.preventDefault(); commit(draft); }
          else if (e.key === "Backspace" && !draft && value.length) remove(value.length - 1);
        }}
        onBlur={() => draft.trim() && commit(draft)}
        onPaste={(e) => { const text = e.clipboardData.getData("text"); if (/[,\n]/.test(text)) { e.preventDefault(); commit(text); } }}
      />
    </div>
  );
}

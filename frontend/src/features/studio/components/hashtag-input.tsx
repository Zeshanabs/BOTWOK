"use client";
import { useState } from "react";
import { X } from "lucide-react";
import { cn } from "@/lib/utils";
import { normalizeTag } from "../platform-rules";

/** Hashtag chip input: Enter/comma/space adds, Backspace removes the last chip; banned tags render red. */
export function HashtagInput({ value, onChange, banned = [], cap, recommended, disabled, id }: {
  value: string[]; onChange: (tags: string[]) => void; banned?: string[]; cap?: number; recommended?: number; disabled?: boolean; id?: string;
}) {
  const [draft, setDraft] = useState("");
  const bannedSet = new Set(banned.map((b) => normalizeTag(b).toLowerCase()));
  const add = (raw: string) => {
    const tags = raw.split(/[\s,]+/).map(normalizeTag).filter(Boolean);
    if (!tags.length) return;
    const existing = new Set(value.map((t) => t.toLowerCase()));
    onChange([...value, ...tags.filter((t) => !existing.has(t.toLowerCase()))]);
    setDraft("");
  };
  const over = cap != null && value.length > cap;
  return (
    <div>
      <div className={cn("flex min-h-9 flex-wrap items-center gap-1.5 rounded-md border bg-background px-2 py-1.5 focus-within:ring-[3px] focus-within:ring-ring/50", over && "border-destructive", disabled && "opacity-60")}>
        {value.map((t) => {
          const isBanned = bannedSet.has(t.toLowerCase());
          return (
            <span key={t} className={cn("inline-flex items-center gap-1 rounded-full px-2 py-0.5 text-xs", isBanned ? "bg-red-100 text-red-800 line-through dark:bg-red-900/40 dark:text-red-200" : "bg-secondary")} title={isBanned ? "Banned by brand policy" : undefined}>
              {t}
              {!disabled && <button type="button" aria-label={`Remove ${t}`} onClick={() => onChange(value.filter((x) => x !== t))} className="rounded-full hover:bg-black/10"><X className="h-3 w-3" /></button>}
            </span>
          );
        })}
        <input id={id} value={draft} disabled={disabled} onChange={(e) => setDraft(e.target.value)} placeholder={value.length ? "" : "#hashtag"}
               className="min-w-[90px] flex-1 bg-transparent text-sm outline-none" aria-label="Add hashtag"
               onKeyDown={(e) => {
                 if (e.key === "Enter" || e.key === "," || e.key === " ") { e.preventDefault(); add(draft); }
                 else if (e.key === "Backspace" && !draft && value.length) onChange(value.slice(0, -1));
               }}
               onBlur={() => draft && add(draft)}
               onPaste={(e) => { const t = e.clipboardData.getData("text"); if (/[\s,]/.test(t)) { e.preventDefault(); add(t); } }} />
      </div>
      {(cap != null || recommended != null) && (
        <p className={cn("mt-1 text-xs", over ? "text-red-600" : "text-muted-foreground")}>
          {value.length} hashtag{value.length === 1 ? "" : "s"}{cap != null ? ` · max ${cap}` : ""}{recommended != null ? ` · recommended ≤ ${recommended}` : ""}
        </p>
      )}
    </div>
  );
}

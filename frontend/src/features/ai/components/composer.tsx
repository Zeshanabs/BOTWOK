"use client";
/** Prompt composer with `/` slash commands and `@brand` mentions (doc 24 §6 Composer). */
import { useRef, useState } from "react";
import { AtSign, Send, Slash } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Textarea } from "@/components/ui/textarea";
import { cn } from "@/lib/utils";
import { useBrands } from "@/features/brand/hooks";

export interface SlashCommand { cmd: string; agent?: string; hint: string }

export const SLASH_COMMANDS: SlashCommand[] = [
  { cmd: "/research", agent: "research", hint: "Search the web & news, rank and cite sources" },
  { cmd: "/write", agent: "writer", hint: "Draft a post with hook, body, CTA and hashtags" },
  { cmd: "/ideas", agent: "ideation", hint: "Generate content ideas from your strategy" },
  { cmd: "/schedule", hint: "Propose a schedule — always waits for your approval" },
  { cmd: "/trends", agent: "trend", hint: "Detect and score trends for this brand" },
  { cmd: "/competitor", agent: "competitor_intel", hint: "Analyze competitors from allowed sources" },
  { cmd: "/plan", agent: "strategy", hint: "Pillars, mix and a posting plan" },
  { cmd: "/repurpose", agent: "repurposer", hint: "Turn one piece into per-platform variants" },
  { cmd: "/critique", agent: "critic", hint: "Score quality, brand fit and policy risk" },
  { cmd: "/factcheck", agent: "fact_check", hint: "Verify claims against sources" },
  { cmd: "/analyze", agent: "performance_analyst", hint: "Insights from your analytics" },
  { cmd: "/report", agent: "report", hint: "Compose a report from stored data" },
];

export interface Mention { type: "brand"; id: string; label: string }
export interface ComposerSubmit { message: string; agent?: string; mentions: Mention[] }

interface Suggestion { key: string; label: string; hint?: string; kind: "slash" | "brand"; start: number; insert: string; mention?: Mention }

export function Composer({ value, onChange, onSubmit, busy, disabled, placeholder, rows = 4, autoFocus, className, footer }: {
  value: string;
  onChange: (v: string) => void;
  onSubmit: (s: ComposerSubmit) => void;
  busy?: boolean;
  disabled?: boolean;
  placeholder?: string;
  rows?: number;
  autoFocus?: boolean;
  className?: string;
  footer?: React.ReactNode;
}) {
  const ref = useRef<HTMLTextAreaElement>(null);
  const brands = useBrands();
  const [caret, setCaret] = useState(0);
  const [active, setActive] = useState(0);
  const [dismissed, setDismissed] = useState(false);
  const [mentions, setMentions] = useState<Mention[]>([]);

  const beforeCaret = value.slice(0, caret);
  const slashMatch = /^\/(\w*)$/.exec(beforeCaret);
  const atMatch = /(^|\s)@([\w-]*)$/.exec(beforeCaret);

  function replaceBeforeCaret(start: number, insert: string) {
    const next = value.slice(0, start) + insert + value.slice(caret);
    onChange(next);
    const pos = start + insert.length;
    setCaret(pos);
    requestAnimationFrame(() => { ref.current?.focus(); ref.current?.setSelectionRange(pos, pos); });
  }

  function buildSuggestions(): Suggestion[] {
    if (dismissed) return [];
    if (slashMatch) {
      const q = slashMatch[1].toLowerCase();
      return SLASH_COMMANDS.filter((c) => c.cmd.slice(1).startsWith(q)).map((c) => ({
        key: c.cmd, label: c.cmd, hint: c.hint, kind: "slash" as const, start: 0, insert: `${c.cmd} `,
      }));
    }
    if (atMatch) {
      const q = atMatch[2].toLowerCase();
      const start = caret - atMatch[2].length - 1;
      return (brands.data ?? []).filter((b) => b.name.toLowerCase().includes(q)).slice(0, 8).map((b) => ({
        key: b.id, label: `@${b.name}`, hint: "Brand", kind: "brand" as const, start, insert: `@${b.name.replace(/\s+/g, "-")} `,
        mention: { type: "brand" as const, id: b.id, label: b.name },
      }));
    }
    return [];
  }

  function applySuggestion(sg: Suggestion | undefined) {
    if (!sg) return;
    const mention = sg.mention;
    if (mention) setMentions((m) => (m.some((x) => x.id === mention.id) ? m : [...m, mention]));
    replaceBeforeCaret(sg.start, sg.insert);
    setActive(0);
  }
  const suggestions = buildSuggestions();

  const open = suggestions.length > 0;
  const activeIdx = Math.min(active, Math.max(0, suggestions.length - 1));

  function submit() {
    const message = value.trim();
    if (!message || busy || disabled) return;
    const first = message.split(/\s+/)[0];
    const cmd = SLASH_COMMANDS.find((c) => c.cmd === first);
    const present = mentions.filter((m) => message.includes(`@${m.label.replace(/\s+/g, "-")}`));
    onSubmit({ message, agent: cmd?.agent, mentions: present });
  }

  return (
    <div className={cn("relative rounded-xl border bg-background shadow-xs focus-within:ring-[3px] focus-within:ring-ring/40", className)}>
      <Textarea
        ref={ref}
        value={value}
        rows={rows}
        autoFocus={autoFocus}
        disabled={disabled}
        aria-label="Message to the AI"
        aria-autocomplete="list"
        aria-expanded={open}
        aria-controls="composer-suggestions"
        placeholder={placeholder ?? "Ask anything — /research, /write, /ideas, /schedule · @brand to target a brand"}
        className="resize-none border-0 shadow-none focus-visible:ring-0"
        onChange={(e) => { onChange(e.target.value); setCaret(e.target.selectionStart ?? e.target.value.length); setDismissed(false); setActive(0); }}
        onSelect={(e) => setCaret(e.currentTarget.selectionStart ?? 0)}
        onKeyDown={(e) => {
          if (open) {
            if (e.key === "ArrowDown") { e.preventDefault(); setActive((activeIdx + 1) % suggestions.length); return; }
            if (e.key === "ArrowUp") { e.preventDefault(); setActive((activeIdx - 1 + suggestions.length) % suggestions.length); return; }
            if (e.key === "Enter" || e.key === "Tab") { e.preventDefault(); applySuggestion(suggestions[activeIdx]); return; }
            if (e.key === "Escape") { e.preventDefault(); setDismissed(true); return; }
          }
          if (e.key === "Enter" && (e.metaKey || e.ctrlKey)) { e.preventDefault(); submit(); }
        }}
      />
      {open && (
        <ul id="composer-suggestions" role="listbox" className="absolute bottom-full left-2 z-20 mb-1 max-h-64 w-[min(28rem,calc(100%-1rem))] overflow-y-auto rounded-lg border bg-popover p-1 text-sm shadow-lg">
          {suggestions.map((s, i) => (
            <li key={s.key} role="option" aria-selected={i === activeIdx}>
              <button type="button" className={cn("flex w-full items-baseline gap-2 rounded-md px-2 py-1.5 text-left", i === activeIdx ? "bg-accent" : "hover:bg-accent")}
                      onMouseDown={(e) => { e.preventDefault(); applySuggestion(s); }}>
                <span className="font-mono text-xs font-medium">{s.label}</span>
                {s.hint && <span className="truncate text-xs text-muted-foreground">{s.hint}</span>}
              </button>
            </li>
          ))}
        </ul>
      )}
      <div className="flex flex-wrap items-center gap-2 border-t px-3 py-2">
        <button type="button" className="inline-flex items-center gap-1 rounded px-1 text-xs text-muted-foreground hover:text-foreground" aria-label="Insert slash command"
                onClick={() => { if (!value.startsWith("/")) { onChange(`/${value}`); setCaret(1); setDismissed(false); } ref.current?.focus(); }}>
          <Slash className="h-3 w-3" /> commands
        </button>
        <button type="button" className="inline-flex items-center gap-1 rounded px-1 text-xs text-muted-foreground hover:text-foreground" aria-label="Mention a brand"
                onClick={() => { const next = `${value}${value && !value.endsWith(" ") ? " " : ""}@`; onChange(next); setCaret(next.length); setDismissed(false); ref.current?.focus(); }}>
          <AtSign className="h-3 w-3" /> brand
        </button>
        {footer}
        <span className="ml-auto hidden text-xs text-muted-foreground sm:inline">⌘↵ to run</span>
        <Button size="sm" onClick={submit} disabled={!value.trim() || busy || disabled}>
          <Send className="h-3 w-3" /> {busy ? "Starting…" : "Run"}
        </Button>
      </div>
    </div>
  );
}

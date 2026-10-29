"use client";
/** Contextual AI assistant available on every page (⌘J). Runs show the full transparency card: steps, sources, tools, cost. */
import { useEffect, useRef, useState } from "react";
import { useMutation } from "@tanstack/react-query";
import { ArrowUp, Loader2, Sparkles, X } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Textarea } from "@/components/ui/textarea";
import { RunCard } from "@/features/common/components/run-card";
import { errorMessage } from "@/features/common/utils";
import { api } from "@/lib/api";
import { cn } from "@/lib/utils";
import { useSession } from "@/stores/session";
import { useUI } from "@/stores/ui";

const SUGGESTIONS = [
  "Give me 10 LinkedIn post ideas for this week",
  "Summarize what competitors posted this month",
  "Draft a carousel from our latest research",
  "Which of our posts performed best and why?",
];

export function AiDrawer() {
  const { aiDrawerOpen, setAiDrawer } = useUI();
  const brandId = useSession((s) => s.brandId);
  const [message, setMessage] = useState("");
  const [runs, setRuns] = useState<{ id: string; prompt: string }[]>([]);
  const textareaRef = useRef<HTMLTextAreaElement>(null);
  const start = useMutation({
    mutationFn: (text: string) => api.post<{ run_id: string }>("/ai/runs", { message: text, brand_id: brandId, mode: "chat" }),
    onSuccess: (d, text) => { setRuns((r) => [{ id: d.run_id, prompt: text }, ...r].slice(0, 5)); setMessage(""); },
  });
  useEffect(() => {
    const h = (e: KeyboardEvent) => { if ((e.metaKey || e.ctrlKey) && e.key.toLowerCase() === "j") { e.preventDefault(); setAiDrawer(!aiDrawerOpen); } };
    window.addEventListener("keydown", h);
    return () => window.removeEventListener("keydown", h);
  }, [aiDrawerOpen, setAiDrawer]);
  useEffect(() => { if (aiDrawerOpen) textareaRef.current?.focus(); }, [aiDrawerOpen]);
  if (!aiDrawerOpen) return null;

  function submit(text = message) {
    const t = text.trim();
    if (!t || start.isPending) return;
    start.mutate(t);
  }

  return (
    <aside
      className={cn("fixed inset-0 z-50 flex flex-col bg-background md:static md:z-auto md:w-[400px] md:shrink-0 md:border-l xl:w-[440px]")}
      aria-label="AI assistant"
    >
      <div className="flex h-14 shrink-0 items-center justify-between border-b px-4">
        <div className="flex items-center gap-2.5">
          <span className="flex h-7 w-7 items-center justify-center rounded-lg bg-ai/12 text-ai"><Sparkles className="h-4 w-4" /></span>
          <div className="leading-tight">
            <p className="text-sm font-semibold">AI assistant</p>
            <p className="text-[11px] text-muted-foreground">Every step, source and cost is shown</p>
          </div>
        </div>
        <Button variant="ghost" size="icon" onClick={() => setAiDrawer(false)} aria-label="Close assistant"><X className="h-4 w-4" /></Button>
      </div>

      <div className="flex-1 space-y-3 overflow-y-auto p-4 text-sm">
        {runs.length === 0 && (
          <div className="space-y-3">
            <p className="text-muted-foreground">Ask for research, ideas, a draft or an analysis for the active brand. Try one of these:</p>
            <ul className="space-y-1.5">
              {SUGGESTIONS.map((s) => (
                <li key={s}>
                  <button type="button" onClick={() => submit(s)} className="w-full rounded-lg border bg-card px-3 py-2 text-left text-[13px] transition-colors hover:border-ai/40 hover:bg-ai/[0.06]">
                    <Sparkles className="mr-1.5 inline h-3 w-3 text-ai" aria-hidden />{s}
                  </button>
                </li>
              ))}
            </ul>
          </div>
        )}
        {runs.map((r) => (
          <div key={r.id} className="space-y-1.5">
            <p className="rounded-lg bg-muted px-3 py-2 text-[13px]">{r.prompt}</p>
            <RunCard runId={r.id} compact />
          </div>
        ))}
      </div>

      <form className="shrink-0 border-t p-3" onSubmit={(e) => { e.preventDefault(); submit(); }}>
        <div className="relative">
          <Textarea
            ref={textareaRef}
            value={message}
            onChange={(e) => setMessage(e.target.value)}
            onKeyDown={(e) => { if (e.key === "Enter" && !e.shiftKey) { e.preventDefault(); submit(); } }}
            placeholder="What should I do? e.g. Give me 10 LinkedIn post ideas"
            rows={3}
            className="resize-none pr-11"
            aria-label="Message to the AI assistant"
          />
          <Button type="submit" size="icon-sm" className="absolute bottom-2 right-2 rounded-full" disabled={start.isPending || !message.trim()} aria-label="Run">
            {start.isPending ? <Loader2 className="animate-spin" /> : <ArrowUp />}
          </Button>
        </div>
        <div className="mt-2 flex items-center justify-between text-[11px] text-muted-foreground">
          <span>Enter to send · Shift+Enter for a new line</span>
          <kbd className="rounded border bg-background px-1 font-mono text-[10px]">⌘J</kbd>
        </div>
        {start.isError && <p className="mt-1 text-xs text-destructive">{errorMessage(start.error)}</p>}
      </form>
    </aside>
  );
}

"use client";
/** Contextual AI drawer available on every page. Feature pages may register context via `aiDrawerContext`. */
import { useEffect, useState } from "react";
import { useMutation, useQuery } from "@tanstack/react-query";
import { Bot, Send, X } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Textarea } from "@/components/ui/textarea";
import { api } from "@/lib/api";
import { useSession } from "@/stores/session";
import { useUI } from "@/stores/ui";
import { StatusChip } from "@/components/data/status-chip";

interface RunTask { key: string; label: string; agent: string; status: string; duration_ms?: number; cost_usd?: number; sources_count?: number }
interface Run { id: string; status: string; plan?: { tasks: RunTask[] } | null; result?: { reasoning_summary?: string; deliverables?: unknown; sources?: unknown[] } | null; cost_usd?: number; error?: string | null }

export function AiDrawer() {
  const { aiDrawerOpen, setAiDrawer } = useUI();
  const brandId = useSession((s) => s.brandId);
  const [message, setMessage] = useState("");
  const [runId, setRunId] = useState<string | null>(null);
  const run = useQuery({ queryKey: ["ai", "runs", runId], queryFn: () => api.get<Run>(`/ai/runs/${runId}`), enabled: !!runId,
    refetchInterval: (q) => (["queued", "planning", "running"].includes(q.state.data?.status ?? "") ? 1500 : false) });
  const start = useMutation({ mutationFn: () => api.post<{ run_id: string }>("/ai/runs", { message, brand_id: brandId, mode: "chat" }), onSuccess: (d) => { setRunId(d.run_id); setMessage(""); } });
  useEffect(() => { const h = (e: KeyboardEvent) => { if ((e.metaKey || e.ctrlKey) && e.key.toLowerCase() === "j") { e.preventDefault(); setAiDrawer(!aiDrawerOpen); } }; window.addEventListener("keydown", h); return () => window.removeEventListener("keydown", h); }, [aiDrawerOpen, setAiDrawer]);
  if (!aiDrawerOpen) return null;
  return (
    <aside className="flex w-full flex-col border-l bg-background md:w-[400px]">
      <div className="flex h-14 items-center justify-between border-b px-4"><div className="flex items-center gap-2 font-medium"><Bot className="h-4 w-4 text-ai" /> AI assistant</div><Button variant="ghost" size="icon" onClick={() => setAiDrawer(false)} aria-label="Close"><X className="h-4 w-4" /></Button></div>
      <div className="flex-1 space-y-3 overflow-y-auto p-4 text-sm">
        {!runId && <p className="text-muted-foreground">Ask for research, ideas, a draft, or an analysis. Every step, source, and cost is shown.</p>}
        {run.data && (
          <div className="space-y-3">
            <div className="flex items-center justify-between"><StatusChip status={run.data.status} />{run.data.cost_usd != null && <span className="text-xs text-muted-foreground">${Number(run.data.cost_usd).toFixed(3)}</span>}</div>
            <ul className="space-y-1">{run.data.plan?.tasks?.map((t) => <li key={t.key} className="flex items-center gap-2"><span className="w-4 text-center">{t.status === "succeeded" ? "✓" : t.status === "failed" ? "✗" : t.status === "running" ? "⟳" : "·"}</span><span className="flex-1">{t.label}</span>{t.duration_ms != null && <span className="text-xs text-muted-foreground">{(t.duration_ms / 1000).toFixed(1)}s</span>}</li>)}</ul>
            {run.data.result?.reasoning_summary && <div className="rounded-md bg-muted p-3 whitespace-pre-wrap">{run.data.result.reasoning_summary}</div>}
            {run.data.error && <div className="rounded-md bg-red-50 p-3 text-red-800 dark:bg-red-900/30 dark:text-red-200">{run.data.error}</div>}
          </div>
        )}
      </div>
      <form className="border-t p-3" onSubmit={(e) => { e.preventDefault(); if (message.trim()) start.mutate(); }}>
        <Textarea value={message} onChange={(e) => setMessage(e.target.value)} placeholder="What should I do? e.g. Give me 10 LinkedIn post ideas" rows={3} />
        <div className="mt-2 flex justify-between"><span className="text-xs text-muted-foreground">⌘J toggles · Enter to send</span><Button size="sm" type="submit" disabled={start.isPending || !message.trim()}><Send className="mr-1 h-3 w-3" /> Run</Button></div>
        {start.isError && <p className="mt-1 text-xs text-red-600">{(start.error as Error).message}</p>}
      </form>
    </aside>
  );
}

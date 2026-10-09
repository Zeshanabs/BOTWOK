"use client";
/** Command Center (doc 24 §6): run history · new-run composer or run inspector. */
import { useState } from "react";
import { useRouter, useSearchParams } from "next/navigation";
import { toast } from "sonner";
import { Bot, History, ShieldCheck } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Sheet, SheetContent, SheetHeader, SheetTitle } from "@/components/ui/sheet";
import { PageHeader } from "@/components/shared/page-header";
import { errorMessage, isNotAvailable } from "@/components/shared/async-states";
import { ApiError } from "@/lib/api";
import { useCan } from "@/lib/permissions";
import { useSession } from "@/stores/session";
import { BrandSelect } from "@/features/brand/components/brand-select";
import { useActiveBrandId } from "@/features/brand/hooks";
import { useRun, useStartRun } from "../hooks";
import { Composer, SLASH_COMMANDS, type ComposerSubmit } from "./composer";
import { RunDetail } from "./run-detail";
import { RunHistory } from "./run-history";

const TEMPLATES = [
  "/research what changed in our industry this week, with sources",
  "/ideas 10 LinkedIn post ideas for next week",
  "/write a LinkedIn post announcing our new feature",
  "/competitor how did our competitors post on Instagram this month?",
];

function startErrorText(e: unknown): string {
  if (isNotAvailable(e)) return "AI runs aren't available yet — configure a provider in Settings › AI.";
  if (e instanceof ApiError && e.code === "budget_exceeded") return "Budget exceeded — raise the cap in Settings › AI or wait for the next period.";
  if (e instanceof ApiError && e.code === "clarification_required") return `The assistant needs more detail: ${e.problem.detail ?? ""}`;
  return errorMessage(e);
}

function FollowUp({ runId }: { runId: string }) {
  const router = useRouter();
  const slug = useSession((s) => s.workspaceSlug);
  const can = useCan();
  const run = useRun(runId);
  const start = useStartRun();
  const [text, setText] = useState("");
  if (!can.create) return null;
  function submit(s: ComposerSubmit) {
    start.mutate(
      { message: s.message, mode: "task", agent: s.agent, brand_id: s.mentions[0]?.id ?? run.data?.brand_id, conversation_id: run.data?.conversation_id, context: { mentions: s.mentions, previous_run_id: runId } },
      { onSuccess: (d) => { setText(""); router.push(`/w/${slug}/command-center/${d.run_id}`); }, onError: (e) => toast.error(startErrorText(e)) },
    );
  }
  return <Composer value={text} onChange={setText} onSubmit={submit} busy={start.isPending} rows={2} placeholder="Follow up… /command @brand" />;
}

function NewRun() {
  const router = useRouter();
  const sp = useSearchParams();
  const slug = useSession((s) => s.workspaceSlug);
  const can = useCan();
  const activeBrand = useActiveBrandId();
  const start = useStartRun();
  const [text, setText] = useState(() => sp.get("prompt") ?? "");
  const [brandId, setBrandId] = useState<string | null>(null);
  const [budget, setBudget] = useState("");

  function submit(s: ComposerSubmit) {
    const b = Number(budget);
    start.mutate(
      { message: s.message, mode: "task", agent: s.agent, brand_id: s.mentions[0]?.id ?? brandId ?? activeBrand, budget_usd: budget && b > 0 ? b : undefined, context: s.mentions.length ? { mentions: s.mentions } : undefined },
      { onSuccess: (d) => router.push(`/w/${slug}/command-center/${d.run_id}`), onError: (e) => toast.error(startErrorText(e)) },
    );
  }

  return (
    <div className="mx-auto max-w-3xl space-y-6 py-4">
      <div className="text-center">
        <Bot className="mx-auto h-10 w-10 text-ai" aria-hidden />
        <h2 className="mt-2 text-xl font-semibold">What should Botwok do?</h2>
        <p className="mt-1 text-sm text-muted-foreground">Runs plan their own steps. Anything that posts, schedules or changes settings waits for your approval.</p>
      </div>
      {can.create ? (
        <>
          <Composer value={text} onChange={setText} onSubmit={submit} busy={start.isPending} autoFocus rows={5}
                    footer={
                      <div className="flex flex-wrap items-center gap-2">
                        <Label htmlFor="cc-brand" className="sr-only">Brand</Label>
                        <BrandSelect id="cc-brand" value={brandId ?? activeBrand} onChange={setBrandId} className="h-7 w-40 text-xs" />
                        <Label htmlFor="cc-budget" className="sr-only">Per-run budget (USD)</Label>
                        <Input id="cc-budget" inputMode="decimal" value={budget} onChange={(e) => setBudget(e.target.value.replace(/[^0-9.]/g, ""))} placeholder="Budget $ (optional)" className="h-7 w-36 text-xs" />
                      </div>
                    } />
          {start.error != null && <p role="alert" className="text-sm text-destructive">{startErrorText(start.error)}</p>}
        </>
      ) : <p className="rounded-lg border p-4 text-center text-sm text-muted-foreground">Viewers can inspect runs but can&apos;t start them.</p>}
      <div className="grid gap-4 sm:grid-cols-2">
        <section className="rounded-xl border p-4">
          <h3 className="mb-2 text-sm font-semibold">Slash commands</h3>
          <ul className="space-y-1 text-xs">
            {SLASH_COMMANDS.slice(0, 8).map((c) => (
              <li key={c.cmd}><button type="button" className="font-mono text-primary hover:underline" onClick={() => setText(`${c.cmd} `)}>{c.cmd}</button> <span className="text-muted-foreground">{c.hint}</span></li>
            ))}
          </ul>
        </section>
        <section className="rounded-xl border p-4">
          <h3 className="mb-2 text-sm font-semibold">Templates</h3>
          <ul className="space-y-1.5">
            {TEMPLATES.map((t) => <li key={t}><button type="button" className="text-left text-xs hover:text-primary" onClick={() => setText(t)}>{t}</button></li>)}
          </ul>
          <p className="mt-3 flex items-center gap-1 text-xs text-muted-foreground"><ShieldCheck className="h-3 w-3" /> Side effects are always proposed for approval.</p>
        </section>
      </div>
    </div>
  );
}

export function CommandCenter({ runId }: { runId?: string }) {
  const [historyOpen, setHistoryOpen] = useState(false);
  return (
    <div>
      <PageHeader title="Command Center" description="Plan, run and inspect AI work — every step, source, tool call and cost."
                  actions={<Button variant="outline" size="sm" className="lg:hidden" onClick={() => setHistoryOpen(true)}><History className="h-4 w-4" /> Runs</Button>} />
      <div className="grid gap-6 lg:grid-cols-[250px_minmax(0,1fr)]">
        <aside className="hidden h-[calc(100vh-12rem)] lg:block" aria-label="Run history"><RunHistory activeId={runId} /></aside>
        <div className="min-w-0">
          {runId ? <RunDetail key={runId} runId={runId} followUp={<FollowUp runId={runId} />} /> : <NewRun />}
        </div>
      </div>
      <Sheet open={historyOpen} onOpenChange={setHistoryOpen}>
        <SheetContent side="left" className="w-80">
          <SheetHeader><SheetTitle>Runs</SheetTitle></SheetHeader>
          <div className="h-full px-4 pb-4"><RunHistory activeId={runId} onNavigate={() => setHistoryOpen(false)} /></div>
        </SheetContent>
      </Sheet>
    </div>
  );
}

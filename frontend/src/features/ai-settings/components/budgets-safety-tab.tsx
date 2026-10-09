"use client";
import { useState } from "react";
import { toast } from "sonner";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Switch } from "@/components/ui/switch";
import { FieldError, FormError, problemFieldErrors } from "@/components/data/form-errors";
import { errorMessage } from "@/components/data/async-states";
import { useSaveAiSettings } from "../hooks";
import type { AiSettings } from "../types";

const num = (s: string) => (s.trim() === "" ? null : Math.max(0, Number(s)));
const str = (n: number | null | undefined) => (n == null ? "" : String(n));

export function BudgetsSafetyTab({ settings, readOnly }: { settings: AiSettings; readOnly: boolean }) {
  const save = useSaveAiSettings();
  const b = settings.budgets ?? {};
  const s = settings.safety ?? {};
  const [perRun, setPerRun] = useState(str(b.per_run_usd));
  const [daily, setDaily] = useState(str(b.daily_usd));
  const [monthly, setMonthly] = useState(str(b.monthly_usd));
  const [confirmAbove, setConfirmAbove] = useState(str(b.confirm_above_usd));
  const [threshold, setThreshold] = useState<boolean>(s.auto_approve === "threshold" || s.auto_approve === "score_threshold");
  const [criticMin, setCriticMin] = useState(str(s.critic_threshold ?? 85));
  const [requireSources, setRequireSources] = useState<boolean>(s.require_sources ?? true);
  const [blockFact, setBlockFact] = useState<boolean>(s.block_on_failed_fact_check ?? true);
  const [maxSteps, setMaxSteps] = useState(str(s.max_steps ?? 20));
  const errors = problemFieldErrors(save.error);

  function onSave() {
    save.mutate({
      budgets: { ...b, per_run_usd: num(perRun), daily_usd: num(daily), monthly_usd: num(monthly), confirm_above_usd: num(confirmAbove) },
      safety: { ...s, auto_approve: threshold ? "threshold" : "never", critic_threshold: threshold ? num(criticMin) : s.critic_threshold ?? null, require_sources: requireSources, block_on_failed_fact_check: blockFact, max_steps: num(maxSteps) },
    }, { onSuccess: () => toast.success("Budgets & safety saved"), onError: (e) => toast.error(errorMessage(e)) });
  }

  const money = (id: string, label: string, value: string, set: (v: string) => void, hint: string) => (
    <div className="space-y-1">
      <Label htmlFor={id}>{label}</Label>
      <div className="flex items-center gap-1"><span className="text-sm text-muted-foreground">$</span><Input id={id} inputMode="decimal" value={value} onChange={(e) => set(e.target.value.replace(/[^0-9.]/g, ""))} disabled={readOnly} placeholder="no cap" aria-invalid={!!errors[id]} /></div>
      <p className="text-xs text-muted-foreground">{hint}</p>
      <FieldError errors={errors} name={id} />
    </div>
  );

  return (
    <div className="space-y-6">
      <Card>
        <CardHeader><CardTitle className="text-sm">Budgets</CardTitle><CardDescription>Runs are refused (or paused mid-run) when a cap would be exceeded; alerts fire at 80%.</CardDescription></CardHeader>
        <CardContent className="grid gap-4 sm:grid-cols-2">
          {money("per_run_usd", "Per run", perRun, setPerRun, "Default $1.50")}
          {money("confirm_above_usd", "Confirm plans above", confirmAbove, setConfirmAbove, "Runs estimated above this wait for your OK (default $2)")}
          {money("daily_usd", "Per day (workspace)", daily, setDaily, "Hard cap across all runs")}
          {money("monthly_usd", "Per month (workspace)", monthly, setMonthly, "Hard cap across all runs")}
        </CardContent>
      </Card>
      <Card>
        <CardHeader><CardTitle className="text-sm">Approvals & safety</CardTitle><CardDescription>Publishing always requires an approved variant; these rules decide what may skip human review.</CardDescription></CardHeader>
        <CardContent className="space-y-4 text-sm">
          <div className="space-y-2">
            <p className="font-medium">Auto-approve</p>
            <label className="flex items-center gap-2"><input type="radio" name="auto" checked={!threshold} onChange={() => setThreshold(false)} disabled={readOnly} className="accent-[var(--primary)]" /> Never (default) — every AI draft needs a human approver</label>
            <label className="flex items-center gap-2"><input type="radio" name="auto" checked={threshold} onChange={() => setThreshold(true)} disabled={readOnly} className="accent-[var(--primary)]" /> When critic score ≥
              <Input aria-label="Critic score threshold" className="h-8 w-20" inputMode="numeric" value={criticMin} onChange={(e) => setCriticMin(e.target.value.replace(/[^0-9]/g, ""))} disabled={readOnly || !threshold} /> and no failed fact-check or policy risk</label>
          </div>
          <label className="flex items-center gap-2"><Switch checked={requireSources} onCheckedChange={setRequireSources} disabled={readOnly} /> Require sources for factual claims</label>
          <label className="flex items-center gap-2"><Switch checked={blockFact} onCheckedChange={setBlockFact} disabled={readOnly} /> Block publishing when a fact-check fails</label>
          <div className="flex items-center gap-2"><Label htmlFor="max-steps">Max autonomous steps per run</Label><Input id="max-steps" className="h-8 w-20" inputMode="numeric" value={maxSteps} onChange={(e) => setMaxSteps(e.target.value.replace(/[^0-9]/g, ""))} disabled={readOnly} /></div>
        </CardContent>
      </Card>
      <FormError error={Object.keys(errors).length ? null : save.error} />
      {!readOnly && <div className="flex justify-end"><Button onClick={onSave} disabled={save.isPending}>{save.isPending ? "Saving…" : "Save budgets & safety"}</Button></div>}
    </div>
  );
}

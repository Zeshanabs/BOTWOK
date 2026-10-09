"use client";
import { usePathname, useRouter, useSearchParams } from "next/navigation";
import { Skeleton } from "@/components/ui/skeleton";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { PageHeader } from "@/components/data/page-header";
import { QueryError } from "@/components/data/async-states";
import { fmtRelative } from "@/lib/formatters";
import { useCan } from "@/lib/permissions";
import { useAiSettings } from "../hooks";
import { BudgetsSafetyTab } from "./budgets-safety-tab";
import { PromptsTab } from "./prompts-tab";
import { ProvidersTab } from "./providers-tab";
import { UsageTab } from "./usage-tab";

const TABS = [{ id: "providers", label: "Providers & routing" }, { id: "budgets", label: "Budgets & safety" }, { id: "prompts", label: "Prompts" }, { id: "usage", label: "Usage & cost" }];

export function AiSettingsView() {
  const router = useRouter();
  const pathname = usePathname();
  const sp = useSearchParams();
  const can = useCan();
  const q = useAiSettings();
  const tab = TABS.some((t) => t.id === sp.get("tab")) ? (sp.get("tab") as string) : "providers";
  const readOnly = !can.manage;

  return (
    <div>
      <PageHeader title="AI Settings" description={readOnly ? "Read-only — owners and admins can change providers, routing, budgets and prompts." : "Providers, routing, local models, budgets, approval thresholds and prompt templates."} />
      <Tabs value={tab} onValueChange={(t) => router.replace(`${pathname}?tab=${t}`)}>
        <div className="overflow-x-auto"><TabsList>{TABS.map((t) => <TabsTrigger key={t.id} value={t.id}>{t.label}</TabsTrigger>)}</TabsList></div>
        {q.data?.updated_at && <p className="mt-1 text-xs text-muted-foreground">Last changed {fmtRelative(q.data.updated_at)}{q.data.updated_by?.full_name ? ` by ${q.data.updated_by.full_name}` : ""}</p>}
        {(tab === "providers" || tab === "budgets") && (q.isLoading ? <div className="mt-4 space-y-3"><Skeleton className="h-40" /><Skeleton className="h-64" /></div> : q.error ? (
          <QueryError className="mt-4" error={q.error} onRetry={() => q.refetch()} title="Couldn't load AI settings" notAvailableText="AI settings aren't available on this install yet." />
        ) : null)}
        <TabsContent value="providers" className="mt-4">{q.data && <ProvidersTab settings={q.data} readOnly={readOnly} />}</TabsContent>
        <TabsContent value="budgets" className="mt-4">{q.data && <BudgetsSafetyTab settings={q.data} readOnly={readOnly} />}</TabsContent>
        <TabsContent value="prompts" className="mt-4"><PromptsTab readOnly={readOnly} /></TabsContent>
        <TabsContent value="usage" className="mt-4"><UsageTab /></TabsContent>
      </Tabs>
    </div>
  );
}

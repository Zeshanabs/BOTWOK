"use client";
import { useState } from "react";
import { usePathname, useRouter, useSearchParams } from "next/navigation";
import { Plus, Search } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Sheet, SheetContent, SheetHeader, SheetTitle } from "@/components/ui/sheet";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { PageHeader } from "@/components/shared/page-header";
import { useActiveBrandId, useBrands, usePillars } from "@/features/brand/hooks";
import { useCan } from "@/lib/permissions";
import { ResearchForm } from "./research-form";
import { ResearchHistory } from "./research-history";
import { ResearchResults } from "./research-results";

export function ResearchView() {
  const router = useRouter();
  const pathname = usePathname();
  const sp = useSearchParams();
  const can = useCan();
  const brandId = useActiveBrandId();
  const brands = useBrands();
  const pillars = usePillars(brandId);
  const runId = sp.get("run");
  const tab = sp.get("tab") ?? "results";
  const [formKey, setFormKey] = useState(0);
  const [prefill, setPrefill] = useState<string | undefined>(sp.get("q") ?? undefined);
  const [mobileForm, setMobileForm] = useState(false);
  const brandName = brands.data?.find((b) => b.id === brandId)?.name;

  function setParams(next: Record<string, string | null>) {
    const p = new URLSearchParams(sp.toString());
    for (const [k, v] of Object.entries(next)) { if (v === null) p.delete(k); else p.set(k, v); }
    router.replace(`${pathname}?${p.toString()}`);
  }
  const openRun = (id: string) => { setMobileForm(false); setParams({ run: id, tab: "results" }); };
  const examples = (pillars.data ?? []).slice(0, 3).map((p) => `What's new in ${p.name.toLowerCase()} this month?`);
  const exampleQueries = examples.length ? examples : ["Latest trends in our industry this month", "What are customers asking about our category?", "Recent news about our top competitors"];

  const form = (
    <ResearchForm key={formKey} defaultBrandId={brandId} initial={prefill ? { query: prefill } : undefined} onStarted={openRun} />
  );

  return (
    <div>
      <PageHeader
        title={`Research${brandName ? ` · ${brandName}` : ""}`}
        description="Find, rank, dedupe and summarize sources — every claim cites where it came from."
        actions={can.create ? <Button className="lg:hidden" onClick={() => setMobileForm(true)}><Plus className="h-4 w-4" /> New run</Button> : undefined}
      />
      <div className="grid gap-6 lg:grid-cols-[320px_minmax(0,1fr)]">
        <Card className="hidden h-fit lg:block">
          <CardHeader><CardTitle className="text-base">New run</CardTitle></CardHeader>
          <CardContent>{form}</CardContent>
        </Card>
        <Tabs value={tab} onValueChange={(v) => setParams({ tab: v })} className="min-w-0">
          <TabsList>
            <TabsTrigger value="results">Results</TabsTrigger>
            <TabsTrigger value="history">History</TabsTrigger>
          </TabsList>
          <TabsContent value="results" className="mt-3">
            {runId ? <ResearchResults runId={runId} /> : (
              <div className="rounded-xl border border-dashed p-8 text-center">
                <Search className="mx-auto mb-3 h-8 w-8 text-muted-foreground" />
                <p className="font-medium">No research selected</p>
                <p className="mt-1 text-sm text-muted-foreground">Start a run or pick one from History. Try one of these:</p>
                <div className="mt-4 flex flex-wrap justify-center gap-2">
                  {exampleQueries.map((q) => (
                    <Button key={q} variant="outline" size="sm" disabled={!can.create} onClick={() => { setPrefill(q); setFormKey((k) => k + 1); setMobileForm(window.innerWidth < 1024); }}>{q}</Button>
                  ))}
                </div>
              </div>
            )}
          </TabsContent>
          <TabsContent value="history" className="mt-3">
            <ResearchHistory brandId={brandId} onOpen={openRun} onNew={() => setMobileForm(true)} />
          </TabsContent>
        </Tabs>
      </div>
      <Sheet open={mobileForm} onOpenChange={setMobileForm}>
        <SheetContent side="bottom" className="max-h-[90vh] overflow-y-auto">
          <SheetHeader><SheetTitle>New research run</SheetTitle></SheetHeader>
          <div className="px-4 pb-6">{form}</div>
        </SheetContent>
      </Sheet>
    </div>
  );
}

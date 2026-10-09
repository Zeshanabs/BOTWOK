"use client";
import { useState } from "react";
import { usePathname, useRouter, useSearchParams } from "next/navigation";
import { Globe, History, Palette } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Dialog, DialogContent, DialogDescription, DialogHeader, DialogTitle } from "@/components/ui/dialog";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { Skeleton } from "@/components/ui/skeleton";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { Tooltip, TooltipContent, TooltipProvider, TooltipTrigger } from "@/components/ui/tooltip";
import { PageHeader } from "@/components/data/page-header";
import { EmptyState } from "@/components/data/empty-state";
import { QueryError } from "@/components/data/async-states";
import { useCan } from "@/lib/permissions";
import { useSession } from "@/stores/session";
import { useActiveBrandId, useBrand, useBrandSettings, useBrands } from "../hooks";
import { BrandBasicsForm } from "./brand-basics-form";
import { ContextPreview } from "./context-preview";
import { ImportFromWebsite } from "./import-from-website";
import { PillarsSection } from "./pillars-section";
import { AudienceSection, ProfileSection, VoiceSection } from "./sections-profile";
import { GoalsSection, KeywordsSection, VisualSection } from "./sections-visual";

const TABS = [
  { id: "profile", label: "Profile" }, { id: "audience", label: "Audience" }, { id: "voice", label: "Voice & Style" }, { id: "visual", label: "Visual Identity" },
  { id: "pillars", label: "Content Pillars" }, { id: "keywords", label: "Keywords · Hashtags · CTAs" }, { id: "goals", label: "Goals" },
];

function NewBrand() {
  const router = useRouter();
  const pathname = usePathname();
  const setBrand = useSession((s) => s.setBrand);
  const can = useCan();
  if (!can.manage) return <EmptyState icon={Palette} title="Only owners and admins can create brands" />;
  return (
    <div className="mx-auto max-w-2xl">
      <PageHeader title="New brand" description="A brand holds voice, pillars and connected accounts. You can import the rest from its website next." />
      <Card><CardContent className="pt-6">
        <BrandBasicsForm onCreated={(b) => { setBrand(b.id); router.replace(`${pathname}?tab=profile&import=1`); }}
                         footer={<Button type="button" variant="ghost" onClick={() => router.replace(pathname)}>Cancel</Button>} />
      </CardContent></Card>
    </div>
  );
}

export function BrandSettingsView() {
  const router = useRouter();
  const pathname = usePathname();
  const sp = useSearchParams();
  const can = useCan();
  const brands = useBrands();
  const brandId = useActiveBrandId();
  const brand = useBrand(brandId);
  const settings = useBrandSettings(brandId);
  const [importState, setImportState] = useState(false);
  const importOpen = importState || sp.get("import") === "1";
  const [rev, setRev] = useState(0);
  const tab = sp.get("tab") ?? "profile";
  const readOnly = !can.manage;

  function setImportOpen(o: boolean) {
    setImportState(o);
    if (!o && sp.get("import")) {
      const p = new URLSearchParams(sp.toString());
      p.delete("import");
      router.replace(`${pathname}?${p.toString()}`);
    }
  }

  function setTab(t: string) {
    const p = new URLSearchParams(sp.toString());
    p.set("tab", t); p.delete("import");
    router.replace(`${pathname}?${p.toString()}`);
  }

  if (sp.get("new") === "1") return <NewBrand />;
  if (brands.isLoading || (brandId && (brand.isLoading || settings.isLoading))) {
    return <div className="space-y-4"><Skeleton className="h-8 w-72" /><Skeleton className="h-9 w-full" /><Skeleton className="h-96 w-full" /></div>;
  }
  if (brands.error) return <QueryError error={brands.error} onRetry={() => brands.refetch()} title="Couldn't load brands" />;
  if (!brandId) {
    return <EmptyState icon={Palette} title="No brands yet" description="A brand holds voice, pillars and connected accounts. Every agent reads its context."
                       action={can.manage ? { label: "New brand", onClick: () => router.replace(`${pathname}?new=1`) } : undefined} />;
  }
  if (brand.error || settings.error || !brand.data) {
    return <QueryError error={brand.error ?? settings.error} onRetry={() => { brand.refetch(); settings.refetch(); }} title="Couldn't load brand settings" />;
  }
  const b = brand.data;
  const s = settings.data ?? {};

  return (
    <div>
      <PageHeader
        title={`Brand Settings · ${b.name}`}
        description="Everything here is compiled into the BrandContext every agent receives."
        actions={
          <>
            {can.manage && <Button variant="outline" size="sm" onClick={() => setImportOpen(true)}><Globe className="h-4 w-4" /> <span className="text-ai">✦</span> Import from website</Button>}
            <TooltipProvider>
              <Tooltip>
                <TooltipTrigger asChild><span tabIndex={0}><Button variant="outline" size="sm" disabled><History className="h-4 w-4" /> Learn from my past posts</Button></span></TooltipTrigger>
                <TooltipContent className="max-w-xs">Not available yet — needs a connected account with post history and the analytics sync.</TooltipContent>
              </Tooltip>
            </TooltipProvider>
          </>
        }
      />
      <div className="grid gap-6 xl:grid-cols-[minmax(0,1fr)_380px]">
        <Tabs value={tab} onValueChange={setTab} className="min-w-0">
          <div className="md:hidden">
            <Select value={tab} onValueChange={setTab}>
              <SelectTrigger className="w-full" aria-label="Section"><SelectValue /></SelectTrigger>
              <SelectContent>{TABS.map((t) => <SelectItem key={t.id} value={t.id}>{t.label}</SelectItem>)}</SelectContent>
            </Select>
          </div>
          <div className="hidden overflow-x-auto md:block"><TabsList>{TABS.map((t) => <TabsTrigger key={t.id} value={t.id}>{t.label}</TabsTrigger>)}</TabsList></div>
          <Card className="mt-3">
            <CardHeader><CardTitle className="text-base">{TABS.find((t) => t.id === tab)?.label}</CardTitle></CardHeader>
            <CardContent>
              {/* forceMount keeps unsaved edits when switching tabs */}
              <TabsContent forceMount value="profile" className="data-[state=inactive]:hidden"><ProfileSection key={`${b.id}-${rev}`} brand={b} settings={s} readOnly={readOnly} /></TabsContent>
              <TabsContent forceMount value="audience" className="data-[state=inactive]:hidden"><AudienceSection key={`${b.id}-${rev}`} brand={b} settings={s} readOnly={readOnly} /></TabsContent>
              <TabsContent forceMount value="voice" className="data-[state=inactive]:hidden"><VoiceSection key={`${b.id}-${rev}`} brand={b} settings={s} readOnly={readOnly} /></TabsContent>
              <TabsContent forceMount value="visual" className="data-[state=inactive]:hidden"><VisualSection key={`${b.id}-${rev}`} brand={b} settings={s} readOnly={readOnly} /></TabsContent>
              <TabsContent forceMount value="pillars" className="data-[state=inactive]:hidden"><PillarsSection key={b.id} brandId={b.id} readOnly={readOnly} /></TabsContent>
              <TabsContent forceMount value="keywords" className="data-[state=inactive]:hidden"><KeywordsSection key={`${b.id}-${rev}`} brand={b} settings={s} readOnly={readOnly} /></TabsContent>
              <TabsContent forceMount value="goals" className="data-[state=inactive]:hidden"><GoalsSection key={`${b.id}-${rev}`} brand={b} settings={s} readOnly={readOnly} /></TabsContent>
            </CardContent>
          </Card>
        </Tabs>
        <aside className="min-w-0 xl:sticky xl:top-0 xl:self-start"><ContextPreview brandId={b.id} /></aside>
      </div>
      <Dialog open={importOpen} onOpenChange={setImportOpen}>
        <DialogContent className="max-h-[90vh] overflow-y-auto sm:max-w-2xl">
          <DialogHeader>
            <DialogTitle><span className="text-ai">✦</span> Import from website</DialogTitle>
            <DialogDescription>Proposals are shown per field; accept only what&apos;s right.</DialogDescription>
          </DialogHeader>
          <ImportFromWebsite key={`${b.id}-${importOpen}`} brandId={b.id} defaultUrl={b.website} onSkip={() => setImportOpen(false)} skipLabel="Close"
                             onDone={async () => { await Promise.all([settings.refetch(), brand.refetch()]); setRev((r) => r + 1); }} />
        </DialogContent>
      </Dialog>
    </div>
  );
}

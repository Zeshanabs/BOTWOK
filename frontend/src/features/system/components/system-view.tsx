"use client";
import { usePathname, useRouter, useSearchParams } from "next/navigation";
import { Card, CardContent } from "@/components/ui/card";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { PageHeader } from "@/components/data/page-header";
import { useCan } from "@/lib/permissions";
import { cn } from "@/lib/utils";
import { useSession } from "@/stores/session";
import { AdminPanel } from "./admin-panel";
import { GeneralSection } from "./general-section";
import { ApiKeysSection, DangerZone, ExportSection, NotificationsSection } from "./sections";

export function SystemView() {
  const router = useRouter();
  const pathname = usePathname();
  const sp = useSearchParams();
  const can = useCan();
  const wsName = useSession((s) => s.memberships.find((m) => m.workspace.id === s.workspaceId)?.workspace.name);
  const sections = [
    { id: "general", label: "General" },
    { id: "notifications", label: "Notifications" },
    ...(can.manage ? [{ id: "api-keys", label: "API keys" }] : []),
    { id: "export", label: "Export & backup" },
    { id: "danger", label: "Danger zone" },
    ...(can.manage ? [{ id: "admin", label: "Admin / Debug" }] : []),
  ];
  const requested = sp.get("tab") ?? sp.get("section") ?? "general";
  const tab = sections.some((s) => s.id === requested) ? requested : "general";
  const go = (id: string) => router.replace(`${pathname}?tab=${id}`);

  return (
    <div>
      <PageHeader title={`System Settings${wsName ? ` · ${wsName}` : ""}`} description="Workspace-wide configuration, notifications, keys, exports and the admin console." />
      <div className="grid gap-6 md:grid-cols-[180px_minmax(0,1fr)]">
        <nav aria-label="System sections" className="hidden md:block">
          <ul className="space-y-0.5">
            {sections.map((s) => (
              <li key={s.id}>
                <button type="button" onClick={() => go(s.id)} aria-current={tab === s.id ? "page" : undefined}
                        className={cn("w-full rounded-md px-2 py-1.5 text-left text-sm", tab === s.id ? "bg-accent font-medium" : "text-muted-foreground hover:bg-accent hover:text-foreground", s.id === "danger" && "text-destructive")}>{s.label}</button>
              </li>
            ))}
          </ul>
        </nav>
        <div className="md:hidden">
          <Select value={tab} onValueChange={go}>
            <SelectTrigger className="w-full" aria-label="Section"><SelectValue /></SelectTrigger>
            <SelectContent>{sections.map((s) => <SelectItem key={s.id} value={s.id}>{s.label}</SelectItem>)}</SelectContent>
          </Select>
        </div>
        <Card className="min-w-0">
          <CardContent className="pt-6">
            <h2 className="mb-4 text-base font-semibold">{sections.find((s) => s.id === tab)?.label}</h2>
            {tab === "general" && <GeneralSection />}
            {tab === "notifications" && <NotificationsSection />}
            {tab === "api-keys" && <ApiKeysSection />}
            {tab === "export" && <ExportSection />}
            {tab === "danger" && <DangerZone />}
            {tab === "admin" && <AdminPanel />}
          </CardContent>
        </Card>
      </div>
    </div>
  );
}

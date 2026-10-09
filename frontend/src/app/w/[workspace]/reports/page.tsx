import { Suspense } from "react";
import { ReportsList } from "@/features/reports/components/reports-list";

export default function ReportsPage() {
  return (
    <Suspense fallback={<div className="text-sm text-muted-foreground">Loading reports…</div>}>
      <ReportsList />
    </Suspense>
  );
}

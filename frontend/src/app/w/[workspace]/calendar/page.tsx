import { Suspense } from "react";
import { CalendarPage } from "@/features/calendar/components/calendar-page";

export default function Calendar() {
  return (
    <Suspense fallback={<div className="text-sm text-muted-foreground">Loading calendar…</div>}>
      <CalendarPage />
    </Suspense>
  );
}

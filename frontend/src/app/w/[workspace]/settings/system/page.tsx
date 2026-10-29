import { Suspense } from "react";
import { ListSkeleton } from "@/components/shared/async-states";
import { SystemView } from "@/features/system/components/system-view";

export default function SystemSettingsPage() {
  return <Suspense fallback={<ListSkeleton rows={4} />}><SystemView /></Suspense>;
}

import { Suspense } from "react";
import { ListSkeleton } from "@/components/data/async-states";
import { SystemView } from "@/features/system/components/system-view";

export default function SystemSettingsPage() {
  return <Suspense fallback={<ListSkeleton rows={4} />}><SystemView /></Suspense>;
}

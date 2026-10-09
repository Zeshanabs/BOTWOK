import { Suspense } from "react";
import { ListSkeleton } from "@/components/shared/async-states";
import { CompareView } from "@/features/competitors/components/compare-view";

export default function CompareCompetitorsPage() {
  return <Suspense fallback={<ListSkeleton rows={6} />}><CompareView /></Suspense>;
}

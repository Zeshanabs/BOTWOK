import { Suspense } from "react";
import { ListSkeleton } from "@/components/data/async-states";
import { CompareView } from "@/features/competitors/components/compare-view";

export default function CompareCompetitorsPage() {
  return <Suspense fallback={<ListSkeleton rows={6} />}><CompareView /></Suspense>;
}

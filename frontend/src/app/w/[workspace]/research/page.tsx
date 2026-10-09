import { Suspense } from "react";
import { ListSkeleton } from "@/components/shared/async-states";
import { ResearchView } from "@/features/research/components/research-view";

export default function ResearchPage() {
  return <Suspense fallback={<ListSkeleton rows={6} />}><ResearchView /></Suspense>;
}

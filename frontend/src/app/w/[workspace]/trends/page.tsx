import { Suspense } from "react";
import { CardGridSkeleton } from "@/components/shared/async-states";
import { TrendsView } from "@/features/trends/components/trends-view";

export default function TrendsPage() {
  return <Suspense fallback={<CardGridSkeleton count={4} />}><TrendsView /></Suspense>;
}

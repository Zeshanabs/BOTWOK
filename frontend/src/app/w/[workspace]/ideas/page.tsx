import { Suspense } from "react";
import { CardGridSkeleton } from "@/components/data/async-states";
import { IdeasView } from "@/features/ideas/components/ideas-view";

export default function IdeasPage() {
  return <Suspense fallback={<CardGridSkeleton count={4} />}><IdeasView /></Suspense>;
}

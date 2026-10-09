import { Suspense } from "react";
import { ListSkeleton } from "@/components/data/async-states";
import { TeamView } from "@/features/team/components/team-view";

export default function TeamPage() {
  return <Suspense fallback={<ListSkeleton rows={4} />}><TeamView /></Suspense>;
}

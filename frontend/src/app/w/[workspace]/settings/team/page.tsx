import { Suspense } from "react";
import { ListSkeleton } from "@/components/shared/async-states";
import { TeamView } from "@/features/team/components/team-view";

export default function TeamPage() {
  return <Suspense fallback={<ListSkeleton rows={4} />}><TeamView /></Suspense>;
}

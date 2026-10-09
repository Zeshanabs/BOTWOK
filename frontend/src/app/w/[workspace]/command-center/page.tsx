import { Suspense } from "react";
import { ListSkeleton } from "@/components/data/async-states";
import { CommandCenter } from "@/features/ai/components/command-center";

export default function CommandCenterPage() {
  return <Suspense fallback={<ListSkeleton rows={6} />}><CommandCenter /></Suspense>;
}

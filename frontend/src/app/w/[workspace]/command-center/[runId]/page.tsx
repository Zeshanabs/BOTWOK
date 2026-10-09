"use client";
import { Suspense } from "react";
import { useParams } from "next/navigation";
import { ListSkeleton } from "@/components/data/async-states";
import { CommandCenter } from "@/features/ai/components/command-center";

export default function CommandCenterRunPage() {
  const { runId } = useParams<{ runId: string }>();
  return <Suspense fallback={<ListSkeleton rows={6} />}><CommandCenter runId={runId} /></Suspense>;
}

"use client";
import { Suspense } from "react";
import { useParams } from "next/navigation";
import { ListSkeleton } from "@/components/shared/async-states";
import { CompetitorDetail } from "@/features/competitors/components/competitor-detail";

export default function CompetitorDetailPage() {
  const { id } = useParams<{ id: string }>();
  return <Suspense fallback={<ListSkeleton rows={6} />}><CompetitorDetail id={id} /></Suspense>;
}

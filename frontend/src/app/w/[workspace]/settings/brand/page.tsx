import { Suspense } from "react";
import { ListSkeleton } from "@/components/shared/async-states";
import { BrandSettingsView } from "@/features/brand/components/brand-settings-view";

export default function BrandSettingsPage() {
  return <Suspense fallback={<ListSkeleton rows={6} />}><BrandSettingsView /></Suspense>;
}

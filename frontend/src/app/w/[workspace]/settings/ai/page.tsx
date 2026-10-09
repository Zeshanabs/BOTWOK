import { Suspense } from "react";
import { ListSkeleton } from "@/components/data/async-states";
import { AiSettingsView } from "@/features/ai-settings/components/ai-settings-view";

export default function AiSettingsPage() {
  return <Suspense fallback={<ListSkeleton rows={6} />}><AiSettingsView /></Suspense>;
}

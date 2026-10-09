import { Suspense } from "react";
import { OnboardingWizard } from "@/features/onboarding/components/onboarding-wizard";

export default function OnboardingPage() {
  return (
    <Suspense fallback={<div className="flex h-screen items-center justify-center text-sm text-muted-foreground">Loading…</div>}>
      <OnboardingWizard />
    </Suspense>
  );
}

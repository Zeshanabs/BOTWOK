import { Suspense } from "react";
import { OnboardingWizard } from "@/features/onboarding/components/onboarding-wizard";
import { AppLoading } from "@/components/layout/shell";

export default function OnboardingPage() {
  return (
    <Suspense fallback={<AppLoading />}>
      <OnboardingWizard />
    </Suspense>
  );
}

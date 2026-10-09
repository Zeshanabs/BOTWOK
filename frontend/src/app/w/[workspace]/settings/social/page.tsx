import { Suspense } from "react";
import { CardGridSkeleton } from "@/components/data/async-states";
import { SocialView } from "@/features/social/components/social-view";

export default function SocialAccountsPage() {
  return <Suspense fallback={<CardGridSkeleton count={4} />}><SocialView /></Suspense>;
}

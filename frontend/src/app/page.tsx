"use client";
import { useEffect } from "react";
import { useRouter } from "next/navigation";
import { refreshSession } from "@/lib/api";
import { useSession } from "@/stores/session";
import { AppLoading } from "@/components/layout/shell";

export default function Home() {
  const router = useRouter();
  const { hydrated, workspaceSlug } = useSession();
  useEffect(() => {
    if (!hydrated) return;
    (async () => {
      const ok = await refreshSession();
      const slug = useSession.getState().workspaceSlug ?? workspaceSlug;
      if (ok && slug) router.replace(`/w/${slug}/dashboard`);
      else if (ok) router.replace("/onboarding");
      else router.replace("/login");
    })();
  }, [hydrated, workspaceSlug, router]);
  return <AppLoading />;
}

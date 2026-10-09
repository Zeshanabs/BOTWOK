"use client";
import { useEffect } from "react";
import { useParams, useRouter } from "next/navigation";
import { Sidebar } from "./sidebar";
import { Header } from "./header";
import { AiDrawer } from "./ai-drawer";
import { MobileNav } from "./mobile-nav";
import { useSession } from "@/stores/session";
import { refreshSession } from "@/lib/api";
import { useSSEConnection } from "@/hooks/useSSE";

export function AppShell({ children }: { children: React.ReactNode }) {
  const router = useRouter();
  const params = useParams<{ workspace: string }>();
  const { accessToken, hydrated, memberships, setWorkspace, workspaceSlug } = useSession();
  useSSEConnection();
  useEffect(() => {
    if (!hydrated) return;
    (async () => {
      if (!accessToken) {
        const ok = await refreshSession();
        if (!ok) { router.replace(`/login?next=${encodeURIComponent(window.location.pathname)}`); return; }
      }
      if (params?.workspace && params.workspace !== workspaceSlug) setWorkspace(params.workspace);
    })();
  }, [hydrated, accessToken, params?.workspace, workspaceSlug, setWorkspace, router]);
  if (!hydrated || !accessToken) return <div className="flex h-screen items-center justify-center text-sm text-muted-foreground">Loading…</div>;
  if (memberships.length === 0) { router.replace("/onboarding"); return null; }
  return (
    <div className="flex h-screen overflow-hidden">
      <Sidebar />
      <div className="flex min-w-0 flex-1 flex-col">
        <Header />
        <div className="flex min-h-0 flex-1">
          <main className="min-w-0 flex-1 overflow-y-auto px-4 pb-20 pt-6 sm:px-6 md:pb-6">
            <div className="mx-auto max-w-[1440px]">{children}</div>
          </main>
          <AiDrawer />
        </div>
      </div>
      <MobileNav />
    </div>
  );
}

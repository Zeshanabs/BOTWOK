"use client";
import { useEffect } from "react";
import { useParams, useRouter } from "next/navigation";
import { Sidebar } from "./sidebar";
import { Header } from "./header";
import { AiDrawer } from "./ai-drawer";
import { MobileNav } from "./mobile-nav";
import { LogoMark } from "@/components/brand/logo";
import { useSession } from "@/stores/session";
import { refreshSession } from "@/lib/api";
import { useSSEConnection } from "@/hooks/useSSE";

/** Full-screen loader used while the session is restored. */
export function AppLoading({ label = "Loading your workspace…" }: { label?: string }) {
  return (
    <div className="flex h-dvh flex-col items-center justify-center gap-3 bg-background text-sm text-muted-foreground" role="status" aria-live="polite">
      <span className="flex h-10 w-10 animate-pulse items-center justify-center rounded-xl bg-primary text-primary-foreground"><LogoMark className="h-5 w-5" /></span>
      {label}
    </div>
  );
}

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
  if (!hydrated || !accessToken) return <AppLoading />;
  if (memberships.length === 0) { router.replace("/onboarding"); return null; }
  return (
    <div className="flex h-dvh overflow-hidden bg-background">
      <Sidebar />
      <div className="flex min-w-0 flex-1 flex-col">
        <Header />
        <div className="flex min-h-0 flex-1">
          <main id="main" className="min-w-0 flex-1 overflow-y-auto px-4 pb-24 pt-5 sm:px-6 md:pb-8 lg:px-8">
            <div className="mx-auto w-full max-w-[1440px]">{children}</div>
          </main>
          <AiDrawer />
        </div>
      </div>
      <MobileNav />
    </div>
  );
}

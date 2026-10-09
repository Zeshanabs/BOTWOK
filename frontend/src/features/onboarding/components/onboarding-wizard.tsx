"use client";
import { useEffect, useState } from "react";
import Link from "next/link";
import { usePathname, useRouter, useSearchParams } from "next/navigation";
import { Check } from "lucide-react";
import { Logo } from "@/components/brand/logo";
import { AppLoading } from "@/components/layout/shell";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Progress } from "@/components/ui/progress";
import { refreshSession } from "@/lib/api";
import { cn } from "@/lib/utils";
import { useSession } from "@/stores/session";
import { useActiveBrandId } from "@/features/brand/hooks";
import { BrandStep, ConnectStep, DoneStep, GoalsStep, ImportStep, WorkspaceStep } from "./steps";

const STEPS = [
  { title: "Workspace", heading: "Set up your workspace", description: "Where your team, brands and connected accounts live." },
  { title: "Brand", heading: "Brand basics", description: "A brand holds voice, pillars and connected accounts." },
  { title: "Import", heading: "Import from your website", description: "We read public pages and propose brand fields. Nothing is saved until you accept it." },
  { title: "Connect", heading: "Connect your first social account", description: "See each platform's real requirements before you sign in." },
  { title: "Goals", heading: "Goals", description: "Tell Botwok what success looks like so ideas and plans aim at it." },
  { title: "Done", heading: "You're set", description: "Here's what's ready. Skipped steps show up as a “Finish setup” card on the dashboard." },
];

function Wizard() {
  const router = useRouter();
  const pathname = usePathname();
  const sp = useSearchParams();
  const memberships = useSession((s) => s.memberships);
  const slug = useSession((s) => s.workspaceSlug);
  const brandId = useActiveBrandId();
  const raw = Number(sp.get("step") ?? (memberships.length ? 2 : 1));
  const step = Math.min(Math.max(Number.isFinite(raw) ? raw : 1, 1), STEPS.length);
  const [furthest, setFurthest] = useState(step);
  const go = (n: number) => { setFurthest((f) => Math.max(f, n)); router.replace(`${pathname}?step=${n}`); };
  const next = () => go(Math.min(step + 1, STEPS.length));
  const back = step > 1 ? () => go(step - 1) : undefined;
  const meta = STEPS[step - 1];

  return (
    <div className="min-h-dvh bg-background">
      <header className="flex items-center justify-between border-b bg-background px-4 py-3 sm:px-6">
        <Logo />
        {step >= 3 && slug && <Link href={`/w/${slug}/dashboard`} className="text-sm text-muted-foreground hover:text-foreground">Exit to dashboard</Link>}
      </header>
      <main className="mx-auto max-w-3xl px-4 pb-24 pt-6 sm:px-6">
        <nav aria-label="Setup progress" className="mb-6">
          <p className="mb-2 text-sm font-medium sm:hidden">Step {step} of {STEPS.length} · {meta.title}</p>
          <Progress value={(step / STEPS.length) * 100} className="sm:hidden" aria-label={`Step ${step} of ${STEPS.length}`} />
          <ol className="hidden items-center gap-1 sm:flex">
            {STEPS.map((s, i) => {
              const n = i + 1;
              const done = n < step;
              const reachable = n <= Math.max(furthest, step) && n !== step && (n !== 1 || !memberships.length || done);
              return (
                <li key={s.title} className="flex flex-1 items-center gap-1">
                  <button type="button" disabled={!reachable} onClick={() => go(n)} aria-current={n === step ? "step" : undefined}
                          className={cn("flex items-center gap-1.5 rounded-md px-1.5 py-1 text-xs font-medium", n === step ? "text-foreground" : done ? "text-primary hover:underline" : "text-muted-foreground", !reachable && "cursor-default")}>
                    <span className={cn("flex h-5 w-5 items-center justify-center rounded-full border text-[10px]", n === step && "border-primary bg-primary text-primary-foreground", done && "border-primary text-primary")}>{done ? <Check className="h-3 w-3" /> : n}</span>
                    {s.title}
                  </button>
                  {n < STEPS.length && <span className="h-px flex-1 bg-border" aria-hidden />}
                </li>
              );
            })}
          </ol>
        </nav>
        <Card>
          <CardHeader><CardTitle className="font-display text-xl font-bold tracking-tight">{meta.heading}</CardTitle><CardDescription>{meta.description}</CardDescription></CardHeader>
          <CardContent>
            {step === 1 && <WorkspaceStep onNext={next} />}
            {step === 2 && <BrandStep onNext={next} onBack={back} />}
            {step === 3 && <ImportStep onNext={next} onBack={back} brandId={brandId} />}
            {step === 4 && <ConnectStep onNext={next} onBack={back} brandId={brandId} />}
            {step === 5 && <GoalsStep onNext={next} onBack={back} brandId={brandId} />}
            {step === 6 && <DoneStep brandId={brandId} />}
          </CardContent>
        </Card>
      </main>
    </div>
  );
}

/** Auth gate: re-obtain the access token from the refresh cookie, else send to /login. */
export function OnboardingWizard() {
  const router = useRouter();
  const hydrated = useSession((s) => s.hydrated);
  const accessToken = useSession((s) => s.accessToken);
  useEffect(() => {
    if (!hydrated || accessToken) return;
    refreshSession().then((ok) => { if (!ok) router.replace("/login?next=/onboarding"); });
  }, [hydrated, accessToken, router]);
  if (!hydrated || !accessToken) return <AppLoading />;
  return <Wizard />;
}

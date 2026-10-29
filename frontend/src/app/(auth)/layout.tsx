import Link from "next/link";
import { BadgeCheck, Radar, ShieldCheck, Sparkles } from "lucide-react";
import { Logo, LogoMark } from "@/components/brand/logo";

const POINTS = [
  { icon: Sparkles, title: "AI that shows its work", text: "Every run lists its steps, sources, tool calls and cost. Nothing publishes without a person approving it." },
  { icon: Radar, title: "Research with receipts", text: "Competitor intelligence and trends from lawful sources, cited inline so you can check them." },
  { icon: ShieldCheck, title: "Local-first", text: "Your data lives on this machine. Platform publishing goes through the official APIs only." },
];

export default function AuthLayout({ children }: { children: React.ReactNode }) {
  return (
    <div className="grid min-h-dvh lg:grid-cols-[1.05fr_1fr]">
      {/* Brand panel: the one expressive surface in the app. */}
      <aside className="relative hidden overflow-hidden bg-primary text-primary-foreground lg:flex lg:flex-col lg:justify-between lg:p-10 xl:p-14" aria-hidden>
        <div className="absolute inset-0 bg-dotgrid opacity-[0.18]" />
        <div className="absolute -right-32 -top-32 h-[420px] w-[420px] rounded-full bg-ai/30 blur-3xl" />
        <div className="absolute -bottom-40 -left-20 h-[420px] w-[420px] rounded-full bg-white/10 blur-3xl" />
        <div className="relative flex items-center gap-2.5">
          <span className="flex h-9 w-9 items-center justify-center rounded-xl bg-white/15 ring-1 ring-white/25"><LogoMark className="h-5 w-5" /></span>
          <span className="font-display text-lg font-bold tracking-tight">Botwok</span>
        </div>
        <div className="relative max-w-md">
          <p className="font-display text-4xl font-bold leading-[1.1] tracking-tight xl:text-[44px]">Cook up a month of content, with every claim sourced.</p>
          <p className="mt-4 text-[15px] leading-relaxed text-primary-foreground/80">Research, strategy, drafts, approvals, scheduling and analytics in one calm workspace, with AI agents that never act silently.</p>
          <ul className="mt-10 space-y-5">
            {POINTS.map((p) => (
              <li key={p.title} className="flex gap-3.5">
                <span className="mt-0.5 flex h-8 w-8 shrink-0 items-center justify-center rounded-lg bg-white/12 ring-1 ring-white/20"><p.icon className="h-4 w-4" /></span>
                <div>
                  <p className="text-sm font-semibold">{p.title}</p>
                  <p className="mt-0.5 text-[13px] leading-relaxed text-primary-foreground/75">{p.text}</p>
                </div>
              </li>
            ))}
          </ul>
        </div>
        <p className="relative flex items-center gap-2 text-xs text-primary-foreground/70"><BadgeCheck className="h-3.5 w-3.5" /> Official platform APIs · exactly-once publishing · human approval gates</p>
      </aside>

      <main className="flex items-center justify-center bg-background px-4 py-10 sm:px-8">
        <div className="w-full max-w-[400px]">
          <Link href="/login" className="mb-8 inline-flex lg:hidden" aria-label="Botwok"><Logo /></Link>
          {children}
          <p className="mt-8 text-center text-xs text-muted-foreground">Local-first. Your data stays on this machine.</p>
        </div>
      </main>
    </div>
  );
}

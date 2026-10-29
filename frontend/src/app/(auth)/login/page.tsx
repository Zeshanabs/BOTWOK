"use client";
import { Suspense, useState } from "react";
import Link from "next/link";
import { useRouter, useSearchParams } from "next/navigation";
import { ArrowRight, Loader2 } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { FormError } from "@/components/shared/form-errors";
import { api } from "@/lib/api";
import { membershipsFrom, useSession, type Membership, type User } from "@/stores/session";

function LoginForm() {
  const router = useRouter();
  const sp = useSearchParams();
  const setAuth = useSession((s) => s.setAuth);
  const [email, setEmail] = useState(""); const [password, setPassword] = useState("");
  const [error, setError] = useState<unknown>(null); const [busy, setBusy] = useState(false);
  async function submit(e: React.FormEvent) {
    e.preventDefault(); setBusy(true); setError(null);
    try {
      const d = await api.post<{ access_token: string; user: User; memberships?: Membership[]; workspace?: { id: string; name: string; slug: string; role?: string }; role?: string }>("/auth/login", { email, password });
      const ms = membershipsFrom(d);
      setAuth(d.access_token, d.user, ms);
      const slug = ms[0]?.workspace.slug;
      router.replace(sp.get("next") || (slug ? `/w/${slug}/dashboard` : "/onboarding"));
    } catch (err) { setError(err); } finally { setBusy(false); }
  }
  return (
    <div>
      <h1 className="font-display text-[28px] font-bold tracking-tight">Welcome back</h1>
      <p className="mt-1.5 text-sm text-muted-foreground">Sign in to your workspace.</p>
      <form onSubmit={submit} className="mt-8 space-y-5" noValidate>
        <div className="space-y-1.5">
          <Label htmlFor="email">Email</Label>
          <Input id="email" type="email" autoComplete="email" placeholder="you@company.com" value={email} onChange={(e) => setEmail(e.target.value)} required autoFocus className="h-10" />
        </div>
        <div className="space-y-1.5">
          <Label htmlFor="password">Password</Label>
          <Input id="password" type="password" autoComplete="current-password" placeholder="••••••••" value={password} onChange={(e) => setPassword(e.target.value)} required className="h-10" />
        </div>
        <FormError error={error} />
        <Button type="submit" size="lg" className="w-full" disabled={busy}>
          {busy ? <Loader2 className="animate-spin" /> : null}{busy ? "Signing in…" : "Sign in"}{!busy && <ArrowRight />}
        </Button>
      </form>
      <p className="mt-6 text-center text-sm text-muted-foreground">New here? <Link className="font-medium text-primary underline-offset-4 hover:underline" href="/signup">Create an account</Link></p>
    </div>
  );
}
export default function LoginPage() { return <Suspense><LoginForm /></Suspense>; }

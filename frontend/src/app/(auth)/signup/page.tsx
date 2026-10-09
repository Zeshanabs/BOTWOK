"use client";
import { useState } from "react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { ArrowRight, Loader2 } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { FieldError, FormError, problemFieldErrors } from "@/components/shared/form-errors";
import { api } from "@/lib/api";
import { membershipsFrom, useSession, type Membership, type User } from "@/stores/session";

export default function SignupPage() {
  const router = useRouter();
  const setAuth = useSession((s) => s.setAuth);
  const [form, setForm] = useState({ full_name: "", email: "", password: "", workspace_name: "" });
  const [error, setError] = useState<unknown>(null); const [busy, setBusy] = useState(false);
  const errors = problemFieldErrors(error);
  async function submit(e: React.FormEvent) {
    e.preventDefault(); setBusy(true); setError(null);
    try {
      const d = await api.post<{ access_token: string; user: User; memberships?: Membership[]; workspace?: { id: string; name: string; slug: string; role?: string }; role?: string }>("/auth/signup", form);
      setAuth(d.access_token, d.user, membershipsFrom(d));
      router.replace("/onboarding");
    } catch (err) { setError(err); } finally { setBusy(false); }
  }
  const set = (k: keyof typeof form) => (e: React.ChangeEvent<HTMLInputElement>) => setForm({ ...form, [k]: e.target.value });
  return (
    <div>
      <h1 className="font-display text-[28px] font-bold tracking-tight">Create your account</h1>
      <p className="mt-1.5 text-sm text-muted-foreground">The first account becomes the workspace owner.</p>
      <form onSubmit={submit} className="mt-8 space-y-5" noValidate>
        <div className="space-y-1.5">
          <Label htmlFor="name">Full name</Label>
          <Input id="name" autoComplete="name" value={form.full_name} onChange={set("full_name")} required autoFocus className="h-10" aria-invalid={!!errors.full_name} />
          <FieldError errors={errors} name="full_name" />
        </div>
        <div className="space-y-1.5">
          <Label htmlFor="email">Email</Label>
          <Input id="email" type="email" autoComplete="email" placeholder="you@company.com" value={form.email} onChange={set("email")} required className="h-10" aria-invalid={!!errors.email} />
          <FieldError errors={errors} name="email" />
        </div>
        <div className="space-y-1.5">
          <Label htmlFor="password">Password</Label>
          <Input id="password" type="password" autoComplete="new-password" minLength={8} value={form.password} onChange={set("password")} required className="h-10" aria-invalid={!!errors.password} />
          <p className="text-[11px] text-muted-foreground">At least 8 characters.</p>
          <FieldError errors={errors} name="password" />
        </div>
        <div className="space-y-1.5">
          <Label htmlFor="ws">Workspace name <span className="font-normal text-muted-foreground">(optional)</span></Label>
          <Input id="ws" placeholder="e.g. Acme Marketing" value={form.workspace_name} onChange={set("workspace_name")} className="h-10" aria-invalid={!!errors.workspace_name} />
          <FieldError errors={errors} name="workspace_name" />
        </div>
        <FormError error={Object.keys(errors).length ? null : error} />
        <Button type="submit" size="lg" className="w-full" disabled={busy}>
          {busy ? <Loader2 className="animate-spin" /> : null}{busy ? "Creating…" : "Create account"}{!busy && <ArrowRight />}
        </Button>
      </form>
      <p className="mt-6 text-center text-sm text-muted-foreground">Have an account? <Link className="font-medium text-primary underline-offset-4 hover:underline" href="/login">Sign in</Link></p>
    </div>
  );
}

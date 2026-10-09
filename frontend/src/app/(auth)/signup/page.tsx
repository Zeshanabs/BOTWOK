"use client";
import { useState } from "react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { api, ApiError } from "@/lib/api";
import { membershipsFrom, useSession, type Membership, type User } from "@/stores/session";

export default function SignupPage() {
  const router = useRouter();
  const setAuth = useSession((s) => s.setAuth);
  const [form, setForm] = useState({ full_name: "", email: "", password: "", workspace_name: "" });
  const [error, setError] = useState<string | null>(null); const [busy, setBusy] = useState(false);
  async function submit(e: React.FormEvent) {
    e.preventDefault(); setBusy(true); setError(null);
    try {
      const d = await api.post<{ access_token: string; user: User; memberships?: Membership[]; workspace?: { id: string; name: string; slug: string; role?: string }; role?: string }>("/auth/signup", form);
      setAuth(d.access_token, d.user, membershipsFrom(d));
      router.replace("/onboarding");
    } catch (err) { setError(err instanceof ApiError ? err.message : "Signup failed"); } finally { setBusy(false); }
  }
  const set = (k: keyof typeof form) => (e: React.ChangeEvent<HTMLInputElement>) => setForm({ ...form, [k]: e.target.value });
  return (
    <Card>
      <CardHeader><CardTitle>Create your account</CardTitle><CardDescription>The first account becomes the workspace owner.</CardDescription></CardHeader>
      <CardContent>
        <form onSubmit={submit} className="space-y-4">
          <div className="space-y-1"><Label htmlFor="name">Full name</Label><Input id="name" value={form.full_name} onChange={set("full_name")} required /></div>
          <div className="space-y-1"><Label htmlFor="email">Email</Label><Input id="email" type="email" value={form.email} onChange={set("email")} required /></div>
          <div className="space-y-1"><Label htmlFor="password">Password</Label><Input id="password" type="password" minLength={8} value={form.password} onChange={set("password")} required /></div>
          <div className="space-y-1"><Label htmlFor="ws">Workspace name</Label><Input id="ws" placeholder="e.g. Acme Marketing" value={form.workspace_name} onChange={set("workspace_name")} /></div>
          {error && <p role="alert" className="text-sm text-red-600">{error}</p>}
          <Button type="submit" className="w-full" disabled={busy}>{busy ? "Creating…" : "Create account"}</Button>
          <p className="text-center text-sm text-muted-foreground">Have an account? <Link className="text-primary underline" href="/login">Sign in</Link></p>
        </form>
      </CardContent>
    </Card>
  );
}

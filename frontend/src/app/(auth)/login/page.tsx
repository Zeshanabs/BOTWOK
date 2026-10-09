"use client";
import { useState } from "react";
import Link from "next/link";
import { useRouter, useSearchParams } from "next/navigation";
import { Suspense } from "react";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { api, ApiError } from "@/lib/api";
import { membershipsFrom, useSession, type Membership, type User } from "@/stores/session";

function LoginForm() {
  const router = useRouter();
  const sp = useSearchParams();
  const setAuth = useSession((s) => s.setAuth);
  const [email, setEmail] = useState(""); const [password, setPassword] = useState("");
  const [error, setError] = useState<string | null>(null); const [busy, setBusy] = useState(false);
  async function submit(e: React.FormEvent) {
    e.preventDefault(); setBusy(true); setError(null);
    try {
      const d = await api.post<{ access_token: string; user: User; memberships?: Membership[]; workspace?: { id: string; name: string; slug: string; role?: string }; role?: string }>("/auth/login", { email, password });
      const ms = membershipsFrom(d);
      setAuth(d.access_token, d.user, ms);
      const slug = ms[0]?.workspace.slug;
      router.replace(sp.get("next") || (slug ? `/w/${slug}/dashboard` : "/onboarding"));
    } catch (err) { setError(err instanceof ApiError ? err.message : "Login failed"); } finally { setBusy(false); }
  }
  return (
    <Card>
      <CardHeader><CardTitle>Sign in</CardTitle><CardDescription>Local-first. Your data stays on this machine.</CardDescription></CardHeader>
      <CardContent>
        <form onSubmit={submit} className="space-y-4">
          <div className="space-y-1"><Label htmlFor="email">Email</Label><Input id="email" type="email" autoComplete="email" value={email} onChange={(e) => setEmail(e.target.value)} required /></div>
          <div className="space-y-1"><Label htmlFor="password">Password</Label><Input id="password" type="password" autoComplete="current-password" value={password} onChange={(e) => setPassword(e.target.value)} required /></div>
          {error && <p role="alert" className="text-sm text-red-600">{error}</p>}
          <Button type="submit" className="w-full" disabled={busy}>{busy ? "Signing in…" : "Sign in"}</Button>
          <p className="text-center text-sm text-muted-foreground">No account? <Link className="text-primary underline" href="/signup">Create one</Link></p>
        </form>
      </CardContent>
    </Card>
  );
}
export default function LoginPage() { return <Suspense><LoginForm /></Suspense>; }

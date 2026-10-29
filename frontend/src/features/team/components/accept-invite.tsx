"use client";
/** /invite/[token]: accept a workspace invitation (POST /invitations/{token}/accept). Anonymous visitors can sign in
 *  or create an account with the invitation token (invites bypass the signup lock, doc 25 flow A.8). */
import { useEffect, useState } from "react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { CheckCircle2, MailOpen, Radar } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { FieldError, FormError, problemFieldErrors } from "@/components/shared/form-errors";
import { errorStatus } from "@/components/shared/async-states";
import { api, refreshSession } from "@/lib/api";
import { useSession, type Membership, type User } from "@/stores/session";
import { teamApi } from "../api";

type Phase = "checking" | "anon" | "ready" | "accepting" | "done";

export function AcceptInvite({ token }: { token: string }) {
  const router = useRouter();
  const hydrated = useSession((s) => s.hydrated);
  const accessToken = useSession((s) => s.accessToken);
  const user = useSession((s) => s.user);
  const [checked, setChecked] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<unknown>(null);
  const [done, setDone] = useState<{ name: string; slug: string; role: string } | null>(null);
  const [form, setForm] = useState({ full_name: "", email: "", password: "" });
  const errors = problemFieldErrors(error);

  useEffect(() => {
    if (!hydrated || accessToken) return;
    refreshSession().finally(() => setChecked(true));
  }, [hydrated, accessToken]);

  const phase: Phase = done ? "done" : !hydrated || (!accessToken && !checked) ? "checking" : !accessToken ? "anon" : busy ? "accepting" : "ready";

  async function finish(ws: { id: string; name: string; slug: string }, role: Membership["role"]) {
    const s = useSession.getState();
    await refreshSession();
    const after = useSession.getState();
    if (!after.memberships.some((m) => m.workspace.id === ws.id) && after.accessToken && after.user) {
      after.setAuth(after.accessToken, after.user, [...after.memberships, { workspace: ws, role }]);
    } else if (!after.accessToken && s.accessToken && s.user) {
      s.setAuth(s.accessToken, s.user, [...s.memberships, { workspace: ws, role }]);
    }
    useSession.getState().setWorkspace(ws.slug);
    setDone({ name: ws.name, slug: ws.slug, role });
  }

  async function accept() {
    setBusy(true); setError(null);
    try {
      const d = await teamApi.accept(token);
      await finish(d.workspace, d.role);
    } catch (e) { setError(e); } finally { setBusy(false); }
  }

  async function signup(e: React.FormEvent) {
    e.preventDefault();
    setBusy(true); setError(null);
    try {
      const d = await api.post<{ access_token: string; user: User; memberships?: Membership[]; workspace?: { id: string; name: string; slug: string }; role?: Membership["role"] }>("/auth/signup", { ...form, invitation_token: token });
      useSession.getState().setAuth(d.access_token, d.user, d.memberships ?? []);
      const ws = d.workspace ?? d.memberships?.[0]?.workspace;
      if (ws) await finish(ws, d.role ?? d.memberships?.[0]?.role ?? "viewer");
      else { const a = await teamApi.accept(token); await finish(a.workspace, a.role); }
    } catch (err) { setError(err); } finally { setBusy(false); }
  }

  const expired = [404, 410].includes(errorStatus(error) ?? 0);

  return (
    <div className="flex min-h-screen items-center justify-center bg-muted/30 p-4">
      <div className="w-full max-w-sm">
        <div className="mb-6 flex items-center justify-center gap-2"><Radar className="h-6 w-6 text-primary" /><span className="text-lg font-semibold">Botwok</span></div>
        <Card>
          {phase === "checking" && <CardContent className="py-10 text-center text-sm text-muted-foreground">Checking your session…</CardContent>}
          {phase === "done" && done && (
            <>
              <CardHeader><CardTitle className="flex items-center gap-2"><CheckCircle2 className="h-5 w-5 text-success" /> You&apos;re in</CardTitle><CardDescription>You joined {done.name} as {done.role}.</CardDescription></CardHeader>
              <CardContent><Button className="w-full" onClick={() => router.replace(`/w/${done.slug}/dashboard`)}>Open {done.name}</Button></CardContent>
            </>
          )}
          {(phase === "ready" || phase === "accepting") && (
            <>
              <CardHeader><CardTitle className="flex items-center gap-2"><MailOpen className="h-5 w-5" /> Workspace invitation</CardTitle><CardDescription>Signed in as {user?.email}. Accept to join the workspace.</CardDescription></CardHeader>
              <CardContent className="space-y-3">
                {expired ? <p role="alert" className="text-sm text-destructive">This invitation is invalid or has expired. Ask the workspace owner for a new link.</p> : <FormError error={error} />}
                <Button className="w-full" onClick={accept} disabled={phase === "accepting" || expired}>{phase === "accepting" ? "Accepting…" : "Accept invitation"}</Button>
                <p className="text-center text-xs text-muted-foreground">Not you? <Link className="text-primary underline" href={`/login?next=/invite/${encodeURIComponent(token)}`}>Sign in with another account</Link></p>
              </CardContent>
            </>
          )}
          {phase === "anon" && (
            <>
              <CardHeader><CardTitle>Join the workspace</CardTitle><CardDescription>Create your account to accept, or sign in if you already have one.</CardDescription></CardHeader>
              <CardContent>
                <form className="space-y-3" onSubmit={signup}>
                  <div className="space-y-1"><Label htmlFor="inv-name">Full name</Label><Input id="inv-name" value={form.full_name} onChange={(e) => setForm({ ...form, full_name: e.target.value })} required /></div>
                  <div className="space-y-1"><Label htmlFor="inv-email">Email</Label><Input id="inv-email" type="email" autoComplete="email" value={form.email} onChange={(e) => setForm({ ...form, email: e.target.value })} required aria-invalid={!!errors.email} /><FieldError errors={errors} name="email" /></div>
                  <div className="space-y-1"><Label htmlFor="inv-pw">Password</Label><Input id="inv-pw" type="password" autoComplete="new-password" minLength={8} value={form.password} onChange={(e) => setForm({ ...form, password: e.target.value })} required aria-invalid={!!errors.password} /><FieldError errors={errors} name="password" /></div>
                  {expired ? <p role="alert" className="text-sm text-destructive">This invitation is invalid or has expired.</p> : <FormError error={Object.keys(errors).length ? null : error} />}
                  <Button type="submit" className="w-full" disabled={busy}>{busy ? "Creating…" : "Create account & join"}</Button>
                  <p className="text-center text-sm text-muted-foreground">Have an account? <Link className="text-primary underline" href={`/login?next=/invite/${encodeURIComponent(token)}`}>Sign in</Link></p>
                </form>
              </CardContent>
            </>
          )}
        </Card>
      </div>
    </div>
  );
}

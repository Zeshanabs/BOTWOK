"use client";
import { useState } from "react";
import { usePathname, useRouter, useSearchParams } from "next/navigation";
import { toast } from "sonner";
import { Check, Copy, UserPlus, Users, X } from "lucide-react";
import { Avatar, AvatarFallback } from "@/components/ui/avatar";
import { Button } from "@/components/ui/button";
import { Dialog, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle } from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { PageHeader } from "@/components/data/page-header";
import { StatusChip } from "@/components/data/status-chip";
import { EmptyState } from "@/components/data/empty-state";
import { ConfirmDialog } from "@/components/data/confirm-dialog";
import { ListSkeleton, QueryError, errorMessage } from "@/components/data/async-states";
import { fmtDate, fmtRelative } from "@/lib/formatters";
import { useCan } from "@/lib/permissions";
import { useSession } from "@/stores/session";
import type { Invitation, Member, Role } from "../api";
import { useInvitations, useMembers, useTeamMutations } from "../hooks";

const ROLES: Role[] = ["owner", "admin", "editor", "approver", "viewer"];
const MATRIX: { cap: string; roles: Role[] }[] = [
  { cap: "Manage billing / delete workspace", roles: ["owner"] },
  { cap: "Manage members, roles, API keys", roles: ["owner", "admin"] },
  { cap: "Connect / disconnect social accounts", roles: ["owner", "admin"] },
  { cap: "Edit brand, AI settings, automations", roles: ["owner", "admin"] },
  { cap: "Create/edit content, run AI, research", roles: ["owner", "admin", "editor", "approver"] },
  { cap: "Approve / reject content", roles: ["owner", "admin", "approver"] },
  { cap: "Schedule / publish approved content", roles: ["owner", "admin", "editor", "approver"] },
  { cap: "View everything", roles: ["owner", "admin", "editor", "approver", "viewer"] },
];

function InviteDialog({ open, onOpenChange }: { open: boolean; onOpenChange: (o: boolean) => void }) {
  const { invite } = useTeamMutations();
  const [emails, setEmails] = useState("");
  const [role, setRole] = useState<Role>("editor");
  const [results, setResults] = useState<{ email: string; ok: boolean; message?: string; link?: string | null }[]>([]);
  const [busy, setBusy] = useState(false);

  async function submit(e: React.FormEvent) {
    e.preventDefault();
    const list = Array.from(new Set(emails.split(/[\s,;]+/).map((x) => x.trim()).filter(Boolean)));
    if (!list.length) return;
    setBusy(true);
    const out: typeof results = [];
    for (const email of list) {
      try {
        const inv = await invite.mutateAsync({ email, role });
        const link = inv?.accept_url ?? (inv?.token ? `${window.location.origin}/invite/${inv.token}` : null);
        out.push({ email, ok: true, link });
      } catch (err) {
        out.push({ email, ok: false, message: errorMessage(err) });
      }
    }
    setResults(out);
    setBusy(false);
    if (out.every((r) => r.ok)) setEmails("");
  }

  return (
    <Dialog open={open} onOpenChange={(o) => { if (!o) { setResults([]); setEmails(""); } onOpenChange(o); }}>
      <DialogContent>
        <DialogHeader>
          <DialogTitle>Invite teammates</DialogTitle>
          <DialogDescription>Invitations expire after 7 days. If email isn&apos;t configured, copy the link below and send it yourself — it&apos;s shown only once.</DialogDescription>
        </DialogHeader>
        <form id="invite-form" onSubmit={submit} className="space-y-3">
          <div className="space-y-1"><Label htmlFor="inv-emails">Emails</Label><Input id="inv-emails" value={emails} onChange={(e) => setEmails(e.target.value)} placeholder="jo@acme.com, ravi@acme.com" /></div>
          <div className="space-y-1">
            <Label htmlFor="inv-role">Role</Label>
            <Select value={role} onValueChange={(v) => setRole(v as Role)}>
              <SelectTrigger id="inv-role" className="w-full"><SelectValue /></SelectTrigger>
              <SelectContent>{ROLES.filter((r) => r !== "owner").map((r) => <SelectItem key={r} value={r}>{r}</SelectItem>)}</SelectContent>
            </Select>
          </div>
        </form>
        {results.length > 0 && (
          <ul className="space-y-2 text-sm">
            {results.map((r) => (
              <li key={r.email} className="rounded-md border p-2">
                <p className="flex items-center gap-1">{r.ok ? <Check className="h-4 w-4 text-green-600" /> : <X className="h-4 w-4 text-red-600" />}{r.email}</p>
                {r.message && <p className="text-xs text-destructive">{r.message}</p>}
                {r.link && (
                  <div className="mt-1 flex items-center gap-1">
                    <Input readOnly value={r.link} className="h-7 font-mono text-xs" aria-label={`Invite link for ${r.email}`} />
                    <Button size="icon-sm" variant="ghost" aria-label="Copy link" onClick={() => navigator.clipboard?.writeText(r.link ?? "").then(() => toast.success("Link copied"), () => undefined)}><Copy className="h-3 w-3" /></Button>
                  </div>
                )}
              </li>
            ))}
          </ul>
        )}
        <DialogFooter>
          <Button variant="outline" onClick={() => onOpenChange(false)}>{results.length ? "Done" : "Cancel"}</Button>
          <Button type="submit" form="invite-form" disabled={busy || !emails.trim()}>{busy ? "Inviting…" : "Send invitations"}</Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}

export function TeamView() {
  const router = useRouter();
  const pathname = usePathname();
  const sp = useSearchParams();
  const can = useCan();
  const me = useSession((s) => s.user);
  const myRole = useSession((s) => s.role);
  const members = useMembers();
  const invitations = useInvitations(can.manage);
  const { updateRole, remove, revoke } = useTeamMutations();
  const [inviteOpen, setInviteOpen] = useState(false);
  const [removing, setRemoving] = useState<Member | null>(null);
  const [revoking, setRevoking] = useState<Invitation | null>(null);
  const [search, setSearch] = useState("");
  const tab = sp.get("tab") ?? "members";
  const pending = (invitations.data ?? []).filter((i) => (i.status ?? "pending") === "pending" && !i.accepted_at);
  const list = (members.data ?? []).filter((m) => !search || `${m.full_name} ${m.email}`.toLowerCase().includes(search.toLowerCase()));

  function roleOptions(m: Member): Role[] {
    if (myRole === "owner") return ROLES;
    return ROLES.filter((r) => r !== "owner" && (m.role !== "owner"));
  }

  return (
    <div>
      <PageHeader title="Team" description="Members, roles and invitations." actions={can.manage ? <Button onClick={() => setInviteOpen(true)}><UserPlus className="h-4 w-4" /> Invite</Button> : undefined} />
      <Tabs value={tab} onValueChange={(t) => router.replace(`${pathname}?tab=${t}`)}>
        <div className="flex flex-wrap items-center justify-between gap-2">
          <TabsList>
            <TabsTrigger value="members">Members</TabsTrigger>
            {can.manage && <TabsTrigger value="invitations">Invitations{pending.length ? ` (${pending.length})` : ""}</TabsTrigger>}
            <TabsTrigger value="roles">Roles</TabsTrigger>
          </TabsList>
          {tab === "members" && <Input value={search} onChange={(e) => setSearch(e.target.value)} placeholder="Search members…" className="h-8 w-full sm:w-56" aria-label="Search members" />}
        </div>

        <TabsContent value="members" className="mt-4">
          {members.isLoading ? <ListSkeleton rows={4} /> : members.error ? <QueryError error={members.error} onRetry={() => members.refetch()} title="Couldn't load members" /> : !list.length ? (
            <EmptyState icon={Users} title={search ? "No members match" : "Invite teammates to review and approve content."} action={can.manage && !search ? { label: "Invite", onClick: () => setInviteOpen(true) } : undefined} />
          ) : (
            <>
              <div className="hidden overflow-x-auto rounded-lg border md:block">
                <Table>
                  <TableHeader><TableRow><TableHead>Member</TableHead><TableHead>Email</TableHead><TableHead>Role</TableHead><TableHead>Joined</TableHead><TableHead /></TableRow></TableHeader>
                  <TableBody>
                    {list.map((m) => {
                      const self = m.user_id === me?.id;
                      const editable = can.manage && !self && (myRole === "owner" || m.role !== "owner");
                      return (
                        <TableRow key={m.user_id}>
                          <TableCell><div className="flex items-center gap-2"><Avatar className="h-7 w-7"><AvatarFallback className="text-[10px]">{m.full_name.slice(0, 2).toUpperCase()}</AvatarFallback></Avatar><span className="font-medium">{m.full_name}{self && <span className="ml-1 text-xs text-muted-foreground">(you)</span>}</span></div></TableCell>
                          <TableCell className="text-sm text-muted-foreground">{m.email}</TableCell>
                          <TableCell>
                            {editable ? (
                              <Select value={m.role} onValueChange={(r) => updateRole.mutate({ userId: m.user_id, role: r as Role }, { onSuccess: () => toast.success(`${m.full_name} is now ${r}`), onError: (e) => toast.error(errorMessage(e)) })}>
                                <SelectTrigger size="sm" className="w-32" aria-label={`Role for ${m.full_name}`}><SelectValue /></SelectTrigger>
                                <SelectContent>{roleOptions(m).map((r) => <SelectItem key={r} value={r}>{r}</SelectItem>)}</SelectContent>
                              </Select>
                            ) : <span className="text-sm">{m.role}</span>}
                          </TableCell>
                          <TableCell className="text-xs text-muted-foreground">{m.last_active_at ? `active ${fmtRelative(m.last_active_at)}` : fmtDate(m.joined_at)}</TableCell>
                          <TableCell className="text-right">{editable && <Button size="xs" variant="ghost" className="text-destructive" onClick={() => setRemoving(m)}>Remove</Button>}</TableCell>
                        </TableRow>
                      );
                    })}
                  </TableBody>
                </Table>
              </div>
              <ul className="space-y-2 md:hidden">
                {list.map((m) => (
                  <li key={m.user_id} className="flex items-center gap-3 rounded-lg border p-3 text-sm">
                    <Avatar className="h-8 w-8"><AvatarFallback className="text-[10px]">{m.full_name.slice(0, 2).toUpperCase()}</AvatarFallback></Avatar>
                    <div className="min-w-0 flex-1"><p className="truncate font-medium">{m.full_name}</p><p className="truncate text-xs text-muted-foreground">{m.email}</p></div>
                    <span className="text-xs">{m.role}</span>
                  </li>
                ))}
              </ul>
            </>
          )}
        </TabsContent>

        {can.manage && (
          <TabsContent value="invitations" className="mt-4">
            {invitations.isLoading ? <ListSkeleton rows={3} /> : invitations.error ? (
              <QueryError error={invitations.error} onRetry={() => invitations.refetch()} title="Couldn't load invitations" notAvailableText="Listing invitations isn't available on this install yet — invites still work." />
            ) : !(invitations.data ?? []).length ? <EmptyState icon={UserPlus} title="No invitations" description="Invite teammates to review and approve content." action={{ label: "Invite", onClick: () => setInviteOpen(true) }} /> : (
              <ul className="divide-y rounded-lg border">
                {(invitations.data ?? []).map((i) => (
                  <li key={i.id} className="flex flex-wrap items-center gap-3 p-3 text-sm">
                    <span className="min-w-0 flex-1 truncate font-medium">{i.email}</span>
                    <span className="text-xs">{i.role}</span>
                    <StatusChip status={i.accepted_at ? "accepted" : i.status ?? "pending"} />
                    <span className="text-xs text-muted-foreground">expires {fmtDate(i.expires_at)}</span>
                    {!i.accepted_at && (i.status ?? "pending") === "pending" && <Button size="xs" variant="ghost" className="text-destructive" onClick={() => setRevoking(i)}>Revoke</Button>}
                  </li>
                ))}
              </ul>
            )}
          </TabsContent>
        )}

        <TabsContent value="roles" className="mt-4">
          <div className="overflow-x-auto rounded-lg border">
            <Table>
              <TableHeader><TableRow><TableHead>Capability</TableHead>{ROLES.map((r) => <TableHead key={r} className="text-center capitalize">{r}</TableHead>)}</TableRow></TableHeader>
              <TableBody>
                {MATRIX.map((row) => (
                  <TableRow key={row.cap}>
                    <TableCell className="text-sm">{row.cap}</TableCell>
                    {ROLES.map((r) => <TableCell key={r} className="text-center">{row.roles.includes(r) ? <Check className="mx-auto h-4 w-4 text-green-600" aria-label="Allowed" /> : <span className="sr-only">Not allowed</span>}</TableCell>)}
                  </TableRow>
                ))}
              </TableBody>
            </Table>
          </div>
          <p className="mt-2 text-xs text-muted-foreground">Editors can schedule only approved content. Only owners can grant the owner role; the last owner can&apos;t be removed.</p>
        </TabsContent>
      </Tabs>

      <InviteDialog open={inviteOpen} onOpenChange={setInviteOpen} />
      <ConfirmDialog open={!!removing} onOpenChange={(o) => { if (!o) setRemoving(null); }} title={`Remove ${removing?.full_name ?? "member"}?`}
                     description="They lose access to this workspace immediately. Content they created stays." confirmLabel="Remove" busy={remove.isPending}
                     onConfirm={() => removing && remove.mutate(removing.user_id, { onSuccess: () => { toast.success("Member removed"); setRemoving(null); }, onError: (e) => toast.error(errorMessage(e)) })} />
      <ConfirmDialog open={!!revoking} onOpenChange={(o) => { if (!o) setRevoking(null); }} title={`Revoke the invitation for ${revoking?.email ?? ""}?`}
                     description="The invite link stops working." confirmLabel="Revoke" busy={revoke.isPending}
                     onConfirm={() => revoking && revoke.mutate(revoking.id, { onSuccess: () => { toast.success("Invitation revoked"); setRevoking(null); }, onError: (e) => toast.error(errorMessage(e)) })} />
    </div>
  );
}

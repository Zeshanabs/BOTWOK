"use client";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { toItems } from "@/lib/formatters";
import { useSession } from "@/stores/session";
import { teamApi, type Role } from "./api";

export const teamKeys = {
  members: (ws: string) => ["team", ws, "members"] as const,
  invitations: (ws: string) => ["team", ws, "invitations"] as const,
};

export function useMembers() {
  const ws = useSession((s) => s.workspaceId);
  return useQuery({ queryKey: teamKeys.members(ws ?? ""), queryFn: async () => toItems(await teamApi.members(ws as string)), enabled: !!ws });
}
export function useInvitations(enabled = true) {
  const ws = useSession((s) => s.workspaceId);
  return useQuery({ queryKey: teamKeys.invitations(ws ?? ""), queryFn: async () => toItems(await teamApi.invitations(ws as string)), enabled: !!ws && enabled });
}
export function useTeamMutations() {
  const ws = useSession((s) => s.workspaceId) ?? "";
  const qc = useQueryClient();
  return {
    updateRole: useMutation({ mutationFn: (v: { userId: string; role: Role }) => teamApi.updateRole(ws, v.userId, v.role), onSettled: () => qc.invalidateQueries({ queryKey: teamKeys.members(ws) }) }),
    remove: useMutation({ mutationFn: (userId: string) => teamApi.removeMember(ws, userId), onSettled: () => qc.invalidateQueries({ queryKey: teamKeys.members(ws) }) }),
    invite: useMutation({ mutationFn: (body: { email: string; role: Role }) => teamApi.invite(ws, body), onSettled: () => qc.invalidateQueries({ queryKey: teamKeys.invitations(ws) }) }),
    revoke: useMutation({ mutationFn: (id: string) => teamApi.revoke(ws, id), onSettled: () => qc.invalidateQueries({ queryKey: teamKeys.invitations(ws) }) }),
  };
}

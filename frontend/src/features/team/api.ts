import { api } from "@/lib/api";
import type { Page } from "@/lib/formatters";
import type { Membership } from "@/stores/session";

export type Role = Membership["role"];

export interface Member { user_id: string; email: string; full_name: string; role: Role; joined_at?: string | null; last_active_at?: string | null }
export interface Invitation {
  id: string; email: string; role: Role; expires_at: string; accepted_at?: string | null; created_at?: string | null;
  status?: "pending" | "accepted" | "expired" | string; token?: string | null; accept_url?: string | null;
}

export const teamApi = {
  members: (ws: string) => api.get<Page<Member> | Member[]>(`/workspaces/${ws}/members`),
  updateRole: (ws: string, userId: string, role: Role) => api.patch<Member>(`/workspaces/${ws}/members/${userId}`, { role }),
  removeMember: (ws: string, userId: string) => api.delete<unknown>(`/workspaces/${ws}/members/${userId}`),
  invitations: (ws: string) => api.get<Page<Invitation> | Invitation[]>(`/workspaces/${ws}/invitations`),
  invite: (ws: string, body: { email: string; role: Role }) => api.post<Invitation>(`/workspaces/${ws}/invitations`, body),
  revoke: (ws: string, id: string) => api.delete<unknown>(`/workspaces/${ws}/invitations/${id}`),
  accept: (token: string) => api.post<{ workspace: { id: string; name: string; slug: string }; role: Role }>(`/invitations/${encodeURIComponent(token)}/accept`, {}),
};

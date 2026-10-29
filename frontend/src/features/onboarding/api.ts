import { api } from "@/lib/api";
import type { Membership } from "@/stores/session";

export interface WorkspaceCreated { id: string; name: string; slug: string; role?: Membership["role"] | null }

export const onboardingApi = {
  createWorkspace: (body: { name: string; slug?: string }) => api.post<WorkspaceCreated>("/workspaces", body),
  setWorkspaceTimezone: (timezone: string) => api.put<unknown>("/settings/workspace", { timezone }),
};

export function slugify(s: string): string {
  return s.toLowerCase().normalize("NFKD").replace(/[̀-ͯ]/g, "").replace(/[^a-z0-9]+/g, "-").replace(/^-+|-+$/g, "").slice(0, 48);
}

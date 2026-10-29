import { create } from "zustand";
import { persist } from "zustand/middleware";

export interface User { id: string; email: string; full_name: string; avatar_url?: string | null; preferences?: Record<string, unknown> }
export interface Membership { workspace: { id: string; name: string; slug: string }; role: "owner" | "admin" | "editor" | "approver" | "viewer" }

interface SessionState {
  accessToken: string | null;
  user: User | null;
  memberships: Membership[];
  workspaceId: string | null;
  workspaceSlug: string | null;
  role: Membership["role"] | null;
  brandId: string | null;
  hydrated: boolean;
  setAuth: (token: string, user: User, memberships?: Membership[]) => void;
  setWorkspace: (slugOrId: string) => void;
  setBrand: (brandId: string | null) => void;
  clear: () => void;
  setHydrated: () => void;
}

export const useSession = create<SessionState>()(
  persist(
    (set, get) => ({
      accessToken: null, user: null, memberships: [], workspaceId: null, workspaceSlug: null, role: null, brandId: null, hydrated: false,
      setAuth: (token, user, memberships) => {
        const ms = memberships ?? get().memberships;
        const current = ms.find((m) => m.workspace.id === get().workspaceId) ?? ms[0];
        set({ accessToken: token, user, memberships: ms,
              workspaceId: current?.workspace.id ?? null, workspaceSlug: current?.workspace.slug ?? null, role: current?.role ?? null });
      },
      setWorkspace: (slugOrId) => {
        const m = get().memberships.find((x) => x.workspace.slug === slugOrId || x.workspace.id === slugOrId);
        if (m) set({ workspaceId: m.workspace.id, workspaceSlug: m.workspace.slug, role: m.role, brandId: null });
      },
      setBrand: (brandId) => set({ brandId }),
      clear: () => set({ accessToken: null, user: null, memberships: [], workspaceId: null, workspaceSlug: null, role: null, brandId: null }),
      setHydrated: () => set({ hydrated: true }),
    }),
    {
      name: "botwok-session",
      // access token is intentionally NOT persisted; it is re-obtained from the refresh cookie on load
      partialize: (s) => ({ user: s.user, memberships: s.memberships, workspaceId: s.workspaceId, workspaceSlug: s.workspaceSlug, role: s.role, brandId: s.brandId }),
      onRehydrateStorage: () => (state) => state?.setHydrated(),
    },
  ),
);

/** Backend auth payloads return either `memberships[]` or a single `workspace` + `role`; normalize to memberships. */
export function membershipsFrom(d: { memberships?: Membership[]; workspace?: { id: string; name: string; slug: string; role?: string } | null; role?: string | null }): Membership[] {
  if (Array.isArray(d.memberships) && d.memberships.length) return d.memberships;
  if (d.workspace) return [{ workspace: { id: d.workspace.id, name: d.workspace.name, slug: d.workspace.slug }, role: ((d.role ?? d.workspace.role ?? "editor") as Membership["role"]) }];
  return [];
}

export const ROLE_RANK = { viewer: 0, approver: 1, editor: 2, admin: 3, owner: 4 } as const;
export function hasRole(role: SessionState["role"], needed: keyof typeof ROLE_RANK) {
  return !!role && ROLE_RANK[role] >= ROLE_RANK[needed];
}

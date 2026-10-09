"use client";
/** Capability helpers for the RBAC matrix in doc 00 §4 (editors create but cannot approve). */
import { hasRole, useSession, type Membership } from "@/stores/session";

type Role = Membership["role"] | null;

export function capabilities(role: Role) {
  return {
    view: !!role,
    /** Create/edit content, run AI, research (owner, admin, editor, approver). */
    create: hasRole(role, "approver"),
    /** Approve / reject (owner, admin, approver). */
    approve: role === "owner" || role === "admin" || role === "approver",
    /** Members, API keys, social accounts, brand & AI settings (owner, admin). */
    manage: hasRole(role, "admin"),
    owner: role === "owner",
  };
}

export function useCan() {
  const role = useSession((s) => s.role);
  return capabilities(role);
}

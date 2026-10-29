/** Social account types (doc 17 §Social; backend/app/models/social.py). */

export type CapabilityValue = boolean | { available?: boolean; ok?: boolean; status?: "available" | "degraded" | "unsupported" | string; reason?: string | null } | null;

export interface SocialAccount {
  id: string;
  brand_id?: string;
  platform: string;
  auth_flavor?: string | null;
  external_id?: string;
  display_name: string;
  handle?: string | null;
  avatar_url?: string | null;
  account_type?: string | null;
  status: "active" | "expired" | "revoked" | "error" | "disconnected" | string;
  scopes?: string[];
  capabilities?: Record<string, CapabilityValue>;
  health?: { token_valid?: boolean; expires_at?: string | null; scopes_missing?: string[]; error?: string | null; [k: string]: unknown } | null;
  last_probe_at?: string | null;
  expires_at?: string | null;
  token_expires_at?: string | null;
  refresh_strategy?: string | null;
  scheduled_posts_count?: number | null;
  created_at?: string;
}

export interface AccountHealth {
  token_valid?: boolean;
  scopes_missing?: string[];
  capabilities?: Record<string, CapabilityValue>;
  limits_remaining?: Record<string, unknown> | null;
  error?: string | null;
}

export interface ConnectableAccount {
  external_id: string;
  display_name?: string | null;
  handle?: string | null;
  avatar_url?: string | null;
  account_type?: string | null;
  already_connected?: boolean;
  disabled_reason?: string | null;
  linked_page?: string | null;
}

export function capabilityState(v: CapabilityValue): "available" | "degraded" | "unsupported" {
  if (v === true) return "available";
  if (!v) return "unsupported";
  if (v.status === "degraded") return "degraded";
  if (v.status === "available" || v.available || v.ok) return "available";
  return "unsupported";
}

export function tokenExpiry(a: SocialAccount): string | null {
  return a.expires_at ?? a.token_expires_at ?? (a.health?.expires_at as string | null | undefined) ?? null;
}

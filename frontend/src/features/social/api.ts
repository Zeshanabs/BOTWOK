import { api, qs } from "@/lib/api";
import type { Page } from "@/lib/formatters";
import type { AccountHealth, ConnectableAccount, SocialAccount } from "./types";

export const socialApi = {
  accounts: (brandId?: string | null) => api.get<Page<SocialAccount> | SocialAccount[]>(`/social/accounts${qs({ brand_id: brandId })}`),
  connect: (platform: string, params: { brand_id?: string | null; flavor?: string; reconnect_account_id?: string }) =>
    api.get<{ auth_url: string; state?: string }>(`/social/connect/${platform}${qs(params)}`),
  /** Assumed endpoint: lists the candidate accounts held under a selection token after the OAuth callback. */
  selection: (platform: string, token: string) =>
    api.get<{ accounts?: ConnectableAccount[]; items?: ConnectableAccount[] } | ConnectableAccount[]>(`/social/connect/${platform}/select${qs({ selection_token: token })}`),
  select: (platform: string, body: { selection_token: string; external_id: string }) => api.post<SocialAccount>(`/social/connect/${platform}/select`, body),
  test: (id: string) => api.post<AccountHealth>(`/social/accounts/${id}/test`, {}),
  refresh: (id: string) => api.post<SocialAccount>(`/social/accounts/${id}/refresh`, {}),
  disconnect: (id: string, force = false) => api.delete<unknown>(`/social/accounts/${id}${force ? "?force=true" : ""}`),
};

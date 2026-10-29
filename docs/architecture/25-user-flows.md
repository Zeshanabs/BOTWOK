# 25 — Complete User Flows

> Conforms to `00-canonical-vocabulary.md` (tables, statuses, events, services, agent ids, roles, routes). Mechanics follow docs 05 (orchestrator), 11 (publishing), 12 (scheduling), 13 (analytics), 14 (automation) and 18 (events). Column and payload names are illustrative (doc 16 and `17-api-architecture.md` win); platform specifics defer to the capability matrix (doc 26) and integration details (doc 27).

## How to read this document

**Step notation.** Each flow is a numbered sequence; within a step, layers appear in this order and are omitted when not involved: **UI** (page/component and action) → **API** (method + route from doc 00 §14, with role) → **Service** (service + method) → **DB** (tables written, status transitions) → **Event** (emitted via `EventBus`) → **Job** (Procrastinate job + queue) → **External** (platform/provider API) → **UI result** (what the user sees, including live updates from `GET /api/v1/events/stream`). Each flow ends with **Failure branches** (*condition → status/event → what the user sees → recovery*) and **Audit & transparency**.

**Roles.** `[manage]` = owner, admin · `[create]` = owner, admin, editor, approver · `[approve]` = owner, admin, approver · `[schedule]` = owner, admin, approver, plus editor for approved content · `[view]` = all. Every route except `/auth/*`, `/invitations/*`, OAuth callbacks and `/webhooks/*` requires an authenticated workspace member; RBAC is enforced in the API dependency layer and re-checked in services; 403s are audited.

### Shared mechanics

**⟨TX⟩ Transactional writes.** A step's domain rows, one `events_outbox` row per event and (for user actions) an `audit_logs` row commit in one transaction. The EventBus relay publishes committed rows to Redis; each consumer (NotificationService, AutomationEngine trigger matcher, SSE gateway, cache invalidators) runs as its own job. "**Event** X" means X commits with that step's state change. Events carry `event_id`, `workspace_id`, `occurred_at`, `actor`; the log is browsable at `GET /api/v1/admin/events` `[manage]`.

**⟨SSE⟩ Live updates.** One `GET /api/v1/events/stream` per tab, filtered by workspace and role, resumable via `Last-Event-ID`. It also carries ephemeral progress frames (token deltas, poll progress) that are not domain events. The UI invalidates caches by event type and polls every 5 s while disconnected.

**⟨JOB⟩ Jobs and the scheduler.** Procrastinate tasks named `jobs.<domain>.<verb>` run on queues `ai`, `research`, `publishing`, `analytics`, `media`, `automation`, `notifications`, `maintenance`, enqueued in the same transaction as the row they serve (a committed row always has its job; a rollback leaves none); `queueing_lock` prevents duplicates. Time-based work belongs to the **scheduler** process (doc 12): one leader (advisory lock `botwok:scheduler`) loops every 5 s through `dispatch_due_posts()`, `dispatch_retries()`, `materialize_recurring()`, `dispatch_analytics_cadence()`, `dispatch_automation_cron()`, `expire_approvals()`, `expire_leases()` and daily maintenance enqueues. It only enqueues (Appendix A).

**⟨AI-RUN⟩ AI run lifecycle.** `AIService.create_run()` → `BudgetGuard.preflight()` estimates and reserves cost (or refuses if a `usage_budgets` limit would be exceeded) → `ai_runs` `queued` → `jobs.ai.run` on `ai`. The worker moves `queued → planning` (`AI_RUN_STARTED`); `Planner` emits a JSON DAG that `PlanValidator` checks, persisted as `ai_tasks` (`pending`, roots `ready`); the run goes `running` and `Executor` runs ready tasks concurrently (`max_parallel` default 3), materializing fan-out child tasks with their own ledger rows. LLM calls write `ai_calls` + `usage_ledger`; tool calls write `ai_tool_calls`; a task reaching `succeeded` emits `AI_RUN_STEP_COMPLETED`. `ApprovalGate` can park the run in `awaiting_approval` (`AI_RUN_AWAITING_APPROVAL`) until `POST /api/v1/ai/runs/{runId}/resume`. Terminal: `completed` (`AI_RUN_COMPLETED`), `failed` (`AI_RUN_FAILED`), `cancelled`; the reservation is settled against actual cost, and crossing 80%/100% emits `BUDGET_THRESHOLD_REACHED`/`BUDGET_EXCEEDED`. Every AI result links to the Run Inspector (`GET /api/v1/ai/runs/{runId}`, `/steps`, `/tool-calls`).

**⟨AI-FAIL⟩ AI failures (every run).** (1) Preflight refusal → no run; `budget_exceeded` with a link to budget settings. (2) Budget exhausted mid-run → task fails, dependents `skipped`, run `failed` with partial deliverables kept. (3) Provider error → 3 retries with backoff, then the tier's fallback model; else the task fails (and the run, if the task is required); "Retry from this step" re-enqueues with `resume_from=task_id`. (4) Schema-invalid output → one repair, then `failed`. (5) Worker crash → the Executor resumes from the ledger, re-running only `running` tasks with no heartbeat for 2 min (tools are idempotent per `(run_id, task_id, call_index)`). (6) `POST /api/v1/ai/runs/{runId}/cancel` → cooperative cancel → `cancelled`.

**⟨NOTIFY⟩** `NotificationService.notify()` writes a `notifications` row per recipient (`NOTIFICATION_CREATED`) and enqueues `jobs.notifications.deliver` per enabled channel (email, Slack, outgoing `webhooks`).

**⟨AUDIT⟩** `AuditService.record()` writes an immutable `audit_logs` row: actor (user, API key or `system:<job>`), action (`domain.verb`), target, redacted diff, request id, linked `ai_run_id`/`automation_run_id`. Admins read it at Settings ▸ System ▸ Audit log (`GET /api/v1/admin/audit-logs`); every entity has an "Activity" tab `[view]`.

---

## A. New user onboarding

Precondition: a fresh local install (`docker compose up`) with migrations applied and the `users` table empty. Because the install is local-first, the first person to sign up becomes **owner** of the first workspace, and email verification is not required.

1. **UI** The app calls `GET /api/v1/auth/me` and gets 401 with `bootstrap_required: true`, so it redirects to `/signup`. The form asks for name, email, password and workspace name; the browser's IANA timezone is sent with it.
2. **API** `POST /api/v1/auth/signup` (unauthenticated).
   - **Service** `AuthService.signup()` takes advisory lock `bootstrap`. It finds zero users, so it calls `WorkspaceService.create_workspace(owner=user)`.
   - **DB** `users` (argon2id hash, `email_verified_at = null`), `workspaces`, `workspace_members` (`role = owner`), default `ai_settings` and `usage_budgets`, `refresh_sessions`.
   - **Event** None. The catalog has no user or workspace events, so this step is ⟨AUDIT⟩ only.
   - **UI result** An in-memory access JWT plus a rotating httpOnly refresh cookie, then a redirect to `/onboarding`.
   - From now on, signup is refused unless `ALLOW_PUBLIC_SIGNUP=true`. Everyone else joins by invitation.
3. **Step 1, Workspace.** **UI** Name, slug, timezone, week start. **API** `PATCH /api/v1/workspaces/{ws}` `[manage]`. Wizard progress is saved via `PUT /api/v1/settings/workspace`.
4. **Step 2, System check.** **API** `GET /api/v1/admin/health` `[manage]` checks Postgres + pgvector, Redis, MinIO, worker heartbeats per queue, outbound internet, and `PUBLIC_MEDIA_BASE_URL` (required by platforms that fetch media by URL; doc 26).

   **UI result** Green, amber or red rows with fix hints. Amber does not block.
5. **Step 3, AI providers.** **UI** Pick a model per tier plus an embedding model. Hosted APIs and OpenAI-compatible local endpoints are both supported.
   - **API** `PUT /api/v1/ai/settings` `[manage]`.
   - **Service** `AIService.update_settings()` encrypts credentials (TokenVault's envelope scheme) and test-calls each tier.
   - **UI result** Pass/fail, latency and cost per tier. The step can be skipped, in which case AI features show "No provider configured".
6. **Step 4, Budget.** **API** `PUT /api/v1/settings/budgets` writes `usage_budgets`: monthly cap, per-run cap, alert threshold, and the amount above which a plan needs confirmation.
7. **Steps 5–6.** First brand (B) and social accounts (C/D). Both can be skipped.
8. **Step 7, Invite team.**
   - **API** `POST /api/v1/workspaces/{ws}/invitations` `[manage]` writes `invitations` (hashed token, role, 7-day expiry).
   - The invite is emailed via ⟨NOTIFY⟩ if SMTP is configured; otherwise the owner gets a copyable link.
   - The invitee signs up (invites bypass the signup lock) or logs in. Then `POST /api/v1/invitations/{token}/accept` writes `workspace_members`.
9. **UI result** `/w/[workspace]/dashboard`, with a "Getting started" checklist built from real state: brand, account, first idea, approval, scheduled post.

**Failure branches**
- **Concurrent bootstrap signups** → the advisory lock serializes them; the loser gets 409 `bootstrap_complete` → redirect to `/login`.
- **Signup while locked** → 403 `signup_disabled` → "Ask your workspace owner for an invitation."
- **Health check red** (e.g. no `publishing` worker) → remediation hint; work stays queued until a worker starts.
- **Provider test fails** → settings saved as `unverified` → banner → re-test from Settings ▸ AI.
- **Forgotten password and no SMTP** → CLI `botwok admin reset-password`, audited as `system:cli`.

Optional email verification (`users.email_verified_at`) becomes available once SMTP is configured. Its route is proposed in Appendix B.

**Audit & transparency.**
- ⟨AUDIT⟩ records `auth.signup` (`bootstrap=true`), `workspace.create`, `member.add`, `ai_settings.update` (key fingerprint only), `budget.update`, `invitation.create`, `invitation.accept`, and logins.
- Settings ▸ Team lists members and pending invites (`GET /api/v1/workspaces/{ws}/invitations`). An invite can be revoked with `DELETE …/invitations/{id}`.

---

## B. Adding a brand

Every brand write requires `[manage]`. Both paths below end in a BrandContext, which every agent receives.

### B1. Manual form

1. **UI** Brand switcher ▾ → "New brand": name, website, description, industry, audiences, voice (tone sliders, do/don't lists, example sentences), banned words, CTAs, hashtag/emoji policy, languages, timezone, default platforms.

   **API** `POST /api/v1/brands` → `BrandService.create_brand()`. **DB** `brands`, `brand_settings`. **Event** None in the catalog (⟨AUDIT⟩ only).
2. **UI** Pillars tab: 3–6 pillars, each with a description, target share and example topics. **API** `POST /api/v1/brands/{brandId}/pillars` → `content_pillars`. The UI warns if the shares don't sum to 100%.
3. **UI** Assets tab: logo, palette, fonts, reference images, style-guide PDFs.
   - **API** `POST /api/v1/media/upload-url` returns a presigned MinIO URL. The browser PUTs the file there directly, then calls `POST /api/v1/brands/{brandId}/assets` `{media_id, kind}`.
   - **DB** `media_assets` (`origin = uploaded`), `brand_assets`.
   - **Job** `jobs.media.process` (`media`) builds thumbnails and extracts colors. Style-guide text is embedded as brand memory via `MemoryService`.
   - **Event** `MEDIA_PROCESSED`.
4. **Service** `BrandService.build_brand_context()` invalidates the cached BrandContext in Redis. Each AI run snapshots the context into `ai_runs.input`, so runs stay reproducible.
   **UI** "Preview as the AI sees it" calls `GET /api/v1/brands/{brandId}/context`.

### B2. Import from website

1. **UI** "Import from website" with a URL. The client first creates a minimal brand (`POST /api/v1/brands` with name and website).
2. **API** `POST /api/v1/brands/{brandId}/import-from-website` `{url, max_pages: 15}`.
   - **Service** `BrandService.import_from_website()` → `ResearchService.run(kind="brand_import")`. An SSRF guard rejects private and loopback addresses.
   - **DB** `research_runs`, plus `ai_runs` with lead agent `research` (⟨AI-RUN⟩).
   - **Event** `RESEARCH_STARTED`. **Job** `jobs.research.run` (`research`).
   - **UI result** A live step list: "Reading homepage… About… Pricing… Extracting voice… Proposing pillars…"
3. **Job** The `research` agent uses `web.fetch` (robots.txt honored, identifying user agent, 1 req/s per host), `web.extract`, same-origin discovery via sitemap and navigation, and `research.save_source`.

   **DB** `research_sources`, `research_documents`, `research_chunks` (embedded). **Event** `SOURCE_SAVED` for each source.
4. **Job** The agent outputs a `BrandProposal` — description and value propositions, audiences, voice attributes (with sentences quoted from the site), 3–6 pillars, words to avoid, CTAs, social handles found in links, logo and colors — where every field carries `value`, `confidence` and `source_ids[]`.

   **DB** The proposal is stored only in the run outputs; `brands` is not touched yet. **Event** `RESEARCH_COMPLETED`, `AI_RUN_COMPLETED`.
5. **UI** Review screen: current vs proposed values side by side, accept/edit/reject per field; citation chips open the saved source; fields below 0.6 confidence start unchecked; detected handles become "Connect" shortcuts (C/D) and competitor seeds (never auto-connected).
6. **API** "Apply selected" sends `PATCH /api/v1/brands/{brandId}`, `PUT /api/v1/brands/{brandId}/settings`, one `POST …/pillars` per accepted pillar, and for an accepted logo a server-side fetch into MinIO plus `POST …/assets`.

   **UI result** Each applied field shows a "from website" chip.

**Failure branches**
- **Site unreachable** → `RESEARCH_FAILED` + `AI_RUN_FAILED` → "Couldn't reach the site" → retry, or fill in the manual form.
- **Pages disallowed by robots.txt** → those `ai_tasks` are `skipped` → the proposal notes "4 pages skipped per robots.txt".
- **Site renders only with JavaScript** → low-confidence proposal → paste About text as a user-provided source and re-run.
- **Private or loopback URL** → 422 `url_not_allowed` (unless `ALLOW_PRIVATE_FETCH=true`).
- **Duplicate brand name** → 409.
- **Other AI failures** → ⟨AI-FAIL⟩.

**Audit & transparency.**
- ⟨AUDIT⟩ records `brand.create`, `brand.update` (with diff), `brand_settings.update`, `pillar.create` and `brand_asset.add`.
- It also records `brand.import_applied`, with the accepted/rejected fields and the `research_run_id`.
- The brand's History tab shows each change and where it came from.

---

## C. Connecting Instagram

Role: `[manage]`.

**Prerequisites.** Meta app credentials saved (encrypted) under Settings ▸ System ▸ Platform apps; `{PUBLIC_BASE_URL}/api/v1/social/callback/instagram` registered as a redirect URI (redirect rules vary by platform, doc 26, so setup shows the exact URI).

**Two auth flavors, one adapter.** `InstagramAdapter` (doc 11) supports both; `social_accounts.adapter` records the flavor. **Facebook Login** (default; "Instagram API with Facebook Login for Business") needs an Instagram **Professional** (Business/Creator) account **linked to a Facebook Page** on which the user has a role that can manage it. **Instagram Login** ("Instagram API with Instagram Login") needs no Page but still a Professional account. Coverage differs (doc 26).

### Steps

1. **UI** Settings ▸ Social Accounts → "Connect Instagram". A checklist asks "Professional account? Linked to a Page you manage?" and links to help. Choosing "I don't have a Facebook Page" switches to Instagram Login. The user also picks a brand.
2. **API** `GET /api/v1/social/connect/instagram?brand_id=…&method=facebook_login` `[manage]` → `SocialAccountService.begin_connect()`.
   - **DB** `oauth_states`: a hash of a 256-bit state, `platform`, `method`, `workspace_id`, `brand_id`, `user_id`, `redirect_uri`, `code_verifier` (if PKCE), `expires_at` (+10 min) and `consumed_at = null`.
   - **UI result** The browser goes to the Meta OAuth dialog (`adapter.auth_url()`) with `client_id`, `redirect_uri`, `state`, and either `scope` or a Facebook Login for Business configuration id. Permissions include `instagram_basic`, `instagram_content_publish`, `instagram_manage_insights`, `pages_show_list`, `pages_read_engagement`, and `business_management` for portfolio-owned Pages (exact set: doc 26).
3. **External** The user signs in to Facebook, selects Pages and Instagram accounts, and consents.
4. **API** `GET /api/v1/social/callback/instagram?code=…&state=…`. This route is authenticated by the state plus the session cookie.
   - **Service** `SocialAccountService.complete_connect()` consumes the state atomically: `UPDATE oauth_states SET consumed_at = now() WHERE state_hash = $1 AND consumed_at IS NULL AND expires_at > now() RETURNING *`.
   - It then checks that the session user equals `oauth_states.user_id`.
5. **External** `adapter.exchange_code()` → short-lived token → long-lived token (`fb_exchange_token`); `adapter.list_connectable_accounts()` → `GET /me/accounts` (Pages) → each Page's `instagram_business_account` → each IG user's `username`, `profile_picture_url`, `followers_count`; `GET /me/permissions` records granted vs declined permissions. Page tokens derived from a long-lived user token don't expire, but Meta can revoke data access after prolonged user inactivity (doc 27); a failing probe then prompts re-consent.
6. **DB** The candidates and TokenVault-encrypted tokens are held in `oauth_states.result` for 15 min. No `social_accounts` row exists yet.
   **UI result** 302 to the picker at `/w/[ws]/settings/social-accounts/connect/instagram?state_ref=…`. It shows each account's avatar, @username, linked Page, and an "already connected" badge where relevant. A single candidate is preselected but must still be confirmed.
7. **UI** The user picks one or more accounts.
   - **API** `POST /api/v1/social/connect/instagram/select` `{state_ref, account_ids[]}` (proposed route, see Appendix B).
   - **Service** `finalize_connect()` calls `TokenVault.encrypt()`. Encryption is envelope-style: a per-record DEK wrapped by the KEK.
   - **DB**
     - `social_accounts` is upserted on `(workspace_id, platform, platform_account_id)` with `status = active`, `account_type`, `brand_id`, `adapter` and `linked_page_id`.
     - `oauth_tokens` stores the ciphertext, `scopes_granted`, `expires_at` and `refresh_strategy`.
     - `oauth_states.result` is purged.
   - **Event** `SOCIAL_ACCOUNT_CONNECTED` `{platform, social_account_id, reconnect}`.
   - **Job** `jobs.social.probe_capabilities` (`maintenance`).
8. **Job** `adapter.probe()` + `adapter.capabilities()` check publishing quota and usage (`content_publishing_limit`), insights access, supported formats, granted vs required permissions, and that `PUBLIC_MEDIA_BASE_URL` serves a probe object through its public hostname (Instagram fetches media by URL; containers are never pre-created).

   **DB** `social_accounts.capabilities` (`publish.image|carousel|reel|story`, `insights.post|account`, `competitor.lookup`, `media.public_url_ok`) and `capabilities_checked_at`.
   **UI result** Capability chips: green = available, amber = degraded (with the reason), grey = unsupported. On a reconnect, posts that were paused for this account are listed with "Resume all".

### Instagram Login variant

`method=instagram_login` opens Instagram's authorization page with `instagram_business_*` scopes (basic, content publish, manage insights; doc 26). The code becomes a short-lived, then long-lived (~60-day) token; identity comes from `GET /me` on the Instagram Graph host. There is no Page discovery and one account per login, so the picker only confirms. Long-lived tokens are refreshable once ≥ 24 h old, so `refresh_strategy = refresh_grant` and Botwok refreshes at ~50 days (doc 27). Switching flavors is a reconnect; uncertain matches are confirmed by the user.

### Failure branches

- **User cancels or declines** → `error=access_denied` → state consumed, nothing written → "Connection cancelled."
- **State bad, expired, already consumed, or for a different user** → 400 `invalid_oauth_state` → "This link expired, start again." Audited as a possible CSRF.
- **No Pages, or a Page with no linked Instagram account** → the picker's empty state explains how to convert to Professional, link the Page, or re-select it. It offers to re-request or to "Use Instagram Login instead".
- **Some permissions declined** → the account connects with amber chips → "Grant missing permissions" re-requests them.
- **Meta app in development mode, and the user has no app role** → Meta shows an error → Botwok explains app roles and review (doc 26).
- **Token exchange fails, or Meta returns 5xx** → state consumed → "Meta didn't respond, try again."
- **Public media URL unreachable** → `media.public_url_ok = false` → amber banner: "Publishing will fail until a public media URL is configured."
- **Deauthorized later** → via Meta's deauthorization webhook to `POST /api/v1/webhooks/instagram`, or a code-190 error → `revoked` + `SOCIAL_ACCOUNT_REVOKED` → the account's posts are paused → "Reconnect".

### Audit & transparency

- ⟨AUDIT⟩ records `social_account.connect_started`, `.connected` (with granted/declined scopes and flavor), `oauth_state.rejected` and `social_account.capabilities_probed`.
- Tokens never appear in logs, API responses or the UI.
- The account drawer shows the flavor, scopes, token expiry, refresh strategy, last probe and an Activity list.

---

## D. Connecting LinkedIn

Role: `[manage]`. LinkedIn grants API products **per developer app**, so admins configure credentials per mode. **Member** (personal profile): self-serve "Sign In with LinkedIn using OpenID Connect" (`openid`, `profile`, `email`) plus "Share on LinkedIn" (`w_member_social`). **Organization** (Company Page): Community Management API scopes such as `r_organization_social`, `w_organization_social`, `rw_organization_admin` (exact set: doc 26), which LinkedIn must approve through its Marketing Developer Platform review; until the org app is marked approved and its probe passes, "Company page" is disabled with an explanation.

1. **UI** "Connect LinkedIn" → choose "Personal profile" or "Company page", and pick a brand.
2. **API** `GET /api/v1/social/connect/linkedin?brand_id=…&target=member|organization` → `begin_connect()`.
   - **DB** `oauth_states` (stores the target).
   - **UI result** Redirect to `/oauth/v2/authorization` with `response_type=code`, `state` and the chosen mode's scopes.
3. **External** The member consents.
4. **API** `GET /api/v1/social/callback/linkedin` → state and user checks (as in C.4).
   - **External** `/oauth/v2/accessToken` returns `access_token` and `expires_in` (~60 days).
   - A `refresh_token` (365-day fixed life) is returned **only** if LinkedIn has enabled programmatic refresh for the app, i.e. approved partner apps.
5. **External** Identity:
   - **Member:** `GET /v2/userinfo` (OIDC) returns `sub`, giving the URN `urn:li:person:{sub}`.
   - **Organization:** `organizationAcls` (roleAssignee finder, with the versioned `LinkedIn-Version` header) lists the orgs where the member holds an approved role. Doc 26 defines which roles may post.
6. **UI** Picker: a confirmation card for a member, or a list of orgs for an organization (orgs where the member's role is insufficient are disabled).
   - **API** `POST /api/v1/social/connect/linkedin/select`.
   - **DB**
     - `social_accounts`: `account_type = member|organization`, `platform_account_id` = URN, `status = active`.
     - `oauth_tokens`, one row per account: `expires_at`, `refresh_expires_at`, `refresh_strategy = refresh_grant|reauth`, `grant_fingerprint`. Orgs connected in a single login share one grant, so a refresh updates every row with that fingerprint.
   - **Event** `SOCIAL_ACCOUNT_CONNECTED`.
   - **Job** `jobs.social.probe_capabilities` checks posting permission, org analytics access and upload support.
   - **UI result** Capability chips, plus either "Auto-refresh: available" or "Auto-refresh: not available — reconnect every ~60 days".

### Token-expiring sub-flow (all platforms)

7. **Job** The daily token monitor, `jobs.social.check_token_expiry` (`maintenance`), runs `SocialAccountService.scan_expiring()` to find `oauth_tokens` that expire within 7 days.
   - **Refreshable** (Meta, Threads, X, TikTok, Google, Pinterest; LinkedIn only if the app has refresh tokens) → **External** `adapter.refresh()` → **DB** `oauth_tokens` updated (⟨AUDIT⟩ only). LinkedIn refresh tokens have a fixed life, so as `refresh_expires_at` nears the account falls through to re-auth.
   - **Re-auth required** → **Event** `SOCIAL_ACCOUNT_TOKEN_EXPIRING` `{social_account_id, expires_at}` (deduped at T-7d, T-3d, T-1d) → ⟨NOTIFY⟩ owners/admins. The scheduler's consumer moves posts scheduled after `expires_at` `scheduled → paused` (`pause_reason = token_expiring`). **UI result** Amber (then red) banner on Social Accounts and Dashboard; affected calendar cards read "Paused: reconnect LinkedIn". (Flow L already blocks new schedules past a non-refreshable expiry.)
8. **UI** "Reconnect" → `GET /api/v1/social/connect/linkedin?reconnect_account_id={id}` → same OAuth flow. LinkedIn may skip the consent screen; Botwok doesn't depend on it.
   - **Service** The callback verifies that the URN matches the existing account (for orgs, that the ACL list contains it).
   - **DB** `oauth_tokens` is replaced; the account goes `→ active`.
   - **Event** `SOCIAL_ACCOUNT_CONNECTED` `{reconnect: true}`.
   - **UI result** Banners clear. "Resume all" calls `POST /api/v1/scheduling/posts/{id}/resume` `[schedule]` for each paused post.
9. If the account is never reconnected, the token monitor (or the first 401) sets `social_accounts: active → expired`. Publishing pre-flight then refuses the account (Flow M).

**Failure branches**
- **Org mode, but the app lacks Community Management access** → scope error → explanation, plus "Connect personal profile instead".
- **No qualifying org role** → an empty list that names the roles required.
- **Reconnect as a different member** → 409 `account_mismatch` ("You signed in as Jane; this connection belongs to Sam") → nothing changes.
- **Refresh returns `invalid_grant`** → the strategy becomes `reauth` → `SOCIAL_ACCOUNT_TOKEN_EXPIRING` fires immediately.
- **Member revokes the app** → 401 → `revoked` + `SOCIAL_ACCOUNT_REVOKED` → posts paused → reconnect.

**Audit & transparency.**
- ⟨AUDIT⟩ records `social_account.connect_started`, `.connected` (URN and scopes), `.reconnected`, `.token_refreshed`, `.expired` and `.revoked`.
- The account drawer shows the mode, an expiry countdown, whether refresh is possible, and which posts are paused.

---

## E. Adding a competitor

Role: `[create]`.

1. **UI** Competitors → "Add competitor": name, website, handles or URLs per platform, brand, tags and notes. While a handle is being typed, the dialog shows its projected data-availability class.
2. **API** `POST /api/v1/competitors`.
   - **Service** `CompetitorService.create()` normalizes the handles and runs an SSRF check on the website.
   - `classify_availability()` then assigns each profile one class:

| Class | Meaning | Example |
|---|---|---|
| `official_api` | A permitted official API reads this third-party profile through one of the workspace's own connected accounts | IG Business/Creator competitor, via a connected IG account's lookup capability (doc 26) |
| `public_web` | The competitor's own site, blog, RSS or press pages, fetched per robots.txt | Website, blog feed |
| `search` | Mentions found through the configured web-search provider | Trade-press coverage |
| `user_provided` | Data the user enters or imports | Platforms without permitted access |
| `not_collected` | No permitted source; only the handle is stored | — |

   Botwok **never** scrapes social platforms or uses unofficial APIs. A profile reachable only that way is `not_collected`, or `user_provided` if the user opts into manual entry. Classes are recomputed when accounts or their capabilities change.
3. **DB** `competitors`, plus one `competitor_profiles` row per handle carrying `data_availability` and the reason. **Event** `COMPETITOR_ADDED`. **Job** `jobs.competitors.sync_profile` (`research`, `queueing_lock` = profile) is enqueued immediately for every `official_api` and `public_web` profile.
4. **Job** `CompetitorService.sync_profile()`:
   - **`official_api`:** The adapter performs public-profile and recent-posts lookups, using the connected account's token and rate-limit bucket at lower priority than publishing and analytics. **DB** `competitor_profiles` (only fields the platform exposes) and `competitor_posts` (upserted by platform post id).
   - **`public_web`:** `ResearchService.fetch()` plus RSS autodiscovery. **DB** `rss_feeds` and linked `research_documents`.
   - **Then, for either class:** **DB** `competitor_snapshots` (followers, posts in the last 30 days, engagement where computable, availability map). **Event** `COMPETITOR_SNAPSHOT_TAKEN`, then `COMPETITOR_UPDATED`.
5. **UI result** The competitor page shows one card per platform, filling in over SSE. Each card has a badge: "Official API", "Website only", "Search mentions", "Manual data" or "Not collected". For `user_provided` profiles, "Add data" saves manual entries or a parsed CSV via `PATCH /api/v1/competitors/{id}` with `source = user_provided`.
6. **Later syncs:**
   - On demand: `POST /api/v1/competitors/{id}/sync`, throttled to once per hour.
   - Nightly: the scheduler enqueues `jobs.competitors.sync_profile` for profiles older than 24 h.
   - Weekly deep monitoring is Flow Q.

**Failure branches**
- **Handle not found, or not a Professional account** → the class is downgraded with reason `not_found_or_not_professional` → a tooltip explains why.
- **No connected account can do lookups** → falls back to a weaker class → "Connect an Instagram account to enable official data."
- **Rate limited** → deferred until the limit resets → "Syncing — next try 14:05."
- **Website returns 4xx or is disallowed by robots.txt** → after 3 tries, the profile is marked errored.
- **Domain already tracked** → 409 → link to the existing competitor.

**Audit & transparency.**
- ⟨AUDIT⟩ logs `competitor.create` and `competitor.update`, each classification with its reason, and each sync (`system:jobs.competitors.sync_profile`, with class and counts).
- The "Data sources" panel lists each source, its class, the API or feed used, and when it was last fetched.
- Figures that come from `user_provided` data are labeled as such wherever they appear.

---

## F. Running competitor research

Role: `[create]`. There are two entry points:
- **Manual.** On the competitor page, "Run analysis" (or "Compare & analyze" for a multi-selection) calls `POST /api/v1/competitors/{id}/reports` `{competitor_ids[], period: "30d", compare_with_brand: true, sections[]}`.
- **Command Center.** A message such as "How is Acme doing on Instagram vs us this month?" calls `POST /api/v1/ai/runs` `{conversation_id, message}`.
  - `AIService.create_run()` appends the message to `ai_messages`.
  - `IntentRouter` (cheap tier) resolves the intent `competitor.analyze` and the competitor ids.
  - If the competitor is ambiguous, the assistant asks a clarifying question and no plan is created.

1. **Service** `CompetitorService.start_analysis()` → `AIService.create_run(lead_agent="competitor_intel")` (⟨AI-RUN⟩). **DB** `ai_runs`, plus `competitor_reports` linked to the run.
2. **Plan.** `competitor_intel` (powerful tier) proposes a DAG, and `PlanValidator` checks the agents, the fan-out width and the budget. If the estimate exceeds the workspace's confirmation threshold, the run goes `awaiting_approval` (`AI_RUN_AWAITING_APPROVAL`).
   **UI result** "Plan: 5 steps · est. $0.40 · ~3 min [Run] [Edit]". "Run" calls `POST /api/v1/ai/runs/{runId}/resume`.
3. **Fan-out.** Each step is an `ai_tasks` row run by `Executor`:
   - **t1 `competitors.sync`** (deterministic). Enqueues `jobs.competitors.sync_profile` for profiles older than 24 h, then waits for `COMPETITOR_SNAPSHOT_TAKEN`. **DB** `competitor_snapshots`.
   - **t2 `research`.** Collects news, launches, pricing changes and blog output for the period. **DB** a child `research_runs`, `research_sources`, `research_documents`, `research_chunks`. **Event** `RESEARCH_STARTED`, `SOURCE_SAVED`, `RESEARCH_COMPLETED`.
   - **t3 `social_listening`.** Collects mentions, hashtags and audience questions, using only the public-content APIs doc 26 permits. **DB** `research_documents` (`social_signal`), `trend_signals`.
   - **t4 `competitor_intel` analysis** (after t1–t3). Uses deterministic tools only: `competitors.get_posts`, `competitors.get_snapshots`, `analytics.compare_periods`, `analytics.breakdown`, `content.search`. It produces:
     - topic gaps, by embedding-clustering `competitor_posts` against our `content_items`
     - format-mix and cadence differences
     - engagement deltas, **only** where both sides have comparable `official_api` data

     Each finding carries its availability class, sample size and the `research_sources` it cites.
   - **t5 `report`.** Composes the report from stored outputs only: summary, per-competitor sections, gaps and opportunities, data gaps, sources.
4. **DB** `reports` (markdown with citations), `competitor_reports` (competitor ↔ report, period), `competitors.last_analyzed_at`. **Event** `REPORT_GENERATED`, `COMPETITOR_UPDATED` (once per competitor), `AI_RUN_COMPLETED`.
5. **UI result** The timeline streams progress ("Syncing 3 profiles… Reading 14 sources…"). The report opens at `/w/[ws]/reports/{id}` and also appears on each competitor's Reports tab (`GET /api/v1/competitors/{id}/reports`). From the report, the user can:
   - "Generate ideas from gaps" (Flow G, with `report_id`)
   - export via `GET /api/v1/reports/{id}/export?format=pdf|md|html` (`jobs.reports.render`)
   - compare via `GET /api/v1/competitors/compare?ids=`

**Failure branches**
- **Some profile syncs fail** → t1 still ends `succeeded`, with warnings → the report's "Data gaps" section names them.
- **Numbers don't match their tool results** → `EvidenceValidator` checks every number in t4/t5 against tool output → one repair attempt → claims that still don't match are dropped.
- **Research finds nothing** → that section reads "No public coverage found in this period."
- **No permitted listening source** → t3 is `skipped`, and the reason is shown.
- **User edits or rejects the plan** → the run is re-planned or `cancelled`.
- **t5 fails** → t1–t4 outputs are kept → "Retry from this step" re-runs t5 only.
- **Anything else** → ⟨AI-FAIL⟩.

**Audit & transparency.**
- ⟨AUDIT⟩ records `competitor.analysis_started` (with the entry point), the plan decision and `report.generated`. Every tool call is in `ai_tool_calls`.
- The report footer, "How this was made", lists agents, models, source count, cost and data availability per section, with a link to the Run Inspector.

---

## G. Generating content ideas

Role: `[create]`.

1. **UI** Ideas → "Generate ideas" drawer: brand, count (default 20, max 50), pillars (weighted toward under-served ones), platforms/formats, campaign, toggles for trends, research and performance memory, optional angle. Also started from Command Center, a competitor report (F) or a recommendation (O).
2. **API** `POST /api/v1/ideas/generate` → `ContentService.generate_ideas()` → `AIService.create_run(lead_agent="ideation")` (⟨AI-RUN⟩).
3. **Context assembly** (deterministic, before any LLM call): BrandContext; `content_pillars` with the mix gap (actual 30-day share vs target); top-k `research_chunks` by vector similarity; relevant active `trends`; `MemoryService.recall(kind=performance)`; top/bottom posts from `analytics_snapshots`; recent idea titles as negative examples. Selected ids are stored in `ai_runs.input`.
4. **Job** `ideation` (cheap tier) generates in parallel batches of 10 (one fan-out task per pillar group). Each idea: title, angle, hook, `pillar_id`, `content_type` (`content_type_t`), `format` (`content_format_t`), platforms, rationale, refs (`trend_ids`, `research_source_ids`, `insight_ids`) and an effort estimate.
5. **Dedupe** (tool `ideas.dedupe`). Title and angle are embedded and compared by pgvector cosine similarity against the brand's `content_ideas` and `content_items` from the last 180 days, and against the rest of the batch.
   - **≥ 0.92:** dropped. The idea stays in the run output with `duplicate_of`.
   - **0.85–0.92:** kept, marked `similar_to`.
   - Both thresholds are set in `ai_settings`.
6. **DB** `content_ideas` (fields, embedding, `source_ai_run_id`, refs). **Event** There is no idea event in the catalog, so the UI follows `AI_RUN_STEP_COMPLETED` (one per batch) and `AI_RUN_COMPLETED`.
7. **UI result** Cards stream in batch by batch. Near-matches show a "Similar to: <idea>" badge; dropped duplicates collapse into "6 near-duplicates removed (show)". Card actions:
   - edit (`PATCH /api/v1/ideas/{id}`)
   - discard (`DELETE /api/v1/ideas/{id}`)
   - thumbs up/down, stored as feedback memory
   - promote (`POST /api/v1/ideas/{id}/promote`, Flow H)

**Failure branches**
- **No brand voice or pillars** → generation is still allowed → "Ideas will be generic until the brand profile is complete."
- **Every idea is a duplicate** → the run is `completed` with 0 new ideas → the UI suggests a broader angle or fresh research.
- **Trends older than 14 days** → a "Scan now" button → `POST /api/v1/trends/scan`.
- **Any other failure** → ⟨AI-FAIL⟩. Batches that already completed are kept.

**Audit & transparency.**
- ⟨AUDIT⟩ records `idea.generate`, `idea.update`, `idea.delete` and `idea.promote`.
- Each card has a "Why this idea" panel showing its rationale and linking to the trends, sources and insights it drew on.
- The drawer shows the run's cost.

---

## H. Generating a post

Role: `[create]`.

1. **Entry.** There are two ways in:
   - **From an idea.** `POST /api/v1/ideas/{id}/promote` creates `content_items` (status `idea`, with a brief) and sets `content_ideas.promoted_content_id`. **Event** `CONTENT_CREATED`. **UI result** Opens `/w/[ws]/studio/[contentId]`.
   - **From a prompt.** Studio "New post" sends `POST /api/v1/content` `{brand_id, prompt, format, content_type, pillar_id, target_platform, campaign_id}`. This creates an item with status `idea` and emits `CONTENT_CREATED`.
2. **Generate.**
   - **UI** "Generate", with options: length, CTA, hashtags, sources, "cite factual claims".
   - **API** `POST /api/v1/content/{id}/generate`.
   - **Service** `ContentService.request_generation()` accepts `idea`, `draft`, `ai_generated` and `rejected`. For `needs_review` or `approved` it returns 409 `confirm_regenerate`, because regenerating withdraws the approval; the client resends with `confirm=true`. It then calls `AIService.create_run(lead_agent="writer")` (⟨AI-RUN⟩).
3. **Plan.** A fixed template, so no LLM planning is involved:
   - **t1 context.** BrandContext, pillar, brief, retrieved research and sources, performance memory for this platform and format, and the adapter's platform rules.
   - **t2 `writer`** (powerful). Writes hook, body, CTA and hashtags, using `hashtags.suggest` and `keywords.lookup`. Claims carry inline source refs. `content.create_draft` saves the version.
   - **t3 `critic`** (balanced). Runs on a *different* model or provider than t2; `BudgetGuard` routing enforces this. It scores voice, clarity, hook, platform fit and policy risk, and suggests rewrites.
   - **t4 `fact_check`.** Runs only if factual claims were reported, checking them against the cited `research_sources`. Otherwise it is `skipped`.
   - **t5 revision.** If the critic scores below 7/10 or fact-check flags unsupported claims, `writer` revises once and t3 re-scores. At most one revision loop.
4. **DB**
   - `content_versions`: one row per draft or revision, with `author_type = agent`, `agent_id`, `ai_run_id`, parent, critique and scores
   - `content_items.current_version_id`
   - `content_sources`: links each version to its `research_sources`, with the claim span and verdict
   - `content_items.status: idea|draft|rejected → ai_generated`. The guard allows skipping `draft` when the first body is agent-written.

   **Event** `CONTENT_UPDATED` and `CONTENT_STATUS_CHANGED` `{from, to}`.
5. **UI result** The draft streams in and the pill turns violet ("AI Generated"). Panels: **Critic** (scores; "Apply" per suggestion creates a user version), **Sources** (claims linked to snippets and fetch dates; unsupported red, unverified amber), **Transparency** (model per step, tokens, cost from `ai_calls`/`usage_ledger`, tool calls, `prompt_templates` version, BrandContext snapshot). Next: I, J or K.
6. **Human edits.** Autosave sends `PATCH /api/v1/content/{id}` with `expected_version_id`, which writes `content_versions` with `author_type = user`. AI provenance is sticky: the item still needs approval.
   - History and restore: `GET …/versions`, `POST …/versions/{v}/restore`.
   - Re-checks: `POST …/critique`, `POST …/fact-check`.

**Failure branches**
- **Only one model is configured** → the critic runs on that same model → shown as "Same-model critique (reduced independence)".
- **High policy risk** (e.g. a health claim) → `policy_flags` are set on the version and a red banner appears → the approver must acknowledge the flags in K.
- **User edits while a run is generating** → the run's result arrives as a new version → "AI version arrived — view diff". Unsaved text is never overwritten.
- **Other failures** → ⟨AI-FAIL⟩. The item's status changes only if t2 succeeded.

**Audit & transparency.**
- ⟨AUDIT⟩ records `content.create`, `content.generate`, `content.version_create` (user or agent) and `content.status_change`.
- The item carries a permanent "AI-assisted" label that links to every run that touched it. Approval and export views show this provenance too.

---

## I. Generating an image

Role: `[create]`.

1. **UI** Studio Media tab → "Generate image": brief (prefilled from the content), style preset, aspect ratios (from target platforms), count (1–4), provider/model (from `ai_settings`), "use brand palette/logo"
2. **API** `POST /api/v1/media/generate` `{content_id, variant_id?, brief, aspect_ratios, count, style}` → `MediaService.request_generation()` → `AIService.create_run(lead_agent="visual")` (⟨AI-RUN⟩). The preflight estimate includes the per-image cost.
3. **Job** `visual` reads the content and the brand's `brand_assets` (logo, palette, references), then writes a concept, a prompt and a negative prompt. By default it adds no text inside the image, no real-person likenesses and no third-party marks. It then calls `media.generate_image` `{prompt, size, count, seed, reference_asset_ids}`.
4. **Service** `MediaService.generate_image()`:
   1. Calls the configured `ImageProvider`, hosted or local (**External**, 120 s timeout).
   2. Runs a safety check: provider moderation, plus an optional local classifier.
   3. Writes MinIO `ws/{workspace_id}/media/{asset_id}/original.{ext}`.

   **DB** `media_assets` (`origin = ai_generated`, provider, model, prompt, seed, `ai_run_id`). **Event** `MEDIA_GENERATED`.
5. **Job** `jobs.media.process` (`media`) uses Pillow to make thumbnails, compute a perceptual hash, strip EXIF and convert to sRGB. It also writes IPTC provenance metadata marking the image as AI-generated. At publish time, adapters also set the platform's AI-generated flag where one exists (doc 27). **Event** `MEDIA_PROCESSED`.
6. **Alt text.** `visual` drafts alt text within the platform's limit (doc 26), using a vision model if one is configured. It is saved to `media_assets.alt_text` (`alt_text_source = ai`) and can be edited.
7. **Attach.** The tool writes `content_assets`: the item, an optional variant, a position, and a role (`primary`, `carousel_slide` or `cover`). **Event** `CONTENT_UPDATED`.
8. **Platform resize.** `POST /api/v1/media/{id}/transform` `{preset}` (presets: doc 26); repurposing (J) calls this automatically. **Job** `jobs.media.transform` crops by saliency, or pads with the brand color. It writes a derived `media_assets` row (`parent_id`, preset) and emits `MEDIA_PROCESSED`.
9. **UI result** Candidates fill a grid as each `MEDIA_GENERATED` arrives. The user picks one; the rest stay unattached in the Media Library. Alt text is editable, crops can be previewed per platform, and an "AI-generated" badge follows the asset everywhere.

**Failure branches**
- **Provider refuses on safety grounds** → the agent may rephrase once → if refused again, the task fails with the provider's category → "The image provider declined this prompt" → edit the brief.
- **Timeout** → one retry → then `failed`, with a "Retry" button.
- **Over budget** → ⟨AI-FAIL⟩ case 1.
- **MinIO down** → the task fails and a health banner appears. The provider cost is still recorded in `usage_ledger`.
- **Alt text missing where a platform requires it** → caught by `validate_content()` in L.

**Audit & transparency.**
- ⟨AUDIT⟩ logs `media.generate` (provider, model, prompt hash, cost), `media.alt_text_update`, `media.transform` and `content_asset.attach`.
- The asset detail page shows the prompt, model, seed, run, cost, renditions and every place the asset is used.

---

## J. Repurposing content

Role: `[create]`.

1. **UI** Studio → "Repurpose". The user picks targets: the brand's `social_accounts` (each implies a platform) and a format for each. Formats an account can't publish are disabled. The master must already have a body.
2. **API** `POST /api/v1/content/{id}/repurpose` `{targets: [{social_account_id, format}], keep_media: true}`.
   **Service** `ContentService.request_repurpose()`:
   - returns 422 if a format is unsupported;
   - for an `approved` or `needs_review` item, returns 409 `confirm_reapproval`, because new variants will need approval;
   - otherwise calls `AIService.create_run(lead_agent="repurposer")` (⟨AI-RUN⟩).
3. **Fan-out.** One optional task per target. Each task gets:
   - the master version and BrandContext
   - the platform's rules from `adapter.capabilities()`: length, hashtag/mention norms, links, line breaks, media constraints (doc 26)
   - the account's performance memory
   - the format

   It can call `hashtags.suggest`, `keywords.lookup` and `content.create_variant`. Each finished variant then gets:
   - a per-variant **`critic`** task;
   - `PublishingService.validate(variant)`, which runs the adapter's `validate_content()` (the contract's `validateContent()`) and returns error/warning codes;
   - **Job** `jobs.media.transform` for each attached asset.
4. **DB**
   - `content_variants`: item, account, platform, format, current version
   - `content_versions`: `variant_id`, `author_type = agent`
   - variant-scoped `content_assets`
   - critique, and validation stored in `content_variants.validation`

   **Event** `VARIANT_CREATED` per variant, then `CONTENT_UPDATED`. Item status changes:
   - `draft → ai_generated`
   - `approved → needs_review`. The pending approval is superseded. Posts already scheduled are unaffected, because approvals bind exact versions (K).
5. **UI result** A tabbed variant editor; each tab fills in independently over SSE. Each tab shows:
   - an "Approximate preview" (truncation point, hashtags, crop)
   - a character counter
   - the critic score
   - validation chips: red errors block scheduling, amber warnings don't

   `PATCH /api/v1/content/{id}/variants/{variantId}` creates a new version. To regenerate one variant, re-send repurpose with just that target and `replace_variant_id`.

**Failure branches**
- **One target fails** → the others still complete → the run is `completed`, with that task `failed` → its tab offers "Retry this platform".
- **Platform limit exceeded** → "Auto-fix" runs one repurposer revision constrained by the error codes.
- **Media can't meet a constraint** → error code plus a suggested action ("Trim to 90 s", "Choose another format").
- **Other failures** → ⟨AI-FAIL⟩.

**Audit & transparency.**
- ⟨AUDIT⟩ logs `content.repurpose`, `variant.create` and `variant.update`.
- Each variant shows its source master version (as a diff), the rules applied, its critic scores and its cost.

---

## K. Approving content

**V1 approval policy.** Content with *any* AI provenance (any `content_versions.author_type = agent` in master or variants, or attached `media_assets.origin = ai_generated`) requires an explicit human approval before scheduling; there is no auto-approve and automations cannot bypass it. For human-only content, `[approve]` roles may "Approve & schedule" (recorded as a self-approval); editors always request approval. In single-user installs the owner may approve their own AI content as a deliberate action on the review screen. Each approval binds a **snapshot** (master version id, each variant's version id, media ids) that scheduling and publishing check.

1. **Request.** **UI** Studio → "Request approval": approvers (`[approve]` members or "any approver"), a due date and a note. A pre-check shows the critic score, validation errors, unverified claims and missing alt text.
   - **API** `POST /api/v1/content/{id}/request-approval` `[create]`.
   - **Service** `ApprovalService.request()` requires status `draft` or `ai_generated` and no variant validation errors. Warnings are allowed.
   - **DB**
     - `approvals`: subject `content_item`, `pending`, `snapshot` and its hash, `requested_by`, assignees, `due_at`, `expires_at` (+7 days)
     - any earlier `pending` approval → `expired` (superseded)
     - `content_items.status → needs_review`
   - **Event** `APPROVAL_REQUESTED`, `CONTENT_STATUS_CHANGED`. ⟨NOTIFY⟩ the assignees, with a deep link.
2. **Review.** The inbox is `GET /api/v1/approvals?status=pending` `[approve]`; editors see their own requests read-only. `GET /api/v1/approvals/{id}` shows:
   - previews at the snapshot versions
   - a diff against the last approved version
   - critic scores, fact-check verdicts and policy flags
   - AI provenance (runs, models, cost)
   - media with alt text

   Reviewers can anchor inline comments to text ranges.
3. **Decide** `[approve]`. **Service** `ApprovalService.decide()` locks the row. If the snapshot hash has changed, it returns 409 `stale_snapshot`.
   - **Approve:** `POST /api/v1/approvals/{id}/approve` `{snapshot_hash, comment, acknowledged_flags[]}`. Every red policy flag must be acknowledged.
     - **DB** `approvals: pending → approved`; `content_items: needs_review → approved`.
     - **Event** `CONTENT_APPROVED`, `CONTENT_STATUS_CHANGED`. ⟨NOTIFY⟩ the requester.
     - If the subject is an `ApprovalGate` task or an automation `approve` step, its resume hook continues it (Q).
   - **Reject:** `POST /api/v1/approvals/{id}/reject` `{resolution: "rejected", comment}`.
     - **DB** `approvals → rejected`; item `needs_review → rejected`.
     - **Event** `CONTENT_REJECTED`, `CONTENT_STATUS_CHANGED`.
   - **Request changes:** same route, with `{resolution: "changes_requested", comment, annotations[]}`.
     - **DB** `approvals → rejected` (resolution recorded); item `needs_review → draft`.
     - **Event** `CONTENT_REJECTED` `{resolution: "changes_requested"}`, `CONTENT_STATUS_CHANGED`.
     - **UI result** The comments appear in Studio's Review panel. "Revise with AI" passes them to `writer` (H).
4. **UI result** The item leaves every inbox and its card turns emerald. Studio shows "Approved by Dana · 10:42 · covers master v7, Instagram v3, LinkedIn v2", and scheduling is enabled.
5. **Edits after approval.** Changing any covered version moves the item `approved → needs_review`. `scheduled_posts` whose version is no longer covered move `scheduled → paused` (`pause_reason = content_changed`), and the user is prompted to re-request approval.
6. **Expiry.** The scheduler's `expire_approvals()` expires overdue approvals. The item stays `needs_review` and the requester is notified. A reminder is sent at `due_at`.

**Failure branches**
- **No other `[approve]` member exists** (outside solo mode) → the request is blocked → "Add an approver".
- **Content is edited during review** → the approval is superseded → the approver sees "Content changed — review the new version."
- **Two approvers decide at the same time** → the second gets 409: "Already approved by Sam."
- **Someone without the role tries to decide** → 403, audited.

**Audit & transparency.**
- ⟨AUDIT⟩ records `approval.request`, `approval.approve` and `approval.reject`, each with resolution, comment, snapshot hash and acknowledged flags. These records cannot be deleted.
- Studio's Review history lists every decision.
- The approved badge names the approver and the exact versions covered.

---

## L. Scheduling content

Role: `[schedule]`.

1. **UI** Two entry points:
   - Studio → "Schedule" on a variant of an approved item.
   - Calendar (`/w/[ws]/calendar`) → drag an approved card from the "Ready to schedule" tray onto a slot.
2. **Best times.** `POST /api/v1/scheduling/best-times` `{brand_id, platform, social_account_id, date_range, count}`. **Service** `SchedulingService.best_times()` (doc 12):
   - computes engagement rate by local weekday × hour over 90 days of `post_metrics`, needing n ≥ 3 per cell and otherwise blending with platform priors;
   - adds audience-activity data from `account_metrics` where the platform exposes it (doc 26);
   - excludes slots that are taken, too close to another post (per-platform minimum gaps), or beyond token expiry.

   **UI result** The top slots, each with a score and its evidence ("based on 37 posts" vs "generic prior").
3. **Submit.** `POST /api/v1/scheduling/posts` `{variant_id, social_account_id, scheduled_at, timezone, first_comment?, options}`. **Service** `SchedulingService.schedule()` applies these guards in order:
   1. **Approval.** The variant version must be covered by an `approved` snapshot.
   2. **Account and token.** The account must be `active` and capable of the format. A token that expires before `scheduled_at` and **can't be refreshed** blocks the request (422 `token_expires_before_publish`, with a reconnect prompt).
   3. **Content.** `PublishingService.validate()` runs the adapter's `validate_content()`: length, hashtags, mentions, links, media count/format/size/aspect/duration, alt text. Errors return 422 with codes; warnings come back for display.
   4. **Limits.** The adapter's rolling-window publishing quota (e.g. Instagram's `content_publishing_limit`; values in doc 26), counted over `scheduled_posts` and `published_posts`, plus workspace caps.
   5. **Time.** At least 2 minutes in the future.

   **DB** `scheduled_posts`: `status = scheduled`, `scheduled_at` (UTC), IANA `timezone`, variant and account, `attempt_count = 0`, `max_attempts = 5`, `idempotency_root`. A partial unique index blocks a second live schedule for the same variant and account.
   **Event** `POST_SCHEDULED`.
4. **UI result** A sky-blue "Scheduled" card (warnings in its tooltip), also listed in `GET /api/v1/publishing/queue`. Per doc 00, `queued` displays as Scheduled, `paused` as Scheduled with a Paused badge, and `cancelled` falls back to the content status.
5. **Drag-and-drop reschedule.** The card moves optimistically while `PATCH /api/v1/scheduling/posts/{id}` `{scheduled_at, timezone}` is sent.
   - Allowed in `scheduled`, and in `queued` while waiting for a retry, which cancels the pending job and returns the post to `scheduled`.
   - Guards 2–5 re-run.
   - **Event** `POST_RESCHEDULED` `{old_scheduled_at, new_scheduled_at}`.
   - If the post is `publishing`, the server returns 409 and the card snaps back ("Already publishing").
   - DST: times that don't exist shift forward; ambiguous times resolve to the first occurrence.
6. **Other actions** (doc 12.4):
   - **Pause / resume.** Pause from `scheduled`; resume returns the post to `scheduled`, asking for a new time if the old one has passed.
   - **Cancel.** From `scheduled`, `queued`, `paused` or `failed` → `cancelled`, `POST_CANCELLED`.
   - **Recurring.** `POST /api/v1/scheduling/recurring` writes `recurring_schedules` (RRULE). The scheduler's `materialize_recurring()` creates posts 14 days ahead; each still needs an approved version.

**Failure branches**
- **Not approved** → 409 `approval_required` → "Request approval".
- **Validation errors** → 422 with codes → the field is highlighted in the variant editor ("Caption 2,412 / 2,200").
- **Quota exceeded** → 422 `quota_exceeded` → the next free slot is suggested.
- **Account expired or revoked** → 409 `account_unavailable` → reconnect (C/D).
- **Dropped in the past** → 422. **Dropped while `publishing`** → 409; the card snaps back.

**Audit & transparency.**
- ⟨AUDIT⟩ logs `scheduled_post.create`, `.reschedule` (old and new times), `.pause`, `.resume` and `.cancel`. The card's History popover shows these.
- Warnings are stored on the row and shown on the card.

---

## M. Publishing content

This flow is system-driven. `[schedule]` is needed only for publish-now and manual retry. The mechanics follow docs 11 and 12.

### M1. Dispatch (scheduler leader, every 5 s)

`dispatch_due_posts()`:

```sql
UPDATE scheduled_posts SET status = 'queued', queued_at = now()
WHERE id IN (SELECT id FROM scheduled_posts
             WHERE status = 'scheduled' AND scheduled_at <= now()
             ORDER BY priority DESC, scheduled_at
             FOR UPDATE SKIP LOCKED LIMIT 50)
RETURNING id, attempt_count;
```

- **Enqueue in the same transaction.** Each claimed row gets `jobs.publishing.publish_post(scheduled_post_id, attempt_no = attempt_count + 1)` on `publishing`, with `queueing_lock = publish:{id}`. If the transaction fails, neither the status change nor the job survives. The `scheduled → queued` change emits no event.
- **Missed window** (the machine was asleep or off). Overdue rows dispatch immediately. Rows older than `late_tolerance` (default 6 h) are instead held: `scheduled → paused`, and ⟨NOTIFY⟩ asks "Missed window — publish now or reschedule?" Stale content is never posted silently.
- **Publish now.** `POST /api/v1/publishing/publish-now` `{variant_id, social_account_id}` runs the same guards as Flow L, then sets `scheduled_at = now()` and `priority = 10`. It takes the same path, with no bypass.

### M2. Publish worker

**Job** `jobs.publishing.publish_post` (`publishing`). **Service** `PublishingService.publish()`:

1. **Check-and-set.** Lock the row with `SELECT … FOR UPDATE`. Proceed only if `status = queued` and `attempt_count = attempt_no − 1`; otherwise do nothing, since this is a stale or duplicate job. If a `published_posts` row already exists, mark the post `published` and stop.
2. **Pre-flight.** Version still covered by the approval snapshot; account `active`; `validate_content()` passes again; no post with the same `request_fingerprint` on this account within 24 h ("possible duplicate", user may override); public media URL available where needed; rate-limiter slot granted (publishing outranks analytics).
3. **Record the attempt.**
   - **DB** `queued → publishing`, `attempt_count = attempt_no`. A new `publish_attempts` row with `status = running`, `idempotency_key = {idempotency_root}:{attempt_no}` and `request_fingerprint`; its `state` is carried over from the previous attempt.
   - **Event** `PUBLISH_STARTED`.
   - This commits **before** any external call.
4. **External: `adapter.publish()`.** The adapter writes intermediate ids into `publish_attempts.state` as it goes, so a retry **resumes** rather than restarts.
   - **Instagram** (doc 27): `POST /{ig-id}/media` (public `image_url`/`video_url`, caption; carousel children first) → save `creation_id` → poll `status_code` via `adapter.get_status()` until `FINISHED` → `POST /{ig-id}/media_publish` → read `permalink`. Containers are created only at publish time.
   - **LinkedIn:** `POST /rest/posts` with the author URN and the `LinkedIn-Version` header. Media goes through `initializeUpload`, then a binary PUT.
5. **Record success.**
   - **DB** `published_posts` (`external_id`, `external_url`, `published_at`); `publish_attempts.status = succeeded`; `publishing → published`.
   - **Event** `PUBLISH_SUCCESS`. Its consumers schedule metric pulls (Flow N) and ⟨NOTIFY⟩ the creator.
6. **UI result** On `PUBLISH_STARTED` the card pulses blue ("Publishing"), with progress frames such as "Instagram is processing your video…". It then turns green, with the permalink.

### M3. Failure handling

`adapter.map_error()` assigns a category:
- **`validation` / `permanent`** (policy rejection, unsupported media) → `failed` + `PUBLISH_FAILED` with reason; no retry.
- **`auth`** (401, Meta code 190) → `adapter.refresh()` once and requeue immediately; if refresh fails → `social_accounts.status = expired` (or `revoked` + `SOCIAL_ACCOUNT_REVOKED`), post `failed`, the account's other `scheduled` posts paused.
- **`rate_limited`** (429, Meta codes 4/17/32/613) → `next_attempt_at` from `Retry-After` or the platform window; back to `queued`; `dispatch_retries()` re-dispatches.
- **`transient`** (5xx, timeouts, DNS) → backoff 1 m, 5 m, 15 m, 30 m, 60 m (jittered); after `max_attempts` (5) → `failed` + `PUBLISH_DEAD_LETTERED`.
- **`ambiguous`** (timeout/reset **after** the request was sent) → `publish_attempts.status = ambiguous` → reconcile (M4) before any retry.

Each failed attempt emits `PUBLISH_FAILED` `{category, message, next_attempt_at}` ("Retrying at 14:05, attempt 2/5"); users are notified only for permanent failures or the last attempt. Dead-lettered posts appear under Publishing ▸ Failed (reason, attempts, Retry / Edit / Cancel) and `GET /api/v1/admin/jobs` `[manage]`, with an urgent ⟨NOTIFY⟩.

### M4. Reconcile

`PublishingService.reconcile()`, run by `jobs.publishing.reconcile`:
1. If an intermediate id exists, check it with `adapter.get_status(attempt)`. For example, an Instagram container reporting `PUBLISHED` means the post went out.
2. Otherwise, call `adapter.find_recent_posts(since = started_at − 5 min)` and match on `request_fingerprint`: normalized text, media hash, account and time window.

Outcomes:
- **Match** → write `published_posts`; `attempt.status = reconciled`; the post becomes `published`; emit `PUBLISH_SUCCESS`.
- **No match, and the platform can list its own posts** → safe to retry.
- **No match, and the platform can't list them** (LinkedIn member profiles) → `failed` with "ambiguous result; verify manually", plus a notification.
  - **UI result** "We can't confirm whether this was posted. Check your profile, then choose *Mark as published* or *Retry*."
  - *Mark as published* sends `PATCH /api/v1/scheduling/posts/{id}` with the permalink, which is verified via `adapter.get_post()`.

An ambiguous attempt is never retried blindly.

**Stale leases.** `expire_leases()` finds rows that have sat in `publishing` for more than 15 min with no attempt heartbeat (a worker crash). It reconciles them before returning them to `queued`.

### M5. Manual recovery

`POST /api/v1/publishing/attempts/{id}/retry` `[schedule]`:
- If the last attempt was `ambiguous`, the post is reconciled first.
- Otherwise it moves `failed → queued` and is dispatched immediately with a fresh pre-flight. `attempt_count` is kept.

To change the content itself: edit it, get it re-approved (K), then reschedule (L).

**Failure branches (pre-flight)**
- **Version no longer approved** → `queued → paused` (`content_changed`) + notification. This does not count as an attempt.
- **Account expired or revoked** → `paused` (`account_unavailable`) → reconnect.
- **Possible duplicate** → `paused` → "Possible duplicate — publish anyway?"
- **No public media URL** → `failed` (`validation`) → "Configure `PUBLIC_MEDIA_BASE_URL`."
- **Cancel while `publishing`** → 409.

**Audit & transparency.**
- ⟨AUDIT⟩ logs:
  - `publish.attempt`, once per attempt (actor `system:jobs.publishing.publish_post`; redacted platform response; category; latency);
  - `publish.reconcile`, with the verdict;
  - `publish.retry_manual`;
  - `publish.mark_published_manual`.
- `GET /api/v1/publishing/attempts/{id}` shows each attempt's timestamps, error category and code, platform message, intermediate ids and reconcile verdict.

---

## N. Collecting analytics

This flow is system-driven. Manual sync needs `[create]`; viewing needs `[view]`.

1. **Schedule the pulls.**
   - **Per-post metrics.** When `PUBLISH_SUCCESS` fires, an EventBus consumer defers `jobs.analytics.sync_post_metrics(published_post_id, stage)` on `analytics`, with `schedule_at` at each stage of the decaying ladder: **+1h, +6h, +24h, +72h, +7d, +30d**. Per-platform overrides, such as doc 13's 14-day and monthly tail, live in the cadence table.
   - **Account metrics.** The scheduler's `dispatch_analytics_cadence()` enqueues `jobs.analytics.sync_account(social_account_id)` daily for D-1. It re-fetches D-3 because platforms revise recent figures (doc 26).
   - **Manual.** `POST /api/v1/analytics/sync` runs the same account job, throttled to once per 15 min per account (the response includes `next_allowed_at`).
   - **Coalescing.** Both jobs use `queueing_lock` per account. A post pull also picks up other posts of the same account that are due within 10 min.
2. **Fetch.**
   - **Event** `ANALYTICS_SYNC_STARTED`.
   - **Service** `AnalyticsSyncService` first acquires the account's rate-limit budget. Analytics is capped at a configurable share of that budget (default 50%), so publishing keeps headroom. If the budget is short, the youngest stages go first and the rest are deferred.
   - **External** `adapter.get_post_metrics()` and `adapter.get_account_metrics()`, batched where the platform allows. Which metrics exist varies by platform, media type and account type (doc 26).
3. **Normalize.** A versioned `MetricNormalizer` per adapter maps platform metrics to canonical keys (`impressions`, `reach`, `views`, `likes`, `comments`, `shares`, `saves`, `clicks`, `video_views`, `avg_watch_time_s`, `followers`, `profile_visits`, …).
   - **Exposed metric:** stored as returned. A 0 is stored only when the platform actually returned 0.
   - **Not exposed, deprecated, or not permitted by the granted scopes:** stored as `null`, with `availability[key]` set to `not_available`, `deprecated` or `not_permitted`. **Never stored as 0.**
   - The raw payload is kept in `raw`.
4. **Store.**
   - **DB** `post_metrics` is append-only: one row per post per `captured_at`, tagged with an `age_bucket`. `account_metrics` is upserted per account per date.
   - **Job** `jobs.analytics.snapshot` recomputes `analytics_snapshots`: rollups by day, brand, platform, pillar, format and campaign. A rate is derived only when both its numerator and denominator exist, and every metric records its `coverage`.
   - **Event** `ANALYTICS_UPDATED` `{account_id, posts_updated, deltas, partial}`.
5. **UI result** The analytics views refresh over SSE (`GET /api/v1/analytics/overview`, `/posts`, `/accounts`, `/breakdown?by=pillar|format|platform|campaign|hour`).
   - Each account shows "Last synced 12 min ago".
   - A missing metric renders as **"n/a"**, with the reason in a tooltip: "Not provided by this platform for this format", or "Grant the insights permission to see reach".
   - Averages exclude nulls and show coverage ("Reach: 18 of 24 posts").
   - Cross-platform totals sum only comparable metrics, and say so.

**Failure branches**
- **Rate limited (429) mid-sync** → results so far are kept → `ANALYTICS_UPDATED` with `partial = true` → the remainder is re-deferred until reset → "Partially synced."
- **Token expired or revoked** → `ANALYTICS_SYNC_FAILED`, plus an account status update (and `SOCIAL_ACCOUNT_REVOKED` if revoked) → stale-data banner with a reconnect prompt.
- **Missing permission** → affected metrics are `not_permitted` → "Grant permission" (re-runs C or D).
- **Post deleted on the platform** (404) → `published_posts.deleted_at` is set and its pulls stop → "Deleted on Instagram" badge.
- **Metric renamed or deprecated** → the normalizer mapping version is bumped. History is not rewritten; charts mark the change.
- **Botwok was offline** → on restart, overdue pulls run once, so missed stages collapse into the latest one.

**Audit & transparency.**
- ⟨AUDIT⟩ logs every sync as `analytics.sync` (system actor), with call counts and rate-limit headroom, and logs manual sync requests.
- The account drawer shows the last and next sync and any recent errors.
- Each metric tooltip shows the source platform field and `captured_at`.

---

## O. AI performance analysis

1. **Triggers** (doc 13). Analysis starts in one of three ways:
   - **Manual:** "Analyze" → `POST /api/v1/insights/analyze` `{brand_id, period, compare_to, focus?}` `[create]`, or the Command Center intent `performance.analyze`.
   - **Daily:** after the syncs complete, if at least 8 posts in the period have 72 h or more of metrics.
   - **Weekly:** runs regardless of volume. With too few posts, insights are labeled "early signal".
2. **Service** `InsightService.analyze()` → `AIService.create_run(lead_agent="performance_analyst")` (⟨AI-RUN⟩).
3. **Job** `performance_analyst` (powerful tier) uses deterministic tools only: `analytics.query_metrics`, `analytics.compare_periods`, `analytics.breakdown`, `analytics.top_posts`, `analytics.significance` (bootstrap CI or Mann-Whitney, with effect size and n), `content.get` and `memory.search`.
   - **The model never computes numbers.** Every number must reference a tool result (`evidence: [{tool_call_id, path}]`).
   - `EvidenceValidator` rejects mismatches. One repair attempt is allowed; if it still fails, the insight is dropped.
4. **DB**
   - `insights`: kind (`trend` / `anomaly` / `driver` / `benchmark`), narrative, evidence refs, confidence, sample sizes, and a `directional` flag when not significant.
   - `recommendations`: `insight_id`, `action_type`, payload, expected impact range, rationale, `status = open`. Action types: `generate_ideas`, `adjust_pillar_mix`, `change_posting_times`, `test_format`, `update_strategy`, `reuse_top_post`.

   **Event** `AI_ANALYSIS_COMPLETED`, plus one `RECOMMENDATION_CREATED` per recommendation. ⟨NOTIFY⟩ sends a digest, which also feeds the Dashboard's "What to do next" card.
5. **UI result** Each insight is a card. Its chart is drawn from the evidence data, not from the model's text. "How we know" shows the tool calls, n and the confidence interval. Each recommendation can be accepted, dismissed (with a reason) or snoozed.
6. **Accept.** `PATCH /api/v1/insights/recommendations/{id}` `{status: "accepted"}` → `InsightService.apply()`, which depends on the type:
   - **`generate_ideas`** `[create]` → starts Flow G, seeded with the recommendation's insight ids.
   - **`test_format`** `[create]` → creates a `campaigns` row (e.g. "Format test: carousel vs single image") and seeds ideas for it.
   - **`adjust_pillar_mix`, `change_posting_times`, `update_strategy`** `[manage]` → the `strategy` agent proposes the updated mix or plan as a diff. Applying it calls `PUT /api/v1/brands/{brandId}/settings` and updates the pillars, creating a new strategy version. If an editor accepts, the acceptance is recorded and admins are notified.

   The recommendation then moves `open → accepted`, and to `done` once its linked artifacts exist.
7. **Memory.**
   - Insights above the confidence threshold are written with `MemoryService.write(kind=performance, statement, evidence_refs, confidence, valid_until=+90d)`.
   - Accepts and dismissals are written as feedback memory. The analyst then won't repeat a dismissed recommendation for 30 days, and `ideation` and `writer` can recall the validated learnings.
   - A memory contradicted by newer evidence is superseded.

**Failure branches**
- **Low metric coverage** → insights are limited to the available metrics, and each card states its coverage.
- **Every insight fails validation** → the run is `completed` with 0 insights and a warning → "Retry".
- **Recommendation is based on stale data** → "Based on data through Oct 1; re-analyze?"
- **Other failures** → ⟨AI-FAIL⟩.

**Audit & transparency.**
- ⟨AUDIT⟩ logs `insight.analyze` (with the trigger), `recommendation.accept` and `recommendation.dismiss` (with the reason), and the diff of any settings applied.
- Each memory keeps its source `ai_run_id`. Settings ▸ AI ▸ Memory lets `[manage]` view, correct or delete memories.

---

## P. Creating an automation

Building automations requires `[manage]` ("Edit automations"). Viewing them requires `[view]`.

1. **UI** Automations → "New automation" opens the React Flow canvas, either blank or from a template (e.g. "Weekly competitor monitoring + report"). The palette and each node's config panel come from `GET /api/v1/automations/node-types` (doc 14):
   - **Triggers:** `trigger.cron`, `trigger.event`, `trigger.webhook`, `trigger.manual`.
   - **Steps:** `condition`, `ai_agent`, `research`, `generate` (ideas | post | variants | image | report), `transform`, `approve`, `schedule`, `publish`, `wait`, `webhook`, `notification`, `analytics`, and `action` (e.g. `competitors.sync`, `report.generate`).

   Every node type declares a side-effect class: `EXTERNAL_READ`, `WRITE_INTERNAL`, `SPEND`, `APPROVAL` or `EXTERNAL_WRITE`.

   The `publish`, `schedule` and `webhook` nodes are disabled until an admin turns on "autonomous actions" for the workflow. **In V1, the AI-content approval policy (K) still applies even then.** A `publish` node accepts only variants already approved.
2. **Save.**
   - **API** `POST /api/v1/automations`, then `PUT /api/v1/automations/{id}` `{nodes[], edges[], settings}` `[manage]`. `settings` holds `timeout`, `max_cost_usd`, `on_error: stop|continue|notify` and the timezone.
   - **Service** `AutomationEngine.save_workflow()` validates the graph and bumps `version`.
   - **DB** `automation_workflows` (`status = draft`, `version`, `autonomous_actions_enabled`), `workflow_nodes` (`key`, type, config, position), `workflow_edges` (`from_node_key` → `to_node_key`, `branch` ∈ `true|false|approved|rejected|error`).
   - Runs pin `workflow_version`, so editing never changes a run already in flight.
3. **Validation.** Errors block activation. The checks:
   - exactly one trigger, and every node reachable from it;
   - the graph is acyclic, except `wait` loops bounded by `max_iterations`;
   - every config is valid against its node schema;
   - referenced entities (competitors, `active` accounts, enabled agents) exist;
   - cron fires no more often than every 15 min;
   - event triggers use catalog events and are not self-recursive;
   - every content-producing path into `schedule` or `publish` passes through `approve`;
   - the estimated cost per run is within `max_cost_usd`.

   **UI result** Invalid nodes are outlined in red. The header shows the estimated cost per run and per month.
4. **Enable.** `POST /api/v1/automations/{id}/enable` `[manage]` re-validates, sets `status = active`, and registers the trigger:
   - **cron:** the scheduler's `dispatch_automation_cron()` fires it when due.
   - **event:** the AutomationEngine's EventBus consumer matches on event name and filter (e.g. `TREND_DETECTED` with `min_score ≥ 80`), deduplicating by `event_id`.
   - **webhook:** a key scoped to `automations:run:{workflow_id}` is issued (shown once, listed under `GET /api/v1/settings/api-keys`, revocable with `DELETE …/api-keys/{id}`), along with the trigger's signing secret. Callers send `POST /api/v1/automations/{id}/run` with a timestamped `X-Botwok-Signature` and a 5-min replay window; the body is validated against the trigger's schema.

   There is no catalog event for enabling, so this is ⟨AUDIT⟩ only. `POST /api/v1/automations/{id}/disable` sets `status = paused`.
5. **Test run.** `POST /api/v1/automations/{id}/run` `{dry_run: true, sample_payload}`.
   - **DB** `automation_runs`. **Event** `AUTOMATION_TRIGGERED`. **Job** `jobs.automation.execute`.
   - AI nodes run for real, after the user confirms the estimate. Side-effecting nodes are simulated.
   - **UI result** Nodes light up as `AUTOMATION_STEP_COMPLETED` arrives. Clicking a node shows its input and output, logs, cost and links to the AI runs it started.

**Failure branches**
- **Activating with validation errors** → 422, with errors listed per node.
- **Event flood** → one active run per workflow by default (`queueing_lock = automation:{workflow_id}`), plus a per-workflow cap on runs per hour. Skipped triggers are recorded as `cancelled` runs.
- **A referenced entity is deleted later** → the workflow is set to `paused` at its next dispatch → ⟨NOTIFY⟩ admins, naming the node.
- **Bad webhook signature, or a replayed request** → 401, audited, no run.

**Audit & transparency.**
- ⟨AUDIT⟩ logs `automation.create` and `automation.update` (with a version diff), `automation.enable`, `automation.disable` and `automation.autonomous_actions_enabled` (with the stated reason). Dry runs are flagged.
- The workflow page has Versions and Runs tabs (`GET /api/v1/automations/{id}/runs`).

---

## Q. Running automated competitor monitoring

This flow runs the "Weekly competitor monitoring + report" template:

`trigger.cron` (Mon 07:00, brand tz) → `action` `competitors.sync` → `research` (last 7 days, one branch per competitor) → `ai_agent` (`trend` scan) → `generate` (kind `report`) → `condition` (any high-significance change?) → optional `approve` → `notification`.

1. **Trigger.** The scheduler's `dispatch_automation_cron()` → `AutomationEngine.start(workflow, payload)`.
   - **DB** `automation_runs`: `workflow_version`, `trigger_type = cron`, `trigger_payload`, `status = running`, `context = {trigger, brand, workspace}`.
   - **Event** `AUTOMATION_TRIGGERED`.
   - **Job** `jobs.automation.execute(run_id)` (`automation`).
   - If a run is still active, the one-active-run default records the new trigger as a `cancelled` run.
   - If cron ticks were missed while Botwok was offline, the scheduler fires once on restart and records the missed count.
2. **Engine loop.** The engine repeatedly picks the next ready node (edges satisfied, branch matched), writes `automation_run_steps` (`running`, `input`) and calls `registry[node.type].run()` with the config rendered against the run context. Long work is handed off, and the run resumes when it finishes:
   - AI nodes call `AIService.create_run(mode=automation)`. The job yields, and an `AI_RUN_COMPLETED` consumer resumes it.
   - `approve` writes `approvals` and sets the run to `awaiting_approval`. `ApprovalService`'s hook resumes it.
   - `wait` sets `waiting_until`, and the scheduler resumes it.

   Each completed node writes `context.steps[key]` and emits `AUTOMATION_STEP_COMPLETED`. The nodes run as follows:
   - **`competitors.sync`**: `CompetitorService.sync_all(brand)` → `jobs.competitors.sync_profile` for each `official_api` and `public_web` profile. It waits up to 30 min for `COMPETITOR_SNAPSHOT_TAKEN`. Output: `{synced, failed, not_collected}`.
   - **`research`**: `ResearchService.run()` → `research_runs` + `jobs.research.run`. Completes on `RESEARCH_COMPLETED` or `RESEARCH_FAILED`.
   - **`ai_agent` (`trend`)**: writes `trends` and `trend_signals`, emitting `TREND_DETECTED` and `TREND_UPDATED`.
   - **`generate` (report)**: `ReportService.generate(kind="competitor_weekly")`, run by the `report` agent. A `competitor_intel` task computes week-over-week deltas from `competitor_snapshots`. **DB** `reports`, `competitor_reports`. **Event** `REPORT_GENERATED`, `COMPETITOR_UPDATED`.
   - **`condition`**: evaluates e.g. `steps.report.highlights.max_significance >= "high"`. The expression grammar is sandboxed (doc 14.5); Python `eval` is never used.
   - **`approve`** (optional): a `pending` approval goes to the inbox (K), emitting `APPROVAL_REQUESTED`. Approval follows the `approved` edge. Rejection, or the `timeout_hours` expiring, follows `rejected`, which by default ends the run as "not distributed".
   - **`notification`**: `NotificationService.notify(template="competitor_weekly", report_id)` → `notifications` (`NOTIFICATION_CREATED`) → `jobs.notifications.deliver` to email, Slack and HMAC-signed `webhooks`.
3. **Completion.** When no ready nodes remain: **DB** `automation_runs → succeeded`, with `cost_usd` and `finished_at`. **Event** `AUTOMATION_COMPLETED`.
4. **UI result** Monday morning: an in-app notification and email, "Weekly competitor report: 3 notable changes", linking to `/w/[ws]/reports/{id}`. The report holds snapshot deltas, notable competitor posts (official or user-provided data only), cited research highlights, emerging trends, "Opportunities" with "Generate ideas" buttons (G), and a **Data coverage** section listing what was not collected and why.

   `GET /api/v1/automations/runs/{runId}` shows the graph with each step's status, duration and cost, linked to the underlying AI and research runs.

**Failure branches**
- **A node fails.** `settings.on_error` decides:
  - `stop`: the run fails → `AUTOMATION_FAILED` → ⟨NOTIFY⟩ owners and admins with the node and the error.
  - `continue`: the run follows the node's `error` edge if it has one. Per-competitor branches default to this, so the report's Data coverage section names the gap.
  - `notify`: the admins are alerted and the run carries on.
- **Budget exhausted.** `BudgetGuard` denies the AI node → `BUDGET_EXCEEDED` → that step fails → handled per `on_error`. At 80%, `BUDGET_THRESHOLD_REACHED` is shown on the run.
- **Manual cancel.** `POST /api/v1/automations/runs/{runId}/cancel` `[manage]` → `cancelled`. Child AI runs are cancelled too.
- **Worker restart.** All state lives in `automation_runs` and `automation_run_steps`. Executors are idempotent per `(run_id, node_key)`: a `generate` node that is re-run reuses the ids it already produced.
- **Workflow edited mid-run.** The run continues on its pinned version.

**Audit & transparency.**
- Run lifecycle entries use the actor `system:automation:{workflow_id}`.
- `automation_run_steps` stores input, output, `attempts` and `ai_run_id`.
- The report footer names the automation, its version and the run.
- Automations ▸ Runs shows the cost of each run.
- Any content an automation creates is labeled "Created by automation <name>" and always goes through K.

---

## Appendix A — Scheduler duties and jobs

**Scheduler** (one leader, a 5-second loop; doc 12):
- `dispatch_due_posts`
- `dispatch_retries`
- `materialize_recurring`
- `dispatch_analytics_cadence`
- `dispatch_automation_cron`
- `expire_approvals`
- `expire_leases`
- daily enqueues of the token monitor and competitor syncs

**Jobs, by queue:**

| Queue | Jobs (flows that use them) |
|---|---|
| `ai` | `jobs.ai.run` (B, F–J, O, Q) |
| `research` | `jobs.research.run` (B, F, Q), `jobs.competitors.sync_profile` (E, F, Q) |
| `media` | `jobs.media.process` (B, I), `jobs.media.transform` (I, J), `jobs.reports.render` (F, Q) |
| `publishing` | `jobs.publishing.publish_post`, `jobs.publishing.reconcile` (M) |
| `analytics` | `jobs.analytics.sync_post_metrics`, `jobs.analytics.sync_account`, `jobs.analytics.snapshot` (N) |
| `automation` | `jobs.automation.execute` (P, Q) |
| `notifications` | `jobs.notifications.deliver` (all flows) |
| `maintenance` | `jobs.social.probe_capabilities`, `jobs.social.check_token_expiry` (C, D) |

## Appendix B — Catalog and cross-doc notes

**Routes added to doc 00 §14 during review.** (1) `POST /api/v1/social/connect/{platform}/select` — finalizes OAuth after the account picker (Meta Pages/IG accounts, LinkedIn orgs). (2) `POST /api/v1/auth/verify-email` — optional verification once SMTP is configured. Both are now canonical.

**Existing routes used instead of new ones.** "Request changes" → `POST /api/v1/approvals/{id}/reject` with `resolution: "changes_requested"`; Command Center messages → `POST /api/v1/ai/runs` with `conversation_id`; webhook triggers → `POST /api/v1/automations/{id}/run` with a scoped API key and signature; "Mark as published" → `PATCH /api/v1/scheduling/posts/{id}` with a server-verified permalink.

**State changes without a catalog event** (audit + notification only): user/workspace creation, brand edits, idea creation, automation enable/disable, `scheduled_posts → paused`, `social_accounts → expired`. Add events to doc 00 §8 if live updates are needed.

**Cross-doc note.** Doc 14 allows a workflow to relax the AI-approval policy if a reason is recorded. This document follows the V1 rule that the policy is never relaxed. Doc 14 should mark per-workflow relaxation as post-V1.

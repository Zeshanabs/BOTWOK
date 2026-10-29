# 00 — Canonical Vocabulary (the "spine")

Every other document in `docs/architecture/` uses the names below exactly. If a name here and a name elsewhere disagree, this file wins.

> **Product name assumption:** the working directory is `botwok`, so the system is called **Botwok** throughout. Rename freely; nothing depends on it.

---

## 1. Platform codes

| Code | Platform | Account object we connect |
|---|---|---|
| `facebook` | Facebook Page (Meta Graph API) | Page |
| `instagram` | Instagram Professional (Business/Creator) | IG professional account |
| `threads` | Threads | Threads profile |
| `linkedin` | LinkedIn | Member profile **or** Organization page |
| `x` | X (Twitter) | User account |
| `tiktok` | TikTok | Creator/Business account |
| `youtube` | YouTube | Channel |
| `pinterest` | Pinterest | Business account |
| `gbp` | Google Business Profile | Location |

`platform` is a Postgres enum `platform_t` with exactly these values.

## 2. Content formats

Enum `content_format_t`: `text`, `image`, `carousel`, `video`, `short_video`, `story`, `article`, `poll`, `document`, `link`.

Enum `content_type_t` (editorial intent): `educational`, `authority`, `promotional`, `engagement`, `storytelling`, `industry_news`, `case_study`, `behind_the_scenes`, `ugc`, `thought_leadership`, `announcement`.

## 3. Lifecycle statuses

**Editorial lifecycle — `content_items.status` (enum `content_status_t`):**
`idea` → `draft` → `ai_generated` → `needs_review` → `approved` | `rejected` → `archived`

**Publishing lifecycle — `scheduled_posts.status` (enum `schedule_status_t`):**
`scheduled` → `queued` → `publishing` → `published` | `failed` | `cancelled` | `paused`

**Calendar card status** is derived: if a `scheduled_post` exists for the variant, show its status; otherwise show the `content_item` status. This yields exactly the nine user-facing states: Idea, Draft, AI Generated, Needs Review, Approved, Scheduled, Publishing, Published, Failed.

**AI run — `ai_runs.status` (enum `run_status_t`):**
`queued`, `planning`, `running`, `awaiting_approval`, `paused`, `completed`, `failed`, `cancelled`

**AI task (plan step) — `ai_tasks.status`:** `pending`, `ready`, `running`, `awaiting_approval`, `succeeded`, `failed`, `skipped`, `cancelled`

**Approval — `approvals.status`:** `pending`, `approved`, `rejected`, `expired`

**Automation run — `automation_runs.status`:** `running`, `waiting`, `awaiting_approval`, `succeeded`, `failed`, `cancelled`

**Social account — `social_accounts.status`:** `active`, `expired`, `revoked`, `error`, `disconnected`

## 4. Roles (RBAC)

Enum `member_role_t`: `owner`, `admin`, `editor`, `approver`, `viewer`.

| Capability | owner | admin | editor | approver | viewer |
|---|---|---|---|---|---|
| Manage billing/workspace deletion | ✓ | | | | |
| Manage members, roles, API keys | ✓ | ✓ | | | |
| Connect/disconnect social accounts | ✓ | ✓ | | | |
| Edit brand, AI settings, automations | ✓ | ✓ | | | |
| Create/edit content, run AI, research | ✓ | ✓ | ✓ | ✓ | |
| Approve / reject content | ✓ | ✓ | | ✓ | |
| Schedule / publish approved content | ✓ | ✓ | ✓ (approved only) | ✓ | |
| View everything | ✓ | ✓ | ✓ | ✓ | ✓ |

## 5. Agents (final roster)

LLM agents (each has its own prompt, tool allowlist, model tier, and eval suite):

| # | Agent id | Purpose | Model tier |
|---|---|---|---|
| 1 | `research` | Web search, fetch, extract, rank, dedupe, summarize, cite | balanced |
| 2 | `social_listening` | Public social content via permitted APIs; audience signals | balanced |
| 3 | `competitor_intel` | Build and analyze competitor profiles from allowed sources | powerful |
| 4 | `trend` | Detect/label trends across news, social, keyword signals | balanced |
| 5 | `strategy` | Pillars, mix, platform strategy, campaigns, planning recommendations | powerful |
| 6 | `ideation` | High-volume content ideas from strategy+research+performance | cheap |
| 7 | `writer` | Master content + first-platform drafts (hook/body/CTA/hashtags) | powerful |
| 8 | `repurposer` | Master → per-platform variants under platform rules | balanced |
| 9 | `visual` | Visual concepts, image prompts, carousel layouts, video scripts; calls MediaService | balanced |
| 10 | `critic` | Quality, brand, platform, policy scoring; rewrite suggestions (different model than writer) | balanced |
| 11 | `fact_check` | Claim extraction and verification against sources | balanced |
| 12 | `performance_analyst` | Insights + recommendations from normalized metrics | powerful |
| 13 | `report` | Compose reports (competitor, weekly, performance) from stored data | balanced |

Deterministic services that replace agents from the original list (no LLM in the loop):
- `AnalyticsSyncService` (replaces "Analytics Agent")
- `PublishingService` (replaces "Publishing Agent") — the LLM can only *propose* publish/schedule actions; it never calls platform write APIs
- `AutomationEngine` (replaces "Automation Agent") — a workflow runner that invokes agents as nodes

Merged: Web Search → `research`; Audience Research → `social_listening` + `strategy`; Content Idea → `ideation`; SEO/Hashtag → a tool (`hashtags.suggest`, `keywords.lookup`) used by `writer`/`repurposer`; Recommendation → `performance_analyst`.

Orchestration components (not agents): `Orchestrator`, `IntentRouter`, `Planner`, `Executor`, `ApprovalGate`, `MemoryService`, `BudgetGuard`.

## 6. Model tiers

`cheap` (classification, extraction, ideation batches), `balanced` (most agents), `powerful` (planning, strategy, writing, analysis). Each tier maps to a configurable provider/model in `ai_settings`. Defaults are set in `docs/architecture/06-ai-orchestrator.md`.

## 7. Database tables (canonical list)

Identity & tenancy: `users`, `workspaces`, `workspace_members`, `invitations`, `api_keys`, `refresh_sessions`

Brand: `brands`, `brand_settings`, `content_pillars`, `brand_assets`

Social: `social_accounts`, `oauth_tokens`, `oauth_states`

Competitors: `competitors`, `competitor_profiles`, `competitor_posts`, `competitor_snapshots`, `competitor_reports`

Research: `research_runs`, `research_sources`, `research_run_sources`, `research_documents`, `research_chunks`, `rss_feeds`, `keywords`

Trends: `trends`, `trend_signals`

Content: `campaigns`, `content_ideas`, `content_items`, `content_variants`, `content_versions`, `content_sources`, `media_assets`, `content_assets`, `hashtags`

Scheduling & publishing: `scheduled_posts`, `publish_attempts`, `published_posts`, `recurring_schedules`

Analytics: `post_metrics`, `account_metrics`, `analytics_snapshots`, `insights`, `recommendations`

AI: `ai_agents`, `ai_conversations`, `ai_messages`, `ai_runs`, `ai_tasks`, `ai_tool_calls`, `ai_calls`, `ai_settings`, `provider_secrets`, `memories`, `prompt_templates`

Automation: `automation_workflows`, `workflow_nodes`, `workflow_edges`, `automation_runs`, `automation_run_steps`

Cross-cutting: `approvals`, `notifications`, `audit_logs`, `events_outbox`, `usage_budgets`, `usage_ledger`, `reports`, `webhooks`

Queue tables are owned by the task-queue library (Procrastinate) in its own schema `procrastinate`.

## 8. Event names

```
CONTENT_CREATED  CONTENT_UPDATED  CONTENT_STATUS_CHANGED  VARIANT_CREATED
APPROVAL_REQUESTED  CONTENT_APPROVED  CONTENT_REJECTED
POST_SCHEDULED  POST_RESCHEDULED  POST_CANCELLED  POST_PAUSED
PUBLISH_STARTED  PUBLISH_SUCCESS  PUBLISH_FAILED  PUBLISH_DEAD_LETTERED
ANALYTICS_SYNC_STARTED  ANALYTICS_UPDATED  ANALYTICS_SYNC_FAILED
RESEARCH_STARTED  RESEARCH_COMPLETED  RESEARCH_FAILED  SOURCE_SAVED
COMPETITOR_ADDED  COMPETITOR_UPDATED  COMPETITOR_SNAPSHOT_TAKEN
TREND_DETECTED  TREND_UPDATED
AI_RUN_STARTED  AI_RUN_STEP_COMPLETED  AI_RUN_AWAITING_APPROVAL  AI_RUN_COMPLETED  AI_RUN_FAILED
AI_ANALYSIS_COMPLETED  RECOMMENDATION_CREATED
SOCIAL_ACCOUNT_CONNECTED  SOCIAL_ACCOUNT_TOKEN_EXPIRING  SOCIAL_ACCOUNT_EXPIRED  SOCIAL_ACCOUNT_REVOKED
AUTOMATION_TRIGGERED  AUTOMATION_STEP_COMPLETED  AUTOMATION_COMPLETED  AUTOMATION_FAILED
MEDIA_GENERATED  MEDIA_PROCESSED
BUDGET_THRESHOLD_REACHED  BUDGET_EXCEEDED
NOTIFICATION_CREATED  REPORT_GENERATED
```

## 9. API route prefixes (`/api/v1`)

`/auth`, `/users`, `/workspaces`, `/brands`, `/social`, `/research`, `/competitors`, `/trends`, `/content`, `/ideas`, `/campaigns`, `/media`, `/calendar`, `/scheduling`, `/publishing`, `/analytics`, `/insights`, `/reports`, `/automations`, `/approvals`, `/notifications`, `/ai`, `/settings`, `/admin`, `/events` (SSE), `/webhooks`

## 10. Frontend navigation

Sidebar (desktop; collapses to icon rail at ≤1280px; bottom tab bar + sheet on mobile):

```
Workspace switcher ▾   Brand switcher ▾
──────────────
Dashboard
Command Center        (AI assistant)
──────────────
Research
Competitors
Trends
Ideas
──────────────
Studio                (Content Studio)
Media Library
Calendar
Approvals
Publishing            (queue / status)
──────────────
Analytics
Reports
Automations
──────────────
Settings ▸ Brand · Social Accounts · AI · Team · System
```

Routes: `/login`, `/signup`, `/onboarding`, `/w/[workspace]/...` (all app routes are workspace-scoped), e.g. `/w/acme/studio/[contentId]`, `/w/acme/competitors/[competitorId]`.

## 11. Design tokens (summary)

Font: Inter (UI), JetBrains Mono (code/IDs). Base size 14px, line-height 1.5. Spacing scale 4px. Radius 8px (cards 12px). Status colors: idea `slate`, draft `gray`, ai_generated `violet`, needs_review `amber`, approved `emerald`, scheduled `sky`, publishing `blue` (pulsing), published `green`, failed `red`, cancelled `zinc`. Severity: info `blue`, warning `amber`, error `red`, success `green`. Dark mode is first-class.

## 12. Naming conventions

- Python: `snake_case` modules, `PascalCase` classes, services end in `Service`, adapters end in `Adapter`, providers end in `Provider`, repositories end in `Repository`.
- DB: `snake_case`, plural table names, `id UUID` primary keys (UUIDv7), `created_at`/`updated_at timestamptz`, every tenant-owned table has `workspace_id`.
- Events: `UPPER_SNAKE`, payload keys `snake_case`, every event carries `event_id`, `workspace_id`, `occurred_at`, `actor`.
- TypeScript: `camelCase` variables, `PascalCase` components/types, one feature folder per domain.
- Tool names (LLM tools): `domain.verb`, e.g. `web.search`, `web.fetch`, `research.save_source`, `content.create_draft`, `media.generate_image`, `publishing.propose_schedule`.

## 13. Application services (backend `app/services/`)

| Service | Responsibility |
|---|---|
| `AuthService` | signup/login, password hashing, JWT issue/rotate, sessions |
| `WorkspaceService` | workspaces, members, invitations, roles |
| `BrandService` | brands, brand_settings, pillars, brand assets; builds the **BrandContext** object every agent receives |
| `SocialAccountService` | OAuth connect flows, account status, token refresh orchestration (uses `TokenVault`) |
| `TokenVault` | encrypt/decrypt `oauth_tokens` (envelope encryption) |
| `ResearchService` | research runs, source pipeline, dedupe, ranking, chunking/embedding |
| `CompetitorService` | competitor CRUD, profile sync, snapshots, comparison, reports |
| `TrendService` | signal ingestion, scoring, trend lifecycle |
| `ContentService` | ideas, items, variants, versions, sources; status transitions |
| `MediaService` | uploads, processing (FFmpeg/Pillow), generation via providers, platform transforms |
| `SchedulingService` | scheduled_posts, recurring schedules, best-time, due-job dispatch |
| `PublishingService` | adapter registry, publish attempts, idempotency, reconciliation |
| `AnalyticsSyncService` | pulls metrics per platform, normalizes, snapshots |
| `InsightService` | runs `performance_analyst`, stores insights/recommendations |
| `AutomationEngine` | workflow definitions, triggers, run state machine, node executors |
| `ApprovalService` | approval requests, decisions, expiry, resume hooks |
| `NotificationService` | in-app, email, webhook, Slack channels |
| `AuditService` | immutable audit log writes |
| `EventBus` | outbox write + Redis publish + consumer dispatch |
| `AIService` | entry point for runs and chat; wraps `Orchestrator` |
| `BudgetGuard` | token/cost budgets, per-workspace limits, model routing policy |
| `ReportService` | report generation and rendering (markdown → HTML/PDF/email) |
| `MemoryService` | read/write of the 8 memory types across Postgres/pgvector/Redis/MinIO |

## 14. API route catalog (method + path only; bodies in `17-api-architecture.md`)

```
AUTH
POST   /api/v1/auth/signup                 POST /api/v1/auth/login        POST /api/v1/auth/logout
POST   /api/v1/auth/refresh                GET  /api/v1/auth/me           POST /api/v1/auth/password/reset
POST   /api/v1/auth/verify-email           (optional, when SMTP is configured)
WORKSPACES
GET/POST /api/v1/workspaces                GET/PATCH/DELETE /api/v1/workspaces/{ws}
GET/POST /api/v1/workspaces/{ws}/members   PATCH/DELETE /api/v1/workspaces/{ws}/members/{userId}
POST   /api/v1/workspaces/{ws}/invitations POST /api/v1/invitations/{token}/accept
BRANDS
GET/POST /api/v1/brands                    GET/PATCH/DELETE /api/v1/brands/{brandId}
GET/PUT  /api/v1/brands/{brandId}/settings GET/POST /api/v1/brands/{brandId}/pillars
POST   /api/v1/brands/{brandId}/assets     POST /api/v1/brands/{brandId}/import-from-website
SOCIAL
GET    /api/v1/social/accounts             GET /api/v1/social/connect/{platform}   (returns auth URL)
GET    /api/v1/social/callback/{platform}  POST /api/v1/social/connect/{platform}/select  (pick account after callback: {selection_token, external_id})
DELETE /api/v1/social/accounts/{id}
POST   /api/v1/social/accounts/{id}/refresh  POST /api/v1/social/accounts/{id}/test
RESEARCH
GET/POST /api/v1/research/runs             GET /api/v1/research/runs/{runId}
GET    /api/v1/research/sources            GET /api/v1/research/sources/{id}
POST   /api/v1/research/sources/{id}/save  GET/POST /api/v1/research/feeds
GET/POST /api/v1/research/keywords
COMPETITORS
GET/POST /api/v1/competitors               GET/PATCH/DELETE /api/v1/competitors/{id}
POST   /api/v1/competitors/{id}/sync       GET /api/v1/competitors/{id}/posts
GET    /api/v1/competitors/{id}/snapshots  GET /api/v1/competitors/compare?ids=
POST   /api/v1/competitors/{id}/reports    GET /api/v1/competitors/{id}/reports
TRENDS
GET    /api/v1/trends                       GET /api/v1/trends/{id}   POST /api/v1/trends/scan
IDEAS
GET/POST /api/v1/ideas                     PATCH/DELETE /api/v1/ideas/{id}
POST   /api/v1/ideas/generate              POST /api/v1/ideas/{id}/promote   (→ content_item)
CONTENT
GET/POST /api/v1/content                   GET/PATCH/DELETE /api/v1/content/{id}
POST   /api/v1/content/{id}/generate       POST /api/v1/content/{id}/repurpose
POST   /api/v1/content/{id}/critique       POST /api/v1/content/{id}/fact-check
GET/POST /api/v1/content/{id}/variants     PATCH /api/v1/content/{id}/variants/{variantId}
GET    /api/v1/content/{id}/versions       POST /api/v1/content/{id}/versions/{v}/restore
POST   /api/v1/content/{id}/transition     (status change with guard)
POST   /api/v1/content/{id}/request-approval
GET/POST /api/v1/campaigns                 GET/PATCH/DELETE /api/v1/campaigns/{id}
MEDIA
GET/POST /api/v1/media                     GET/DELETE /api/v1/media/{id}
POST   /api/v1/media/upload-url            POST /api/v1/media/generate
POST   /api/v1/media/{id}/transform        POST /api/v1/media/{id}/remove-background
CALENDAR & SCHEDULING
GET    /api/v1/calendar?from=&to=&view=    (aggregated cards)
GET/POST /api/v1/scheduling/posts          GET/PATCH/DELETE /api/v1/scheduling/posts/{id}
POST   /api/v1/scheduling/posts/{id}/pause  POST /api/v1/scheduling/posts/{id}/resume
POST   /api/v1/scheduling/posts/{id}/cancel POST /api/v1/scheduling/best-times
GET/POST /api/v1/scheduling/recurring
PUBLISHING
POST   /api/v1/publishing/publish-now      GET /api/v1/publishing/queue
GET    /api/v1/publishing/attempts/{id}    POST /api/v1/publishing/attempts/{id}/retry
GET    /api/v1/publishing/published        DELETE /api/v1/publishing/published/{id}  (platform delete)
ANALYTICS
POST   /api/v1/analytics/sync              GET /api/v1/analytics/overview
GET    /api/v1/analytics/posts             GET /api/v1/analytics/accounts
GET    /api/v1/analytics/breakdown?by=pillar|format|platform|campaign|hour
GET    /api/v1/insights                    POST /api/v1/insights/analyze
GET/PATCH /api/v1/insights/recommendations/{id}
REPORTS
GET/POST /api/v1/reports                   GET /api/v1/reports/{id}   GET /api/v1/reports/{id}/export?format=
AUTOMATIONS
GET/POST /api/v1/automations               GET/PUT/DELETE /api/v1/automations/{id}
POST   /api/v1/automations/{id}/enable     POST /api/v1/automations/{id}/disable
POST   /api/v1/automations/{id}/run        GET /api/v1/automations/{id}/runs
GET    /api/v1/automations/runs/{runId}    POST /api/v1/automations/runs/{runId}/cancel
GET    /api/v1/automations/node-types
APPROVALS
GET    /api/v1/approvals                    GET /api/v1/approvals/{id}
POST   /api/v1/approvals/{id}/approve       POST /api/v1/approvals/{id}/reject
NOTIFICATIONS
GET    /api/v1/notifications                POST /api/v1/notifications/{id}/read   POST /api/v1/notifications/read-all
AI
POST   /api/v1/ai/runs                      GET /api/v1/ai/runs   GET /api/v1/ai/runs/{runId}
POST   /api/v1/ai/runs/{runId}/cancel       POST /api/v1/ai/runs/{runId}/resume
GET    /api/v1/ai/runs/{runId}/steps        GET /api/v1/ai/runs/{runId}/tool-calls
GET/POST /api/v1/ai/conversations           GET /api/v1/ai/conversations/{id}/messages
GET/PUT  /api/v1/ai/settings                GET /api/v1/ai/agents   GET /api/v1/ai/usage
GET/PUT  /api/v1/ai/prompts/{agentId}
SETTINGS / ADMIN / EVENTS
GET/PUT  /api/v1/settings/workspace         GET/PUT /api/v1/settings/budgets
GET/POST /api/v1/settings/api-keys          DELETE /api/v1/settings/api-keys/{id}
POST   /api/v1/settings/export              GET /api/v1/settings/exports/{id}      (workspace export/backup)
GET    /api/v1/workspaces/{ws}/invitations  DELETE /api/v1/workspaces/{ws}/invitations/{id}
GET    /api/v1/brands/{brandId}/context     (BrandContext preview as the AI sees it)
GET    /api/v1/admin/audit-logs             GET /api/v1/admin/events               (outbox/event log)
GET    /api/v1/admin/jobs                   GET /api/v1/admin/jobs/{id}   POST /api/v1/admin/jobs/{id}/retry
GET    /api/v1/admin/health                 GET /api/v1/admin/costs
GET    /api/v1/events/stream                (SSE: run progress, notifications, publish status)
POST   /api/v1/webhooks/{platform}          (inbound platform webhooks, signature-verified)
```

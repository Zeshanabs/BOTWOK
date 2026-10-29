# 30 — MVP, V1, V2, V3, Future, Development Phases & Build Order

## 30.1 Release definitions

| Release | One-line definition | Usable by |
|---|---|---|
| **MVP** (Phases 0–7, ~8–10 weeks solo) | One person, one brand, local Docker: brand profile → research with citations → AI-written posts (LinkedIn, X, Instagram captions) with critic/fact-check → manual approval → Studio editing → **publish to LinkedIn (member) and X** via official APIs → basic published-post list. No scheduler UI beyond "publish now / at time", no analytics, no automations. | the developer |
| **V1** (Phases 8–10, +6–8 weeks) | Full calendar + reliable scheduler + publishing to Instagram/Facebook/Threads/LinkedIn org/X/YouTube; analytics sync + dashboards; AI performance insights; competitor profiles (allowed data) and comparison; media generation (images, carousels); repurposing; approvals inbox; notifications; cost dashboard. Deployable to a VPS for a small team. | small team / agency pilot |
| **V2** (Phases 11–12, +8 weeks) | Automation engine with visual builder and templates; multi-agent planning in the Command Center with approval gates; trend detection; social listening via licensed APIs; TikTok (inbox upload + direct post if audited), Pinterest, GBP; reports with delivery; local AI routing; brand-level permissions; OIDC login; 2FA. | teams; early customers |
| **V3** (Phase 13+, ongoing) | Optimization: best-time learning, strategy auto-tuning from performance, video pipeline (scripted + generated), comment/mention monitoring and reply drafting, campaign planning, A/B variants, multi-workspace admin, native platform scheduling toggles, Temporal-backed workflows if needed. | scale |
| **Future** | Marketplace of workflow templates, collaborative editing (CRDT), mobile app, white-label reports, advanced listening (Reddit/forums with licensed APIs), ads integration (Meta/LinkedIn ads APIs), e-commerce signals (Shopify), fine-tuned brand-voice models. | — |

The MVP deliberately picks **LinkedIn member posting + X** because both work without lengthy app reviews (LinkedIn's `w_member_social` is self-serve; X pay-per-use needs only a developer account and a card), so the full write→approve→publish loop is testable in week 6 with real platforms. Instagram/Facebook require Meta App Review for live mode but work in **development mode for app admins/testers** — enough for MVP dogfooding; V1 includes the App Review submission work.

## 30.2 Phases

Each phase lists: objectives · features · database · backend · frontend · AI · testing · dependencies · expected output. Estimates assume one experienced developer with AI-assisted coding.

### PHASE 0 — Architecture & infrastructure (1 week)
- Objectives: repo, Docker, CI, skeletons, conventions.
- Features: `make up/dev/test`, health endpoint, SSE skeleton, structured logging.
- Database: Postgres+pgvector container, Alembic baseline, enums, `set_updated_at`, RLS helper.
- Backend: FastAPI app factory, config, DB session, error handling, JobQueue port + Procrastinate app, scheduler process skeleton (advisory lock), EventBus + outbox + relay.
- Frontend: Next.js app with shell (sidebar/header), theme, shadcn setup, generated API client pipeline, SSE hook.
- AI: provider ports + `AnthropicProvider` + `OpenAICompatibleProvider` + `FakeProvider`, pricing table, token counting.
- Testing: CI pipeline, testcontainers, first tests.
- Dependencies: none. Output: a booting stack with a health page and a passing CI.

### PHASE 1 — Authentication & workspace (1 week)
- DB: `users, workspaces, workspace_members, invitations, refresh_sessions, api_keys, audit_logs, notifications`.
- Backend: AuthService, WorkspaceService, RBAC deps, CSRF, rate limits, audit middleware, NotificationService (in-app).
- Frontend: login/signup/onboarding step 1, workspace switcher, team page, notifications bell.
- Testing: auth/RBAC/RLS tests. Output: multi-user workspace with roles.

### PHASE 2 — Brand system (1 week)
- DB: `brands, brand_settings, content_pillars, brand_assets, media_assets (minimal), provider_secrets, ai_settings`.
- Backend: BrandService + BrandContext builder (+cache), MediaService ingest (uploads to MinIO, validation), AI settings with encrypted provider keys.
- Frontend: Brand Settings (all tabs), onboarding brand step, AI Settings (providers/routing/budgets).
- AI: `research.crawl_site` tool + "import from website" (single-agent `tool` mode run using the orchestrator skeleton: ledger + SSE).
- Output: a brand the AI can describe back accurately.

### PHASE 3 — Social account connections (1.5 weeks)
- DB: `social_accounts, oauth_tokens, oauth_states`.
- Backend: TokenVault (envelope crypto), SocialAccountService, adapter base, OAuth flows for LinkedIn (member), X, Meta (Facebook Page + Instagram via Facebook Login), YouTube; `probe()`; token monitor job; deauth webhooks (Meta).
- Frontend: Social Accounts page (connect/reconnect/disconnect, capability display, requirements explainers).
- Testing: mocked authorization servers; encryption tests. Dependencies: developer apps registered on each platform; tunnel for HTTPS callbacks.
- Output: connected accounts with live token health.

### PHASE 4 — Research engine (1.5 weeks)
- DB: `research_runs, research_sources, research_run_sources, research_documents, research_chunks, rss_feeds, keywords, memories`.
- Backend: SearchProvider (Tavily/Brave/SearXNG), SafeFetcher, extractors, dedupe, scoring, chunking + embeddings (EmbeddingProvider), injection classifier, ResearchService; jobs `research.run`, `maintenance.poll_rss`.
- AI: `research` agent + tools; orchestrator `tool` mode matured (budgets, citations, cancellation).
- Frontend: Research page (run, results, source drawer, history); Command Center v0 (single-agent runs with step timeline).
- Output: cited research runs in < 2 min with reusable sources.

### PHASE 5 — Competitor intelligence (1.5 weeks)
- DB: `competitors, competitor_profiles, competitor_posts, competitor_snapshots, competitor_reports`.
- Backend: CompetitorService, collectors (website/blog/RSS, IG Business Discovery, YouTube stats, X user timeline, LinkedIn org follower count), `stats.describe`, retention job.
- AI: `competitor_intel` agent (analyze/compare/find_gaps), `report` agent (competitor kinds).
- Frontend: Competitors list, detail (tabs, availability badges), compare view.
- Output: competitor dashboards with honest availability classes and a gap report.

### PHASE 6 — AI content generation (2 weeks)
- DB: `campaigns, content_ideas, content_items, content_variants, content_versions, content_sources, content_assets, hashtags, approvals, prompt_templates, ai_agents`.
- Backend: ContentService (versions, transitions, sources), platform rules engine, validators, ApprovalService, HashtagService.
- AI: `ideation`, `writer`, `repurposer`, `critic`, `fact_check` agents; prompt templates with versioning; evals harness; injection corpus test.
- Frontend: Ideas page, minimal Studio (editor + AI panel + sources + critic), Approvals inbox.
- Output: brand-faithful posts with scores, verdicts, and citations, approved by a human.

### PHASE 7 — Content Studio (1.5 weeks)
- Features: full three-column Studio, platform previews, character budgets, version compare, repurpose modal, media panel (upload + generate image via `visual` agent + ImageProvider), carousel composer, SEO/hashtag panel, approval panel, schedule panel (publish now / at time).
- Backend: MediaService generation + transforms; `publish-now` path using PublishingService + adapters for LinkedIn member and X (MVP publish).
- DB: `scheduled_posts, publish_attempts, published_posts` (introduced here for publish-now; scheduler loop in Phase 8).
- Output: **MVP complete** — write, approve, publish to LinkedIn/X from the Studio.

### PHASE 8 — Calendar & scheduler (1.5 weeks)
- DB: `recurring_schedules`; indexes for due scans.
- Backend: SchedulingService, scheduler loop (due dispatch, retries, late tolerance, leases), best-time stub, validation at schedule time, calendar aggregation endpoint.
- Frontend: Calendar (month/week/day/list/board), drag-and-drop, filters, unscheduled tray, Publishing queue page.
- Testing: scheduler correctness under concurrency; crash recovery. Output: reliable scheduling with visible queue.

### PHASE 9 — Publishing engine (2 weeks)
- Backend: full adapters for Instagram (container flow, carousels, Reels, Stories), Facebook (feed/photos/videos/Reels), Threads, LinkedIn organization (+document/multi-image), X threads + media v2, YouTube uploads (+publishAt option); reconciliation; MediaPublicURLService; dead-letter handling; platform delete; webhooks.
- Frontend: Publishing page completeness (attempts, errors, retry), Studio validation UX per platform.
- Dependencies: Meta App Review submission (permissions: `pages_manage_posts`, `pages_read_engagement`, `instagram_basic`, `instagram_content_publish`, `instagram_manage_insights`, `business_management`), LinkedIn Community Management application (if org posting), Google OAuth verification + YouTube audit (for public uploads).
- Output: exactly-once publishing across six platforms.

### PHASE 10 — Analytics (1.5 weeks)
- DB: `post_metrics, account_metrics, analytics_snapshots, insights, recommendations, usage_budgets, usage_ledger`.
- Backend: AnalyticsSyncService + per-platform normalizers, cadence jobs, snapshots, stats tools, InsightService, cost ledger aggregation.
- AI: `performance_analyst`, `report` (weekly performance).
- Frontend: Analytics (overview, breakdowns, heatmap, top posts), Dashboard KPIs + "what to do next", Reports page, Cost dashboard.
- Output: **V1 complete** — the learning loop closes.

### PHASE 11 — Automation engine (2 weeks)
- DB: `automation_workflows, workflow_nodes, workflow_edges, automation_runs, automation_run_steps, webhooks`.
- Backend: AutomationEngine, node executors, expression sandbox, triggers (cron/event/webhook/manual), dry-run, templates.
- Frontend: Automations list, React Flow builder, run history. Output: "every Monday research → ideas → planner" running unattended.

### PHASE 12 — Multi-agent intelligence (2 weeks)
- AI: IntentRouter, Planner with plan templates, Executor with fan-out/fan-in, ApprovalGate for `propose_*` tools, `social_listening`, `trend`, `strategy` agents, MemoryService full (8 types), conversation memory, reasoning summaries.
- Frontend: Command Center full (plan checklist, sources/reasoning/content/actions panels, run history), AI drawer contextual on every page, Trends page.
- Backend: TrendService, listening collectors (X search, YouTube search, Threads keyword search where approved, IG hashtag search), additional adapters (TikTok, Pinterest, GBP).
- Output: **V2** — conversational multi-step work with transparency and approvals.

### PHASE 13 — Optimization (ongoing)
- Best-time learning from own data, mix auto-adjust, prompt/eval tuning, caching/dedupe tuning, local model routing, performance (indexes, snapshot precompute), VPS hardening (backups, monitoring), accessibility pass, load tests. Output: V3 increments.

## 30.3 Build order (dependency graph)
```
P0 infra → P1 auth/workspace → P2 brand → P3 social connect ─┐
                                   └→ P4 research → P5 competitors ─┤
                                   └→ P6 generation → P7 studio (MVP) → P8 calendar → P9 publishing → P10 analytics (V1)
                                                                                   └→ P11 automation → P12 multi-agent (V2) → P13 (V3)
```
P4 and P6 can be interleaved (research tools are needed by the writer for citations; start P4 first). P3 can slip after P6 for a pure-local demo but must precede P7's publish-now.

## 30.4 Priority system (feature matrix is in doc 02)
P0 = required for MVP · P1 = required for V1 · P2 = V2 · P3 = V3/Future.

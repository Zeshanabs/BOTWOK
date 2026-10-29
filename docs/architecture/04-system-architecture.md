# 04 — System Architecture

## 4.1 Shape of the system

Botwok is a **modular monolith**: one Python codebase, one container image, three process types (`api`, `worker`, `scheduler`), plus a Next.js frontend and three infrastructure services (PostgreSQL+pgvector, Redis, MinIO). Everything else (AI models, search, social platforms) is external and reached through adapters.

```
                                   USER (browser / mobile browser)
                                              │
                                              ▼
┌───────────────────────────────────────────────────────────────────────────────────┐
│ FRONTEND  Next.js (App Router) · TanStack Query · Zustand · shadcn/ui             │
│   /w/{ws}/dashboard · command-center · research · competitors · trends · ideas    │
│   studio · media · calendar · approvals · publishing · analytics · reports        │
│   automations · settings/*                       SSE client ◄─────────────┐       │
└───────────────────────────────┬───────────────────────────────────────────┼───────┘
                                │ same-origin proxy (/api/* → backend)      │
                                ▼                                           │
┌───────────────────────────────────────────────────────────────────────────┼───────┐
│ API GATEWAY (FastAPI app)                                                 │       │
│   middleware: request-id · auth (JWT) · workspace scope · RLS var ·       │       │
│   rate limit · CORS (off, same-origin) · CSRF (double-submit) · audit     │       │
│   routers: /api/v1/* (see 00 §14)                     GET /events/stream ─┘       │
├───────────────────────────────────────────────────────────────────────────────────┤
│ AUTHZ  RBAC (owner/admin/editor/approver/viewer) · workspace isolation · policies │
├───────────────────────────────────────────────────────────────────────────────────┤
│ APPLICATION SERVICES (app/services)                                                │
│  Auth · Workspace · Brand · SocialAccount/TokenVault · Research · Competitor ·     │
│  Trend · Content · Media · Scheduling · Publishing · AnalyticsSync · Insight ·     │
│  AutomationEngine · Approval · Notification · Audit · EventBus · Budget · Report   │
├───────────────────────────────────────────────────────────────────────────────────┤
│ AI ORCHESTRATOR (app/agents/orchestrator)                                          │
│   IntentRouter → Planner → Executor(DAG) → AgentRuntime(loop) → ApprovalGate      │
│   MemoryService · BudgetGuard · CitationTracker · RunLedger                        │
│         ┌───────────────────┬────────────────────┬────────────────────┐           │
│         ▼                   ▼                    ▼                    ▼           │
│   RESEARCH AGENTS     CONTENT AGENTS       ANALYTICS AGENTS      OPS AGENTS        │
│   research            strategy · ideation  performance_analyst   report            │
│   social_listening    writer · repurposer  trend                                   │
│   competitor_intel    visual · critic                                              │
│                       fact_check                                                   │
├───────────────────────────────────────────────────────────────────────────────────┤
│ TOOL LAYER (app/tools)  — typed, permissioned, logged                              │
│  web.search · web.fetch · web.crawl · rss.read · research.save_source ·            │
│  social.search · social.profile · competitors.* · brand.get_context ·              │
│  content.* · media.* · hashtags.suggest · analytics.query · stats.* ·              │
│  publishing.propose_schedule (APPROVAL) · publishing.propose_publish (APPROVAL)    │
├──────────────┬──────────────────┬──────────────────┬──────────────────────────────┤
│ AI PROVIDERS │ SEARCH PROVIDERS │ MEDIA PROVIDERS  │ SOCIAL ADAPTERS              │
│ Anthropic ·  │ Tavily · Brave · │ OpenAI images ·  │ Meta(FB/IG/Threads) ·        │
│ OpenAI-compat│ Exa · SearXNG ·  │ xAI · Google ·   │ LinkedIn · X · TikTok ·      │
│ (OpenAI,xAI, │ xAI Live Search  │ FLUX/local ·     │ YouTube · Pinterest · GBP    │
│ Ollama,vLLM) │                  │ FFmpeg · rembg   │                              │
│ Google       │                  │                  │                              │
└──────┬───────┴────────┬─────────┴────────┬─────────┴───────────────┬──────────────┘
       │                │                  │                         │
       ▼                ▼                  ▼                         ▼
┌──────────────┐ ┌──────────────┐ ┌─────────────────┐ ┌─────────────────────────────┐
│ POSTGRESQL   │ │ REDIS        │ │ MINIO (S3)      │ │ EXTERNAL PLATFORMS          │
│ relational + │ │ cache · rate │ │ media originals │ │ Meta Graph · LinkedIn ·     │
│ pgvector +   │ │ limits ·     │ │ derived renders │ │ X API v2 · TikTok ·         │
│ procrastinate│ │ pub/sub(SSE) │ │ reports · export│ │ YouTube · Pinterest · GBP   │
│ queue schema │ │ locks        │ │                 │ │ + AI/search vendor APIs     │
└──────┬───────┘ └──────┬───────┘ └────────┬────────┘ └─────────────────────────────┘
       │                │                  │
       ▼                ▼                  ▼
┌───────────────────────────────────────────────────────────────────────────────────┐
│ WORKERS (procrastinate)  queues: ai · research · publishing · analytics · media ·  │
│                          automation · notifications · maintenance                 │
│ SCHEDULER (leader)       due scheduled_posts → publishing queue · recurring        │
│                          schedules · analytics sync cadence · automation cron      │
└───────────────────────────────────────────────────────────────────────────────────┘
                                              │
                                              ▼
                    PUBLISHING → SOCIAL PLATFORMS → ANALYTICS SYNC → AI LEARNING
                                              │
                                              └──────────► NEXT CONTENT (ideas, strategy)
```

## 4.2 Process types

| Process | Entry | Scales | Responsibilities |
|---|---|---|---|
| `api` | `uvicorn app.main:app` | horizontally | HTTP + SSE; writes to DB; enqueues jobs; never does long work inline (>2s) |
| `worker` | `procrastinate worker --queues=…` | horizontally per queue | AI runs, research, publishing, analytics, media, automation steps, notifications |
| `scheduler` | `python -m app.workers.scheduler` | 1 active (advisory lock), N standby | polls due work every 5s; materializes cron schedules; enqueues jobs |
| `frontend` | `next start` | horizontally | UI; proxies `/api/*` |

All three backend processes import the same `app` package and share config, models, services, and the event bus. Queue separation lets you dedicate a worker to `publishing` (small, critical, low concurrency) and another to `ai` (large, bursty, higher concurrency) without separate codebases.

## 4.3 Bounded contexts (modules)

Each module owns its tables, services, schemas, and events; cross-module calls go through service interfaces (no reaching into another module's tables).

```
identity     users, workspaces, members, invitations, api_keys, refresh_sessions
brand        brands, brand_settings, content_pillars, brand_assets   → BrandContext
social       social_accounts, oauth_tokens, oauth_states             → adapters
research     research_runs, research_sources, research_documents, research_chunks, rss_feeds, keywords
competitor   competitors, competitor_profiles, competitor_posts, competitor_snapshots, competitor_reports
trend        trends, trend_signals
content      campaigns, content_ideas, content_items, content_variants, content_versions, content_sources, hashtags
media        media_assets, content_assets
scheduling   scheduled_posts, recurring_schedules
publishing   publish_attempts, published_posts
analytics    post_metrics, account_metrics, analytics_snapshots
insights     insights, recommendations
automation   automation_workflows, workflow_nodes, workflow_edges, automation_runs, automation_run_steps
ai           ai_agents, ai_conversations, ai_messages, ai_runs, ai_tasks, ai_tool_calls, ai_calls, ai_settings, memories, prompt_templates
platform     approvals, notifications, audit_logs, events_outbox, usage_budgets, usage_ledger, reports, webhooks
```

Dependency direction (allowed imports): `platform ← identity ← brand ← {social, research, competitor, trend, content, media} ← {scheduling, publishing, analytics} ← insights ← {ai, automation}`. The `ai` module depends on everything through tools; nothing depends on `ai` except `automation` and the API layer.

## 4.4 The five core flows

### 4.4.1 Synchronous request (CRUD)
```
Browser → Next proxy → FastAPI router → dependency: current_user, workspace, role check
→ service method (unit of work: one DB transaction) → repository → Postgres
→ EventBus.emit() writes events_outbox in the same transaction
→ commit → response (Pydantic schema) → TanStack Query cache update
→ outbox relay (worker) publishes to Redis → SSE → other tabs/users
```

### 4.4.2 AI run (asynchronous, streamed)
```
POST /ai/runs {message, brand_id, conversation_id}
→ AIService.create_run(): ai_runs(status=queued) + enqueue jobs.ai.run (queue=ai)
→ 202 {run_id}
→ UI subscribes SSE filter run_id
worker: Orchestrator.run(run_id)
  → IntentRouter (cheap model) → Planner (powerful) → ai_tasks rows
  → Executor runs DAG; each AgentRuntime step emits AI_RUN_STEP_* events
  → tools write domain rows (research_sources, content_items …) under the run's actor
  → tool with side-effect class=APPROVAL → approvals row, run status=awaiting_approval, notify
  → on approve: POST /ai/runs/{id}/resume → re-enqueue → continue
  → completed: ai_runs.result (structured) → AI_RUN_COMPLETED → SSE → UI renders Sources/Reasoning/Content/Actions
```

### 4.4.3 Scheduling → publishing
```
scheduler (every 5s):
  UPDATE scheduled_posts SET status='queued', queued_at=now()
  WHERE id IN (SELECT id FROM scheduled_posts WHERE status='scheduled' AND scheduled_at<=now()
               ORDER BY scheduled_at FOR UPDATE SKIP LOCKED LIMIT 50)
  RETURNING id;  -- same transaction: enqueue jobs.publishing.publish_post(id), queueing_lock=publish:{id}
worker(publishing):
  CAS queued→publishing · insert publish_attempts(idempotency_key) · adapter.publish()
  success → published_posts · status=published · PUBLISH_SUCCESS
  transient failure → retry schedule (backoff) · status=queued (attempt+1)
  ambiguous (timeout after send) → reconcile via adapter.find_recent(idempotency marker) before retry
  permanent / max attempts → status=failed · PUBLISH_DEAD_LETTERED · notification
```

### 4.4.4 Analytics sync
```
scheduler: for each active social_account → enqueue jobs.analytics.sync_account (respecting per-platform cadence)
worker: adapter.get_account_metrics() + for each published_post due for a metric pull → adapter.get_post_metrics()
  → normalize → post_metrics/account_metrics (upsert by (post, captured_at bucket)) → analytics_snapshots → ANALYTICS_UPDATED
```

### 4.4.5 Learning loop
```
ANALYTICS_UPDATED (daily batch) → InsightService → performance_analyst agent (stats tools) → insights + recommendations
→ RECOMMENDATION_CREATED → notification → user accepts → ideation/strategy agents consume performance memory
→ new content_ideas / strategy updates → Studio → … → publishing → analytics → (loop)
```

## 4.5 Deployment topologies

**Local (default):**
```
docker compose up
  frontend:3000  api:8000  worker(x1, all queues)  scheduler  postgres:5432  redis:6379  minio:9000/9001
  optional: ollama (host), searxng:8080, playwright (sidecar)
```

**VPS (later), same images:**
```
Caddy/Traefik (TLS, HTTP/2, SSE-friendly timeouts) → frontend, api
worker-publishing (concurrency 2) · worker-ai (concurrency 4) · worker-general (concurrency 8) · scheduler (x2, lock)
managed Postgres (or container + WAL-G backups) · Redis · S3-compatible storage (replaces MinIO)
secrets via SOPS/age or the host's secret store; Prometheus + Grafana + Loki optional
```

Nothing in application code changes between the two; only env vars (`DATABASE_URL`, `REDIS_URL`, `S3_ENDPOINT`, `BOTWOK_MASTER_KEY`, provider keys, `PUBLIC_BASE_URL` for OAuth callbacks).

## 4.6 Cross-cutting rules

1. **Side effects only in services.** Routers validate and delegate; agents call tools; tools call services. No raw SQL in routers or agents.
2. **One transaction per unit of work.** Domain write + outbox event + job enqueue commit together.
3. **Every tenant row has `workspace_id`**, and RLS is on. Background jobs set `app.workspace_id` from their payload before touching the DB.
4. **External calls are wrapped** in a `ResilientClient` (timeouts, retries with jitter, circuit breaker per host, rate-limit buckets in Redis, structured error mapping).
5. **Untrusted text is tagged** at ingestion (`trust=untrusted`) and carried through to the prompt builder, which isolates it (doc 19).
6. **The LLM never calls a platform write API.** Side-effect tools create approvals or scheduled rows; the deterministic scheduler/publisher performs the write.

# 03 — Recommended Technology Stack & Architectural Decision Records

## 3.1 The stack at a glance

| Layer | Choice | Version target | Why (one line) |
|---|---|---|---|
| Language | Python | 3.12 | User proficiency; best AI/ML tooling; async maturity |
| API framework | FastAPI | 0.115+ | Async, Pydantic-native, OpenAPI for free |
| Validation | Pydantic | v2 | Schemas shared by API, agents (structured outputs), config |
| ORM / migrations | SQLAlchemy 2.0 (async) + Alembic | 2.0 / 1.13 | Mature, explicit, async sessions |
| Database | PostgreSQL + pgvector | 16 / 0.8 | Relational core + vectors + `SKIP LOCKED` queues + JSONB |
| Cache / realtime | Redis | 7 | Cache, rate limiters, pub/sub for SSE, distributed locks |
| Task queue | Procrastinate (Postgres-backed, async) | 3.x | Transactional enqueue, queueing locks, periodic tasks, no extra broker on the publishing path |
| Object storage | MinIO (S3 API) | latest | Local S3; swap to S3/R2 on VPS |
| HTTP client | httpx | 0.27+ | Async, timeouts, SSRF guard hooks |
| Web extraction | trafilatura + selectolax; Playwright optional | — | Best open-source article extraction |
| Media | Pillow, FFmpeg (subprocess), rembg | — | Deterministic transforms; providers for generation |
| AI providers | Own `AIProvider` port; adapters: Anthropic SDK, OpenAI-compatible (OpenAI, xAI, Ollama, vLLM, OpenRouter), Google GenAI | — | Provider independence with two adapters covering ~all models |
| Observability | structlog, OpenTelemetry, Prometheus client | — | Structured logs, traces, metrics |
| Frontend | Next.js (App Router) + React + TypeScript | 15 / 19 / 5.6 | User preference; routing, SSR when useful |
| UI | Tailwind + shadcn/ui + lucide icons | 4 / latest | Composable, owns the code |
| Data fetching | TanStack Query | 5 | Server state, caching, optimistic updates |
| Client state | Zustand | 5 | Small, explicit stores (editor, run stream, UI) |
| Forms | react-hook-form + zod | — | Typed forms mirrored from OpenAPI |
| Charts | Recharts | 2.x | Adequate, simple |
| Editor | Tiptap | 2.x | ProseMirror-based, extensible, markdown round-trip |
| Workflow canvas | React Flow (`@xyflow/react`) | 12 | Node/edge editor for automations |
| Drag & drop | dnd-kit | — | Calendar + kanban |
| API client | openapi-typescript + openapi-fetch | — | Generated types from FastAPI's OpenAPI |
| Tooling (py) | uv, ruff, pyright, pytest, pytest-asyncio, respx, factory-boy | — | Fast, strict |
| Tooling (ts) | pnpm, ESLint, Prettier, Vitest, Playwright | — | Standard |
| Containers | Docker Compose (local), Compose or Nomad/k3s on VPS | — | Same images locally and remotely |

**Non-choices (deliberately avoided for V1):** Kubernetes, Kafka, microservices, GraphQL, a SaaS auth provider, LangChain, a dedicated vector DB, Celery.

---

## 3.2 Architectural Decision Records

Each ADR lists options, the decision, and the consequence. Status is *Accepted* unless noted.

### ADR-001 Backend framework: FastAPI vs Node.js vs Go

- **A. Python/FastAPI.** Async, Pydantic models reused for LLM structured outputs, the richest ecosystem for AI SDKs, extraction (trafilatura), media (Pillow, ffmpeg bindings), embeddings. Weaker: CPU-bound work needs processes; typing is optional.
- **B. Node.js (NestJS/Hono) + TypeScript.** One language across the stack; Vercel AI SDK is good. Weaker: web extraction/media/ML tooling is thinner; the developer is less fluent.
- **C. Go.** Great for workers and reliability; AI/extraction ecosystem immature; slower iteration on prompts.

**Decision: A.** The AI/research/media parts dominate the codebase and are strongest in Python. We keep CPU-heavy media work in workers (separate processes) so the API stays responsive.

### ADR-002 Database: PostgreSQL vs MongoDB vs SQLite

- **A. PostgreSQL 16 + pgvector.** Relational integrity (content ↔ variants ↔ schedules ↔ attempts is deeply relational), JSONB for flexible brand/platform metadata, `SELECT … FOR UPDATE SKIP LOCKED` for a correct scheduler, advisory locks for leader election, pgvector for embeddings, LISTEN/NOTIFY used by Procrastinate.
- **B. MongoDB.** Flexible documents, but we'd re-implement joins, transactions across collections are clunkier, no native vector + queue story in one engine.
- **C. SQLite (local-first purist).** Zero-ops locally, but no `SKIP LOCKED`, weak concurrent writers (API + workers + scheduler), no pgvector; migration to VPS later would be a rewrite.

**Decision: A.** Docker makes Postgres a one-liner locally; it is also the VPS target, so there is no "local vs cloud" divergence.

### ADR-003 Task queue: Celery vs Dramatiq vs RQ vs arq/Taskiq vs Procrastinate

| | Celery | Dramatiq | RQ | arq / Taskiq | Procrastinate |
|---|---|---|---|---|---|
| Broker | Redis/RabbitMQ | Redis/RabbitMQ | Redis | Redis / pluggable | **PostgreSQL** |
| Async-native | No | No | No | Yes | Yes |
| Transactional enqueue with domain writes | No | No | No | No | **Yes** |
| Per-key "only one job for this post" lock | DIY | DIY | DIY | DIY | **`queueing_lock` built-in** |
| Retries/backoff | Yes | Yes (middleware) | Basic | Yes | Yes |
| Periodic tasks | Beat (separate SPOF) | periodiq | rq-scheduler | cron built-in | built-in |
| Job introspection in DB | No | No | No | No | **Yes (SQL)** |
| Maturity/community | Highest | High | High | Medium | Medium |
| Operational weight | Highest | Low | Low | Low | Lowest (no broker) |

**Decision: Procrastinate**, behind a thin `JobQueue` port so it can be swapped. Rationale: the single most important reliability property in this system is "never publish twice, never lose a scheduled post". With a Postgres-backed queue, the row that marks a post `queued` and the job that will publish it are committed in **one transaction**; the `queueing_lock = f"publish:{scheduled_post_id}"` guarantees at most one pending job per post. Throughput requirements are tiny (hundreds of jobs/day for a solo user, low thousands on a VPS), well within Postgres. Redis still exists for cache/rate-limits/pub-sub, just not on the publishing critical path.
**Fallback:** if throughput ever exceeds ~50 jobs/sec, swap the `JobQueue` adapter to Dramatiq+Redis and keep our own `scheduled_posts`/`publish_attempts` ledger (which is the source of truth regardless of broker).

### ADR-004 Vectors: pgvector vs Qdrant vs Weaviate/Chroma

- **A. pgvector (HNSW).** One database, transactional with the rows that own the embeddings (research chunks, content, memories), workspace filtering is a normal `WHERE`. Fine to ~1–5M vectors.
- **B. Qdrant.** Faster at scale, rich filtering, but another service, another failure mode, and data duplication/sync.
- **C. Chroma/Weaviate.** Similar trade-offs to B; Chroma is dev-oriented.

**Decision: A**, behind a `VectorStore` port (`upsert`, `search(filter, k)`, `delete`). A solo workspace will hold tens of thousands of chunks, not millions.

### ADR-005 API style: REST vs GraphQL vs tRPC

**Decision: REST (OpenAPI) + SSE for streaming.** FastAPI generates the OpenAPI spec; we generate a typed TS client from it. GraphQL adds a resolver layer and N+1 risks for no benefit at this UI complexity; tRPC requires a TS backend.

### ADR-006 Frontend: Next.js vs Vite+React vs Remix

**Decision: Next.js 15 App Router**, but used deliberately: all app pages are client-rendered feature modules backed by TanStack Query; Next's role is routing, layouts, static optimization, and a **same-origin proxy** (`rewrites` → FastAPI) so cookies are first-party and CORS is unnecessary. We avoid server actions and avoid duplicating business logic in Next; the FastAPI backend is the only API. If Next ever becomes friction, the feature modules port to Vite in days.

### ADR-007 AI abstraction: own port vs LiteLLM vs LangChain/LangGraph vs PydanticAI

- **A. Own `AIProvider` port + adapters.** We control the message format, tool-call normalization, streaming, token accounting, retries. Two adapters cover almost everything: `AnthropicProvider` (Messages API) and `OpenAICompatibleProvider` (OpenAI, xAI, Ollama, vLLM, OpenRouter, Groq, Mistral). A third, `GoogleProvider`, is added when needed.
- **B. LiteLLM.** Breadth and cost tables out of the box; but a large, fast-moving dependency with its own bugs in tool-calling edge cases and streaming.
- **C. LangChain/LangGraph.** Heavy abstractions, frequent breaking changes, obscures prompts; graph runtime is nice but we need our own run ledger/approvals anyway.
- **D. PydanticAI.** Clean typed agents; still young and opinionated about the loop. Could be used *inside* an adapter later.

**Decision: A.** The orchestrator, agent loop, tool registry, and run ledger are ours (they are the product). Optionally add `LiteLLMProvider` as a fourth adapter for long-tail models. **Why it matters:** cost tracking, approval gates, and injection defenses live in the loop; owning the loop is non-negotiable.

### ADR-008 Local AI vs API AI

**Decision: API-first, local-compatible.** Default model routing uses cloud models. Ollama/vLLM expose OpenAI-compatible endpoints, so local inference is just another `OpenAICompatibleProvider` configuration (`base_url=http://host.docker.internal:11434/v1`). Embeddings and the `cheap` tier are the first realistic candidates for local execution. See doc 21 for hardware guidance.

### ADR-009 Monolith vs microservices

**Decision: Modular monolith**, one Python package, three process types from the same image: `api`, `worker`, `scheduler`. Modules communicate in-process through service interfaces and the event bus; the only network boundaries are Postgres, Redis, MinIO, and external APIs. This is the right shape for one developer and still deploys as separate scalable containers on a VPS. Microservices would multiply deploy units, contracts, and failure modes without a team to own them.

### ADR-010 ORM: SQLAlchemy 2.0 vs SQLModel vs raw asyncpg

**Decision: SQLAlchemy 2.0 async + Alembic.** SQLModel blends Pydantic and SQLA models, which fights us when API schemas diverge from DB rows (they will). Raw asyncpg is fastest but we need migrations and relationships.

### ADR-011 Authentication: own vs SaaS (Clerk/Auth0) vs fastapi-users

**Decision: own, minimal.** Local-first cannot depend on a hosted IdP. Argon2id passwords, short-lived JWT access tokens (15 min) in memory, opaque rotating refresh tokens (30 days) in `httpOnly; Secure; SameSite=Lax` cookies, server-side `refresh_sessions` table for revocation. OIDC login (Google/GitHub) is a V2 add-on.

### ADR-012 Object storage: MinIO vs filesystem vs S3

**Decision: MinIO** with the S3 SDK (`aioboto3`). Same code path locally and on a VPS (S3, R2, Backblaze). A `LocalFSStorage` driver exists only for tests.

### ADR-013 Realtime: SSE vs WebSocket vs polling

**Decision: SSE** (`GET /api/v1/events/stream`) fed by Redis pub/sub. All realtime needs are server→client (run progress, publish status, notifications). WebSocket adds bidirectional complexity we don't need; polling wastes AI-run UX.

### ADR-014 Workflow engine: own vs Temporal vs Prefect/Airflow

**Decision: own Postgres state machine** (`automation_runs` + `automation_run_steps`) executed by Procrastinate jobs, with explicit `waiting`/`awaiting_approval` states and resumable steps. Temporal is the right tool at scale but is a heavy server + SDK for a local-first app; the `WorkflowRunner` port lets us adopt it later.

### ADR-015 Web extraction: trafilatura vs Firecrawl/Jina Reader vs Playwright-everything

**Decision:** `ExtractorProvider` port. Default chain: httpx fetch (SSRF-guarded) → trafilatura (with `favor_recall`) → fallback readability → optional Playwright render for JS-heavy pages (behind a flag, sandboxed container). Hosted extractors (Firecrawl, Jina) are optional adapters for sites that block bots.

### ADR-016 Search providers

**Decision:** `SearchProvider` port with adapters: `TavilyProvider` (default: returns extracted content, good for agents), `BraveProvider` (cheap, broad), `ExaProvider` (semantic/neural, great for "find pages like"), `SearXNGProvider` (self-hosted, zero cost, meta-search; local-first default when no key), `XAISearchProvider` (Grok Live Search for X/news when licensed). Bing Search APIs were retired in 2025 and are not an option.

### ADR-017 Embeddings

**Decision:** `EmbeddingProvider` port; default cloud `text-embedding-3-small` (1536-d) or Voyage; local `nomic-embed-text` via Ollama (768-d). Dimension is stored per model; one `embedding_model` column per vector table prevents mixing spaces.

### ADR-018 Editor, canvas, charts

Tiptap (editor; markdown + JSON storage), React Flow (automation canvas; nodes/edges persist 1:1 to `workflow_nodes`/`workflow_edges`), Recharts (charts), dnd-kit (calendar/board DnD).

### ADR-019 Secrets & token encryption

**Decision:** Application-level envelope encryption for OAuth tokens and provider keys: AES-256-GCM data keys wrapped by a Key-Encryption-Key from `BOTWOK_MASTER_KEY` (env/Docker secret locally; KMS/SOPS on VPS). Ciphertext, nonce, key-version stored in `oauth_tokens`. Rotation = re-wrap data keys.

### ADR-020 Scheduler leadership

**Decision:** The `scheduler` process holds a Postgres advisory lock (`pg_try_advisory_lock(hash('botwok:scheduler'))`). Multiple replicas can run; only the lock holder dispatches. Dispatch itself is idempotent (`SKIP LOCKED` + status CAS), so even a split-brain cannot double-enqueue.

### ADR-021 Multi-tenancy isolation

**Decision:** `workspace_id` column on every tenant table + mandatory repository scoping + Postgres **Row-Level Security** policies enabled from day one (session variable `app.workspace_id` set per request/job). RLS is cheap insurance against a missing `WHERE`.

### ADR-022 Package/tooling

uv (deps + venv), ruff (lint/format), pyright (strict on `app/`), pytest + pytest-asyncio, `testcontainers` for Postgres in integration tests, respx for HTTP mocking, VCR-style cassettes for platform adapters. Frontend: pnpm, ESLint, Prettier, Vitest, Playwright.

---

## 3.3 Ports & adapters (the provider-independence rule)

Every external dependency is reached through a Python `Protocol` in `app/core/ports/` and implemented in `app/integrations/`:

```
AIProvider          complete(), stream(), count_tokens(), supports(tool_use|json|vision)
EmbeddingProvider   embed(texts) -> vectors, dims, model_id
ImageProvider       generate(), edit(), variations()
VideoProvider       generate(), status()
SpeechProvider      tts(), transcribe()
SearchProvider      search(query, kind=web|news|social, recency, domains)
ExtractorProvider   extract(url|html) -> Document
SocialAdapter       (per platform) auth_url(), exchange(), refresh(), publish(), get_post(), delete(), get_metrics(), validate()
StorageProvider     put(), get(), presign(), delete()
JobQueue            enqueue(task, args, lock_key, run_at), cancel(), status()
VectorStore         upsert(), search(), delete()
NotificationChannel send(notification)
```

Selection is configuration (`ai_settings`, env), never `if provider == "openai"` in business code. Adding a provider = one adapter file + one registry entry + its tests.

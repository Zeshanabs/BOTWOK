# 22 — Complete Repository Structure

```
botwok/
├── README.md
├── docker-compose.yml                 # local stack
├── docker-compose.prod.yml            # VPS override
├── .env.example
├── Makefile
├── .github/workflows/ci.yml           # lint, type-check, tests (py + ts), build images
├── docs/
│   ├── architecture/                  # this package (00–33)
│   ├── adr/                           # one file per ADR after they change
│   ├── platforms/                     # per-platform integration notes, verified dates, app-review checklists
│   └── runbooks/                      # ops: restore DB, rotate keys, reconnect accounts, dead-letter handling
├── infrastructure/
│   ├── docker/
│   │   ├── backend.Dockerfile
│   │   ├── frontend.Dockerfile
│   │   ├── entrypoint.sh              # api|worker|scheduler
│   │   ├── minio-init.sh
│   │   └── caddy/Caddyfile            # VPS TLS/proxy
│   ├── compose/profiles/              # local-search, render, monitoring (prometheus, grafana, loki)
│   └── vps/                           # cloud-init, backup scripts (pg_dump + WAL-G), systemd units
├── scripts/
│   ├── seed.py  generate_master_key.py  export_openapi.py  reembed.py  dev_tunnel.sh  create_demo_data.py
├── backend/
│   ├── pyproject.toml  uv.lock  alembic.ini  ruff.toml  pyrightconfig.json
│   ├── migrations/
│   │   ├── env.py
│   │   └── versions/                  # 0001_identity … 00xx_*
│   ├── app/
│   │   ├── main.py                    # FastAPI app factory, middleware, routers
│   │   ├── config.py                  # pydantic-settings
│   │   ├── api/                       # HTTP layer only: routers, dependencies, error handlers, SSE
│   │   │   ├── deps.py                # current_user, current_member, require_role, db session, idempotency
│   │   │   ├── errors.py              # Problem Details mapping
│   │   │   ├── sse.py
│   │   │   └── v1/  auth.py users.py workspaces.py brands.py social.py research.py competitors.py trends.py
│   │   │            ideas.py content.py campaigns.py media.py calendar.py scheduling.py publishing.py analytics.py
│   │   │            insights.py reports.py automations.py approvals.py notifications.py ai.py settings.py admin.py webhooks.py
│   │   ├── core/                      # cross-cutting primitives (no domain logic)
│   │   │   ├── db.py (engine, sessions, RLS var)  security.py (jwt, argon2)  crypto.py (envelope encryption)
│   │   │   ├── ports/                 # Protocols: ai_provider.py embedding_provider.py image_provider.py video_provider.py
│   │   │   │                          #   speech_provider.py search_provider.py extractor_provider.py social_adapter.py
│   │   │   │                          #   storage_provider.py job_queue.py vector_store.py notification_channel.py
│   │   │   ├── resilience.py          # ResilientClient: timeouts, retries, circuit breaker, rate buckets
│   │   │   ├── safe_fetch.py          # SSRF guard
│   │   │   ├── pricing.py  budgets.py  ids.py (uuid7)  time.py  pagination.py  logging.py  telemetry.py  events.py (EventBus)
│   │   ├── models/                    # SQLAlchemy ORM, one module per bounded context (identity.py brand.py social.py …)
│   │   ├── schemas/                   # Pydantic request/response + section models (brand_settings sections, agent outputs)
│   │   ├── repositories/              # query objects per aggregate; all workspace-scoped
│   │   ├── services/                  # application services (doc 00 §13), unit-of-work
│   │   ├── agents/                    # AI layer
│   │   │   ├── orchestrator/  service.py context.py intent_router.py planner.py executor.py runtime.py approval_gate.py
│   │   │   │                  budget_guard.py citations.py ledger.py memory.py
│   │   │   ├── registry.py            # AgentSpec registry (seeded into ai_agents)
│   │   │   ├── base.py                # Agent base: build_messages, parse, untrusted wrapper
│   │   │   ├── research.py social_listening.py competitor_intel.py trend.py strategy.py ideation.py writer.py
│   │   │   │   repurposer.py visual.py critic.py fact_check.py performance_analyst.py report.py
│   │   │   ├── prompts/               # default prompt templates (*.md) per agent/action, versioned
│   │   │   └── schemas/               # output models per agent action
│   │   ├── tools/                     # LLM-callable tools (typed, permissioned)
│   │   │   ├── registry.py decorators.py runner.py
│   │   │   ├── web.py rss.py research.py social.py competitors.py brand.py content.py media.py hashtags.py keywords.py
│   │   │   │   platform_rules.py analytics.py stats.py insights.py publishing.py (propose_* only) memory.py reports.py policy.py claims.py
│   │   ├── integrations/              # adapters implementing ports
│   │   │   ├── ai/  anthropic.py openai_compatible.py google.py litellm.py (optional) fake.py (tests)
│   │   │   ├── embeddings/  openai.py voyage.py ollama.py
│   │   │   ├── media/  openai_images.py xai_images.py google_images.py replicate_fal.py local_diffusion.py
│   │   │   │           runway.py luma.py kling.py veo.py sora.py ffmpeg_template.py elevenlabs.py openai_speech.py whisper_local.py
│   │   │   ├── search/  tavily.py brave.py exa.py searxng.py xai_live.py
│   │   │   ├── extract/  trafilatura.py readability.py pdf.py playwright_render.py firecrawl.py
│   │   │   ├── social/
│   │   │   │   ├── base.py            # shared helpers: TokenSet, PublishRequest, error mapping, rate specs
│   │   │   │   ├── meta/  client.py facebook.py instagram.py threads.py webhooks.py
│   │   │   │   ├── linkedin.py x.py tiktok.py youtube.py pinterest.py gbp.py
│   │   │   │   └── cassettes/         # recorded fixtures for tests (redacted)
│   │   │   ├── storage/  s3.py local_fs.py
│   │   │   ├── queue/  procrastinate_queue.py (JobQueue impl)  dramatiq_queue.py (optional)
│   │   │   ├── notifications/  email.py slack.py webhook.py in_app.py
│   │   │   └── vector/  pgvector.py
│   │   ├── content/                   # domain helpers: platform_rules.py (declarative), validators.py, fingerprint.py, hashtags.py
│   │   ├── media/                     # platform_specs.py, pipelines (image.py video.py carousel.py subtitles.py), templates/
│   │   ├── research/                  # pipeline stages: query_plan.py fetch.py extract.py dedupe.py score.py chunk.py injection.py
│   │   ├── analytics/                 # normalize.py (per-platform mappers), stats.py, snapshots.py
│   │   ├── workflows/                 # AutomationEngine: engine.py nodes/*.py expressions.py validation.py templates/*.json
│   │   ├── workers/                   # job definitions by queue + scheduler
│   │   │   ├── app.py                 # procrastinate app, queues, middleware (RLS var, logging, budgets)
│   │   │   ├── scheduler.py           # leader loop (doc 12)
│   │   │   ├── jobs/  ai.py research.py competitors.py trends.py publishing.py analytics.py media.py automation.py
│   │   │   │          notifications.py maintenance.py (retention, reembed, token monitor, outbox relay)
│   │   ├── events/                    # event names, envelope, consumers registry, outbox relay
│   │   └── utils/                     # text.py urls.py hashing.py jinja_sandbox.py timezones.py
│   └── tests/
│       ├── unit/  services/ agents/ tools/ content/ research/ analytics/ workflows/
│       ├── integration/  db/ api/ queue/ adapters/ (cassettes)
│       ├── agent_evals/  golden/ rubrics/ injection_corpus/
│       └── conftest.py (testcontainers Postgres, FakeProvider, factories)
├── frontend/
│   ├── package.json  pnpm-lock.yaml  next.config.ts (rewrites → api)  tailwind.config.ts  tsconfig.json  playwright.config.ts
│   ├── src/
│   │   ├── app/                       # routes (App Router)
│   │   │   ├── (auth)/login  (auth)/signup  onboarding
│   │   │   └── w/[workspace]/  layout.tsx dashboard command-center research competitors/[id] trends ideas
│   │   │                        studio/[contentId] media calendar approvals publishing analytics reports
│   │   │                        automations/[id] settings/(brand|social|ai|team|system)
│   │   ├── components/                # shared UI: ui/ (shadcn), layout/ (shell, sidebar, header, ai-drawer), data/ (tables, charts), forms/
│   │   ├── features/                  # one folder per domain: api.ts (generated client wrappers), hooks.ts, components/, store.ts, types.ts
│   │   │   ├── auth brands social research competitors trends ideas studio media calendar approvals publishing analytics
│   │   │   │   reports automations ai (command center, run timeline, sources panel) settings
│   │   ├── hooks/                     # cross-feature hooks: useSSE, useWorkspace, useShortcuts, useDebounce
│   │   ├── lib/                       # api client (openapi-fetch), auth, query client, utils, date/tz, platform meta (icons, limits)
│   │   ├── services/                  # non-React: sse client, upload (presigned), analytics formatting
│   │   ├── stores/                    # zustand: ui.ts (sidebar, theme), editor.ts, runStream.ts, calendarFilters.ts
│   │   ├── types/                     # generated openapi types + domain types
│   │   └── utils/                     # formatting, validation (zod schemas mirrored), platform rules (client-side counters)
│   └── tests/  unit/ (vitest)  e2e/ (playwright)
├── workers/                           # (empty by design — workers live in backend/app/workers; kept as a top-level pointer README)
└── tests/                             # cross-cutting: e2e scenarios (docker compose), load tests (k6 scripts)
```

## Folder responsibilities (backend)
- `api/`: routing, auth dependencies, serialization; no business rules.
- `core/`: infrastructure primitives and port definitions; importable by everything; imports nothing from domain.
- `models/`: ORM tables only. `schemas/`: Pydantic contracts (API + agent outputs + JSONB sections).
- `repositories/`: data access, always scoped by workspace; no HTTP or LLM awareness.
- `services/`: use cases, transactions, event emission, authorization checks at object level.
- `agents/`: orchestrator + agent specs/prompts; call tools only. `tools/`: thin, typed wrappers over services with permission metadata.
- `integrations/`: adapters for external systems implementing `core/ports`; no domain logic.
- `content/`, `media/`, `research/`, `analytics/`, `workflows/`: domain algorithms (pure where possible) used by services.
- `workers/`: job definitions (thin: load context, call service), scheduler.
- `events/`: event catalog, outbox relay, consumer registry.
- `utils/`: pure helpers.

## Folder responsibilities (frontend)
- `app/`: routing and layouts only; pages compose feature components.
- `components/`: presentational/shared; no data fetching.
- `features/`: everything domain-specific (API hooks, components, local stores). A feature may import `components`, `lib`, `hooks`, never another feature's internals (only its public `index.ts`).
- `hooks/`: generic hooks. `lib/`: clients and config. `services/`: non-React logic. `stores/`: global client state. `types/`: generated and shared types. `utils/`: pure functions.

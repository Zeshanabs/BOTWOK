# BUILD CONTRACT — how modules are built and fit together

This file is the contract between parallel builders. Read it fully, then read `docs/architecture/00-canonical-vocabulary.md`.
The foundation below ALREADY EXISTS — use it, never re-create it.

## Foundation that exists (do not modify unless told)
- `backend/app/config.py` — `settings` (pydantic-settings; every env var).
- `backend/app/core/db.py` — `SessionLocal`, `get_session` (FastAPI dep), `session_scope(workspace_id)` (unit of work for jobs), `set_workspace()`.
- `backend/app/core/security.py` — argon2 `hash_password/verify_password`, `create_access_token/decode_access_token`, `new_opaque_token/hash_token`.
- `backend/app/core/crypto.py` — `seal(plaintext, aad) -> Sealed(ciphertext, nonce, key_version)`, `unseal(...)` (AES-GCM envelope).
- `backend/app/core/errors.py` — `ProblemError`, helpers `not_found/forbidden/conflict/validation/budget_exceeded`.
- `backend/app/core/events.py` — `await emit(session, NAME, payload, workspace_id=..., actor=...)` writes the outbox in the caller's txn; `@on_event("NAME")` registers consumers (run by the scheduler's relay).
- `backend/app/core/redis.py` — `get_redis()` (async redis).
- `backend/app/core/pagination.py` — `Page[T]`, cursor helpers.
- `backend/app/core/ids.py` — `new_id()` (UUIDv7).
- `backend/app/core/logging.py` — `get_logger(name)` (structlog, JSON).
- `backend/app/core/ports/*` — Protocols: `AIProvider` (+ `Message/ToolSpec/ToolCall/Completion/Usage`), `EmbeddingProvider`, `SearchProvider` (+`SearchHit`), `ExtractorProvider` (+`ExtractedDocument`), `SocialAdapter` (+`TokenSet/ConnectableAccount/Capabilities/ValidationResult/PublishRequest/PublishResult/RemotePost/PublishError/MediaInput`), `StorageProvider`, `JobQueue`.
- `backend/app/models/*` — ALL ORM models for every table in doc 16 (import from `app.models`). Enums in `app/models/enums.py` (`Platform, MemberRole, ContentStatus, ScheduleStatus, RunStatus, TaskStatus, ApprovalStatus, AccountStatus, ContentFormat, ContentType, Availability, RiskLevel, AutomationStatus`, `ROLE_RANK`).
- `backend/migrations/versions/0001_initial.*` — the whole schema is already migrated. Do NOT write new migrations unless you must add a column (then add `0002_<name>.py` with plain `op.execute` SQL and update the model).
- `backend/app/api/deps.py` — `DB`, `CurrentUser`, `CurrentMember` (has `.user`, `.workspace_id`, `.role`, `.has("editor")`), `require_role("admin")` dependency. Workspace is resolved from `X-Workspace-Id` header or the user's first membership.
- `backend/app/api/errors.py`, `backend/app/api/sse.py` (SSE at `/api/v1/events/stream`), `backend/app/main.py` (auto-includes `app.api.v1.<name>.router` for every module name listed in `ROUTER_MODULES`; each router module must define `router = APIRouter(prefix="/<name>", tags=[...])`).
- `backend/app/workers/app.py` — `procrastinate_app` (Postgres queue). Define jobs as:
  ```python
  from app.workers.app import procrastinate_app
  @procrastinate_app.task(name="jobs.research.run", queue="research", retry=3)
  async def run_research(run_id: str, workspace_id: str) -> None: ...
  ```
  Enqueue from services with `await procrastinate_app.configure_task(name="jobs.research.run", queue="research", queueing_lock=f"research:{id}").defer_async(run_id=str(id), workspace_id=str(ws))`. Job modules: `app/workers/jobs/{ai,research,publishing,analytics,media,competitors,automation,notifications,maintenance}.py` (already exist as stubs; fill them in).
- `backend/app/workers/scheduler.py` — leader loop that calls `app.services.scheduling_service.dispatch_due_posts/dispatch_retries/expire_leases(db)` if they exist, `app.workers.jobs.maintenance.scheduler_hooks()` if it exists, and relays the outbox to Redis/SSE.
- `backend/app/integrations/storage/s3.py` — `storage` (S3Storage: put/get/delete/presign_put/presign_get/public_url), `ensure_buckets()`.
- Frontend scaffold at `frontend/` (Next.js 15 App Router, TypeScript, Tailwind v4, ESLint, `src/` dir, `@/*` alias). Dependencies installed with npm.

## Conventions every builder follows
- Python 3.12, async everywhere, SQLAlchemy 2.0 `select()` style, Pydantic v2 schemas in `app/schemas/<module>.py` (request/response models; `model_config = ConfigDict(from_attributes=True)`).
- Services in `app/services/<name>_service.py` as classes with `async def` methods taking `db: AsyncSession` first. Services emit events via `app.core.events.emit` inside the same transaction, and write `audit_logs` for mutations via `app/services/audit_service.py` (`await audit(db, member, action, target_type, target_id, before=None, after=None)`; if that file doesn't exist yet, the identity builder creates it and others import it; until then wrap in try/except ImportError).
- Routers in `app/api/v1/<name>.py`: thin; validate → service → response schema. Use `CurrentMember` + `require_role`. Return Problem Details via `ProblemError`.
- Every tenant query filters by `workspace_id == member.workspace_id` explicitly (RLS is a backstop).
- Tool names for the LLM: `domain.verb` (e.g. `web.search`, `content.create_draft`). Side-effect classes: READ, WRITE_INTERNAL, EXTERNAL_READ, SPEND, APPROVAL.
- No scraping of logged-in or API-gated surfaces. Only official APIs.
- Tests: `backend/tests/unit/test_<module>.py` with pytest (asyncio mode auto). Unit tests must not require a DB; mark DB tests with `@pytest.mark.integration` and skip if `DATABASE_URL` is unreachable.
- Type hints everywhere; `ruff` clean (line length 110).
- Frontend: feature folders `src/features/<name>/{api.ts,hooks.ts,components/...}`; shared UI in `src/components/ui` (shadcn-style components written by the frontend builder), layout in `src/components/layout`; API calls through `src/lib/api.ts` (`api.get/post/patch/delete(path, body)` with JSON + Problem Details errors + `X-Workspace-Id` header from the workspace store). Routes under `src/app/w/[workspace]/...` and `src/app/(auth)/...` per doc 00 §10.

## Cross-module interfaces (who provides what)
| Provided by | Symbol | Used by |
|---|---|---|
| identity | `app.services.auth_service.AuthService`, `app.services.workspace_service.WorkspaceService`, `app.services.audit_service.audit()`, `app.services.notification_service.NotificationService.notify(db, workspace_id, kind, title, body, link, user_id=None, severity="info")` | everyone |
| brand | `app.services.brand_service.BrandService.build_context(db, brand_id, mode="compact"|"full") -> str` and `.get(db, workspace_id, brand_id) -> Brand` | agents, content, research |
| ai-core | `app.integrations.ai.registry.get_provider(settings_or_workspace) -> AIProvider`, `app.agents.orchestrator.service.AIService.create_run(db, member, *, message, brand_id, mode, agent=None, action=None, inputs=None) -> AIRun`, `app.tools.registry.tool(...)` decorator and `ToolContext`, `app.agents.base.Agent` base class, `app.services.budget_guard.BudgetGuard` | research, content, competitors, frontend via /ai routes |
| research | `app.services.research_service.ResearchService.start_run(db, member, params) -> ResearchRun`, tools `web.search`, `web.fetch`, `research.save_source`, `research.read_source`, `research.find_similar` registered in `app/tools/web.py`, `app/tools/research.py` | ai agents, content, competitors |
| content | `app.services.content_service.ContentService` (create_item, create_variant, new_version, transition, request_approval), `app.services.approval_service.ApprovalService` (create, approve, reject), tools `content.create_draft`, `content.create_variant`, `brand.get_context`, `platform.rules`, `hashtags.suggest` in `app/tools/content.py` | ai agents, scheduling, frontend |
| publishing | `app.services.scheduling_service` (functions `dispatch_due_posts(db)`, `dispatch_retries(db)`, `expire_leases(db)`, class `SchedulingService`), `app.services.publishing_service.PublishingService`, `app.services.social_account_service.SocialAccountService`, `app.services.token_vault.TokenVault`, adapters in `app/integrations/social/*` | frontend, ai propose_* tools |

Builders may create placeholder implementations of symbols they depend on ONLY if the owner hasn't produced them yet, inside their own module and clearly marked `# TEMP until <owner> lands`, and they must not write into another builder's files.

# 29 — Testing Strategy

## 29.1 Pyramid and tooling

| Layer | Tooling | Scope | Runs |
|---|---|---|---|
| Unit | pytest, hypothesis (property tests for normalizers, fingerprinting, platform rules), vitest | pure functions, services with fakes, agents with `FakeProvider`, tools, validators, expression sandbox | every commit (< 2 min) |
| Database | pytest + testcontainers Postgres (pgvector image), Alembic upgrade/downgrade | migrations, constraints, RLS policies, repositories, `SKIP LOCKED` dispatch, unique indexes | every commit |
| API | FastAPI TestClient/httpx AsyncClient against test DB | routes, auth, RBAC, Problem Details, pagination, idempotency keys | every commit |
| Queue/worker | Procrastinate in-memory/testing connector + real Postgres | job enqueue-in-transaction, retries, locks, scheduler loop, lease expiry | every commit |
| Adapter/integration | respx (HTTP mocks) + recorded cassettes (redacted) per platform/provider; contract tests against sandbox accounts (manual/nightly) | request shapes, pagination, error mapping, resumable flows, reconciliation | commit (mocks); nightly/manual (live sandbox) |
| Agent | deterministic harness (`FakeProvider` with scripted tool-call sequences); schema tests; invariant tests | loop behavior, tool permissions, budget enforcement, citation guard, cancellation | every commit |
| Prompt/evals | golden sets + rubric judge; injection corpus | quality regression tracking, safety invariants | nightly (non-blocking except safety invariants, which block) |
| Workflow | engine tests with fake node executors; snapshot of serialized workflows | validation, branching, waits, approvals, resume after crash, dry-run | every commit |
| Publishing | end-to-end with mocked platforms: happy path, each error category, ambiguous+reconcile, partial threads, duplicate prevention | exactly-once effect | every commit |
| OAuth | mocked authorization servers per platform; state/PKCE validation; token encryption; refresh paths; revoked handling | security of connect flows | every commit |
| UI | vitest + Testing Library (components, stores), Storybook for states (empty/loading/error) | component logic and states | every commit |
| E2E | Playwright against docker compose with mocked external APIs (WireMock container for platforms/providers) | onboarding → brand → connect (mock) → research → write → approve → schedule → publish (mock) → analytics (mock) | PR + nightly |
| Load | k6: API (500 rps CRUD), scheduler (10k due posts), publishing throughput, SSE fan-out (1k clients) | capacity on a VPS profile | before VPS release |

## 29.2 Testing AI behavior without flaky outputs
1. **Separate reasoning from mechanics.** The agent loop, tool permission checks, budget guards, citation tracker, and approval gates are tested with a `FakeProvider` that returns scripted responses (including malformed JSON, tool calls to disallowed tools, over-budget sequences, canary leaks). These tests are deterministic and block CI.
2. **Schema-first outputs.** Every agent action has a Pydantic output model; tests assert parse success on a corpus of recorded real outputs (cassettes) and failure handling on corrupted ones.
3. **Invariants, not exact text.** Assert properties: every claim has a source id that exists in the tool results; no URL outside sources; platform limits respected after repurposing; forbidden topics absent; critic uses a different model id than writer; injection corpus produces zero disallowed tool calls.
4. **Golden evals with rubrics (nightly).** Fixed inputs (brand fixtures, research fixtures) → outputs graded by a judge model with a rubric (0–5 per criterion); track trends in a dashboard; alert on drops > 1 point; do not block merges on them except for safety invariants.
5. **Replay from ledger.** Any production run can be replayed offline using stored prompts/responses to reproduce a bug deterministically.
6. **Statistical tools are unit-tested** against known datasets (effect sizes, CIs), so the performance analyst's numbers are trustworthy independent of the model.

## 29.3 Fixtures
`tests/fixtures/brands/*.json` (3 brands across industries incl. a regulated one), `research/*.json` (sources with credibility variety, one with injection), `platform_responses/*` (cassettes), `metrics/*.csv` (90 days synthetic with known effects), `workflows/*.json`.

## 29.4 CI gates
ruff + pyright (strict for `app/`), ESLint/TS, unit+db+api+queue+agent+workflow+publishing+oauth tests, migration up/down, RLS coverage test (every `workspace_id` table has a policy), OpenAPI diff (breaking change detector), Docker build, Playwright smoke. Nightly: evals, live sandbox contract tests (where sandbox accounts exist), dependency audit.

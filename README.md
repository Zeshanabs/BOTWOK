# Botwok

Local-first AI social media operating system: research with citations, competitor intelligence from lawful sources, trends, strategy, AI-written content with critique and fact-checking, human approval, scheduling, exactly-once publishing through official platform APIs, normalized analytics, performance insights, and no-code automations.

- Architecture package: [`docs/architecture/README.md`](docs/architecture/README.md) (37 sections, build blueprint, platform matrix verified 2026-10-08)
- Screen-by-screen walkthrough (wireframe next to the built screen): [`docs/ui-walkthrough.md`](docs/ui-walkthrough.md)
- Builder contract used to implement the modules: [`docs/BUILD_CONTRACT.md`](docs/BUILD_CONTRACT.md)

## Quick start (local)

Prerequisites: Docker Desktop, Node 24+, [`uv`](https://docs.astral.sh/uv/) (installs Python 3.12 itself). `ffmpeg` is optional (video transforms).

```bash
make setup            # .env from .env.example, generates BOTWOK_MASTER_KEY/JWT_SECRET, installs backend + frontend deps
make up               # Postgres (pgvector), Redis, S3-compatible store, Mailpit
make migrate          # schema (69 tables, RLS) + job-queue schema
make seed             # agent registry, prompt templates, demo workspace
scripts/dev.sh        # api :8000, worker, scheduler, web :3000 (logs in .dev-logs/)
```

If the API, worker or scheduler exits right after starting, read its `preflight.failed` log line: it names the problem and the command that fixes it (Postgres not reachable → `make up`; schema missing/out of date or job-queue schema missing → `make migrate`). The job-queue schema is part of the Alembic migrations, so `make migrate` is all that is needed after pulling.

Open http://localhost:3000 and sign in with the seeded demo account (`demo@botwok.local` / `botwok-demo`), or create your own account (the first user owns the workspace). API docs: http://localhost:8000/api/docs. Mailpit (local email): http://localhost:8025.

## Configure AI and search providers

Nothing is required to browse the app. To run agents, add at least one model provider key either in **Settings → AI → Provider keys** (stored encrypted in the database) or in `.env` (`ANTHROPIC_API_KEY`, `OPENAI_API_KEY`, `XAI_API_KEY`, `GOOGLE_API_KEY`). Model routing per tier (cheap / balanced / powerful) and per agent is editable in the same screen. Search providers (`TAVILY_API_KEY`, `BRAVE_API_KEY`, `EXA_API_KEY`) enable web research; without them a self-hosted SearXNG at `SEARXNG_BASE_URL` is used, and without that research completes with "no usable sources". Embeddings use the OpenAI key or a local Ollama model (`OLLAMA_BASE_URL`).

Without keys every AI run fails fast and the Command Center shows exactly what failed, which step, and the cost (zero).

## Connect social accounts

Each platform needs a developer app registered with that platform; put its credentials in `.env` (`META_APP_ID/SECRET`, `LINKEDIN_CLIENT_ID/SECRET`, `X_CLIENT_ID/SECRET`, `TIKTOK_CLIENT_KEY/SECRET`, `GOOGLE_CLIENT_ID/SECRET`, `PINTEREST_APP_ID/SECRET`). OAuth callbacks are built from `PUBLIC_BASE_URL`; most platforms require HTTPS, so run `make tunnel` (cloudflared) and set `PUBLIC_BASE_URL` to the tunnel URL. Instagram, Threads, TikTok photos and Google Business Profile fetch media from a public URL: set `PUBLIC_MEDIA_BASE_URL` to a tunnel to the media bucket. Platform-specific limits, approval requirements and verified facts are in `docs/architecture/26-platform-capability-matrix.md` and `docs/platforms/`.

## Tests and checks

```bash
make test             # backend pytest (unit + integration against the local DB) and frontend vitest
make lint             # ruff + eslint
```

## Repository layout

`backend/` FastAPI app (`app/api`, `app/services`, `app/agents`, `app/tools`, `app/integrations`, `app/workers`), Alembic migrations, tests · `frontend/` Next.js app (`src/app` routes, `src/features/<domain>`, `src/components`) · `docs/` architecture, platform research, screenshots, walkthrough · `infrastructure/` Dockerfiles and compose profiles · `scripts/` dev tooling.

## Status

MVP + V1 scope is implemented and runs locally: identity/RBAC, brand knowledge, research engine, competitor intelligence, trends, content studio with critic/fact-check, approvals, calendar, scheduler with exactly-once publishing (adapters for Facebook, Instagram, Threads, LinkedIn, X, TikTok, YouTube, Pinterest, Google Business Profile), analytics sync and dashboards, AI orchestrator with 13 agents, insights/reports and the automation engine. Live publishing and analytics require platform app credentials; AI features require provider keys.

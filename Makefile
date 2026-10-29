SHELL := /bin/bash
export PATH := $(HOME)/.local/bin:$(PATH)

.PHONY: setup up down logs migrate seed dev api worker scheduler web test lint tunnel

setup: ## copy env, generate keys, install deps
	@test -f .env || cp .env.example .env
	@cd backend && uv sync
	@cd frontend && npm install
	@python3 scripts/generate_master_key.py --write

up: ## start infrastructure (postgres, redis, minio, mailpit)
	docker compose up -d postgres redis s3 mailpit

down:
	docker compose down

logs:
	docker compose logs -f --tail=100

migrate: ## schema (tables, RLS) + job-queue schema, all via alembic
	cd backend && uv run alembic upgrade head

seed:
	cd backend && uv run python -m app.seed

api:
	cd backend && uv run uvicorn app.main:app --reload --port 8000

worker:
	cd backend && uv run python -m app.workers.main worker

scheduler:
	cd backend && uv run python -m app.workers.main scheduler

web:
	cd frontend && npm run dev

dev: ## run api + worker + scheduler + web natively (requires `make up`)
	@trap 'kill 0' SIGINT; \
	( $(MAKE) api ) & ( $(MAKE) worker ) & ( $(MAKE) scheduler ) & ( $(MAKE) web ) & wait

test:
	cd backend && uv run pytest -q
	cd frontend && npm test --silent -- --run

lint:
	cd backend && uv run ruff check . && uv run ruff format --check .
	cd frontend && npm run lint

tunnel:
	cloudflared tunnel --url http://localhost:3000

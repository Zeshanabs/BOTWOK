#!/usr/bin/env bash
# Runs api + worker + scheduler + web natively (infra via docker compose). Logs in ./.dev-logs/*.log
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
export PATH="$HOME/.local/bin:$PATH"
mkdir -p "$ROOT/.dev-logs"
docker compose -f "$ROOT/docker-compose.yml" up -d postgres redis s3 mailpit >/dev/null
uv run --directory "$ROOT/backend" alembic upgrade head
uv run --directory "$ROOT/backend" python -m app.seed || true
( uv run --directory "$ROOT/backend" uvicorn app.main:app --host 127.0.0.1 --port 8000 > "$ROOT/.dev-logs/api.log" 2>&1 ) &
( uv run --directory "$ROOT/backend" python -m app.workers.main worker > "$ROOT/.dev-logs/worker.log" 2>&1 ) &
( uv run --directory "$ROOT/backend" python -m app.workers.main scheduler > "$ROOT/.dev-logs/scheduler.log" 2>&1 ) &
( npm --prefix "$ROOT/frontend" run dev -- --port 3000 > "$ROOT/.dev-logs/web.log" 2>&1 ) &
echo "api :8000  web :3000  logs: $ROOT/.dev-logs"
wait

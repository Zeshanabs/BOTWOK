#!/bin/sh
set -e
case "${BOTWOK_PROCESS:-api}" in
  api)       alembic upgrade head && (procrastinate --app app.workers.app.procrastinate_app schema --apply || true) && exec uvicorn app.main:app --host 0.0.0.0 --port 8000 ;;
  worker)    exec python -m app.workers.main worker ;;
  scheduler) exec python -m app.workers.main scheduler ;;
  *)         echo "unknown BOTWOK_PROCESS=$BOTWOK_PROCESS"; exit 1 ;;
esac

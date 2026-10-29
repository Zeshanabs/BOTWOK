"""Startup checks shared by the API, the worker and the scheduler.

They turn the usual "the backend is not running" situations into one clear `preflight.failed` log line (problem +
the command that fixes it) and a fast exit, instead of a 30 s hang or a stack trace deep inside a database driver:

* Postgres is not reachable (infrastructure not started, wrong DATABASE_URL)  -> `make up`
* the database has no schema, or an older one than the code expects            -> `make migrate`
* the job-queue (procrastinate) schema is missing                              -> `make migrate`
"""
from __future__ import annotations

import asyncio
from pathlib import Path
from urllib.parse import urlsplit

from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine
from sqlalchemy.pool import NullPool

from app.config import settings
from app.core.logging import get_logger

log = get_logger("preflight")
CONNECT_TIMEOUT_S = 5.0
MIGRATIONS_DIR = Path(__file__).resolve().parents[2] / "migrations"


class PreflightError(RuntimeError):
    """The process cannot do its job; the message says what is wrong and which command fixes it."""


def database_target() -> str:
    """host:port/database of DATABASE_URL, never the credentials."""
    u = urlsplit(settings.database_url)
    return f"{u.hostname or 'localhost'}:{u.port or 5432}/{(u.path or '').lstrip('/')}"


def expected_schema_revision() -> str | None:
    """Head revision of the Alembic scripts shipped with this code (None if they cannot be read)."""
    try:
        from alembic.script import ScriptDirectory
        return ScriptDirectory(str(MIGRATIONS_DIR)).get_current_head()
    except Exception as e:  # pragma: no cover - only when the migrations folder is missing from the deployment
        log.warning("preflight.migrations_unreadable", error=str(e))
        return None


async def check_database(*, process: str, require_queue: bool = True) -> None:
    """Raise PreflightError (after logging it) unless Postgres is reachable, migrated to the current head and, when
    `require_queue` is set, carries the procrastinate schema."""
    target = database_target()
    engine = create_async_engine(settings.database_url, poolclass=NullPool)   # one throw-away connection, not the app pool
    try:
        async with asyncio.timeout(CONNECT_TIMEOUT_S):
            async with engine.connect() as conn:
                migrated = (await conn.execute(text("SELECT to_regclass('public.alembic_version')"))).scalar() is not None
                revision = (await conn.execute(text("SELECT version_num FROM alembic_version"))).scalar() if migrated else None
                queue = (await conn.execute(
                    text("SELECT 1 FROM information_schema.tables WHERE table_name = 'procrastinate_jobs' LIMIT 1"))).scalar()
    except TimeoutError as e:
        raise _fail(process, f"Postgres at {target} did not answer within {CONNECT_TIMEOUT_S:.0f}s", "make up") from e
    except Exception as e:  # connection refused, unknown database, bad credentials, ...
        raise _fail(process, f"cannot connect to Postgres at {target}: {e}", "make up (and check DATABASE_URL in .env)") from e
    finally:
        await engine.dispose()

    if not revision:
        raise _fail(process, f"database {target} has no schema (alembic_version missing)", "make migrate")
    expected = expected_schema_revision()
    if expected and revision != expected:
        raise _fail(process, f"database {target} is at schema revision {revision}, this code expects {expected}", "make migrate")
    if require_queue and not queue:
        raise _fail(process, f"job-queue schema (procrastinate_* tables) missing in {target}", "make migrate")
    log.info("preflight.ok", process=process, database=target, schema_revision=revision, queue=bool(queue))


def _fail(process: str, problem: str, fix: str) -> PreflightError:
    log.error("preflight.failed", process=process, problem=problem, fix=f"run `{fix}`")
    return PreflightError(f"{process}: {problem}. Fix: run `{fix}`")

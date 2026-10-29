"""The job-queue schema is part of the Alembic migrations (revision 0002), so `alembic upgrade head` alone is enough
for the worker, the scheduler and every `defer()`; the startup preflight accepts the migrated database."""
from __future__ import annotations

import pytest
from sqlalchemy import text

pytestmark = pytest.mark.integration


async def test_queue_schema_is_migrated(db) -> None:
    from app.core.preflight import expected_schema_revision
    tables = set((await db.execute(text(
        "SELECT table_name FROM information_schema.tables WHERE table_name LIKE 'procrastinate\\_%'"))).scalars())
    assert {"procrastinate_jobs", "procrastinate_events", "procrastinate_workers", "procrastinate_periodic_defers"} <= tables
    functions = set((await db.execute(text("SELECT proname FROM pg_proc WHERE proname LIKE 'procrastinate\\_%'"))).scalars())
    assert {"procrastinate_defer_jobs_v1", "procrastinate_fetch_job_v2", "procrastinate_prune_stalled_workers_v1"} <= functions
    revision = (await db.execute(text("SELECT version_num FROM alembic_version"))).scalar()
    assert revision == expected_schema_revision() == "0002"


async def test_preflight_accepts_migrated_database() -> None:
    from app.core.preflight import check_database, database_target
    await check_database(process="test", require_queue=True)      # does not raise
    target = database_target()
    assert "@" not in target and ":" in target                       # host:port/db, never credentials

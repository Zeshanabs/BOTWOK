"""Transactional job deferral (doc 12 §12.3: "enqueue job in the same transaction").

``procrastinate_app.configure_task(...).defer_async()`` runs on Procrastinate's own psycopg pool, which cannot join an
asyncpg/SQLAlchemy transaction. ``defer_in_txn`` executes Procrastinate's own ``procrastinate_defer_jobs_v1``
SQL function through the caller's session, so the status change and the job row commit (or roll back) together.
``queueing_lock`` semantics are identical (partial unique index on ``status='todo'``): a duplicate lock raises
``AlreadyEnqueued`` and the caller treats it as "already pending".
``defer_async`` is the out-of-transaction fallback (opens the app lazily).
"""
from __future__ import annotations

import json
from datetime import datetime
from typing import Any

from sqlalchemy import text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.logging import get_logger

log = get_logger("queue")
QUEUEING_LOCK_INDEX = "procrastinate_jobs_queueing_lock_idx_v1"


class AlreadyEnqueued(Exception):
    pass


async def defer_in_txn(db: AsyncSession, task_name: str, *, queue: str, args: dict[str, Any],
                       queueing_lock: str | None = None, lock: str | None = None, priority: int = 0,
                       schedule_at: datetime | None = None) -> int:
    """Insert a Procrastinate job in the caller's transaction. Returns the job id."""
    stmt = text(
        "SELECT unnest(procrastinate_defer_jobs_v1(ARRAY[ROW(:queue, :task, :priority, :lock, :qlock, "
        "CAST(:args AS jsonb), CAST(:at AS timestamptz))::procrastinate_job_to_defer_v1])) AS id"
    )
    params = {"queue": queue, "task": task_name, "priority": priority, "lock": lock, "qlock": queueing_lock,
              "args": json.dumps(args, default=str), "at": schedule_at}
    try:
        async with db.begin_nested():
            res = await db.execute(stmt, params)
            job_id = int(res.scalar_one())
    except IntegrityError as e:
        if QUEUEING_LOCK_INDEX in str(e.orig):
            raise AlreadyEnqueued(queueing_lock or "") from e
        raise
    return job_id


async def cancel_pending(db: AsyncSession, queueing_lock: str) -> int:
    """Cancel a still-waiting job by its queueing lock (status todo → cancelled)."""
    res = await db.execute(text("UPDATE procrastinate_jobs SET status='cancelled' WHERE queueing_lock=:l AND status='todo'"),
                           {"l": queueing_lock})
    return res.rowcount or 0


async def pending_exists(db: AsyncSession, queueing_lock: str) -> bool:
    res = await db.execute(text("SELECT 1 FROM procrastinate_jobs WHERE queueing_lock=:l AND status IN ('todo','doing') LIMIT 1"),
                           {"l": queueing_lock})
    return res.first() is not None


async def defer_async(task_name: str, *, queue: str, args: dict[str, Any], queueing_lock: str | None = None,
                      lock: str | None = None, schedule_at: datetime | None = None, priority: int = 0) -> int | None:
    """Out-of-transaction defer via Procrastinate's pool (API handlers / consumers). Opens the app lazily."""
    from app.workers.app import procrastinate_app
    try:
        import procrastinate
        connector = procrastinate_app.connector
        if getattr(connector, "_async_pool", None) is None:
            await procrastinate_app.open_async()
        deferrer = procrastinate_app.configure_task(name=task_name, queue=queue, queueing_lock=queueing_lock, lock=lock,
                                                   schedule_at=schedule_at, priority=priority)
        return await deferrer.defer_async(**args)
    except procrastinate.exceptions.AlreadyEnqueued:
        log.info("queue.already_enqueued", task=task_name, lock=queueing_lock)
        return None

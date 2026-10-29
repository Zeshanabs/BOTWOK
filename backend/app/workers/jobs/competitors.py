"""Jobs: competitors (run on the ``research`` queue — the worker's queue list has no dedicated competitors queue).

* ``jobs.competitors.sync_profile``      — collect one profile, store posts, snapshot stats, news mentions (3 attempts)
* ``jobs.competitors.sync_all``          — enqueue every due profile (monitoring_frequency)
* ``jobs.competitors.enforce_retention`` — YouTube 30-day stats window, raw payloads 30 d, posts 365 d

``scheduler_hooks()`` / ``enqueue_due_syncs(db)`` are exported for the scheduler (maintenance builder can call them).
"""
from __future__ import annotations

import time
from uuid import UUID

from procrastinate import RetryStrategy

from app.core.logging import get_logger
from app.services.competitor_service import enqueue_due_syncs
from app.workers.app import procrastinate_app

log = get_logger("jobs.competitors")
_READ_RETRY = RetryStrategy(max_attempts=2, exponential_wait=30)  # 3 attempts total: +30 s, +15 min
_last_hook = 0.0
HOOK_INTERVAL_S = 300  # maintenance.scheduler_hooks already gates this at 10 min


@procrastinate_app.task(name="jobs.competitors.sync_profile", queue="research", retry=_READ_RETRY)
async def sync_profile(profile_id: str, workspace_id: str) -> dict:
    from app.core.db import session_scope
    from app.services.competitor_service import CompetitorService
    async with session_scope(UUID(workspace_id)) as db:
        res = await CompetitorService.sync_profile(db, UUID(profile_id))
    log.info("competitors.synced", profile_id=profile_id, status=res.get("status"), new=res.get("new"))
    return {k: v for k, v in res.items() if k in ("profile_id", "status", "reason", "items", "new", "changed", "snapshot_id")}


@procrastinate_app.task(name="jobs.competitors.sync_all", queue="research", retry=1)
async def sync_all(limit: int = 100) -> dict:
    from app.core.db import session_scope
    async with session_scope(None) as db:
        n = await enqueue_due_syncs(db, limit=limit)
    return {"enqueued": n}


@procrastinate_app.task(name="jobs.competitors.enforce_retention", queue="research", retry=1)
async def enforce_retention() -> dict:
    from app.core.db import session_scope
    from app.services.competitor_service import CompetitorService
    async with session_scope(None) as db:
        return await CompetitorService.enforce_retention(db)


async def scheduler_hooks() -> None:
    """Call from the scheduler tick: every 10 min enqueue due competitor syncs, hourly feed polls, retention."""
    global _last_hook
    now = time.monotonic()
    if now - _last_hook < HOOK_INTERVAL_S:
        return
    _last_hook = now
    from app.research.queue import defer
    for name, lock in (("jobs.competitors.sync_all", "competitors:sync_all"),
                       ("jobs.research.poll_feeds", "research:poll_feeds"),
                       ("jobs.competitors.enforce_retention", "competitors:retention")):
        try:
            await defer(name, queue="research", lock=lock)
        except Exception as e:
            log.warning("competitors.hook_failed", job=name, error=str(e)[:200])


__all__ = ["sync_profile", "sync_all", "enforce_retention", "scheduler_hooks", "enqueue_due_syncs"]

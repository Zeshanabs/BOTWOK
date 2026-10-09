"""Jobs: analytics (doc 13 §13.3, doc 18 §18.4).

* ``jobs.analytics.sync_account(account_id, workspace_id, force=False)`` — account + due post metrics (reads: 3 attempts).
* ``jobs.analytics.pull_post_metrics(published_post_id, workspace_id)`` — one post pull (scheduled per cadence point).
* ``schedule_metric_pulls`` — ``PUBLISH_SUCCESS`` consumer creating the decaying pull schedule as jobs with ``run_at``.
* ``jobs.analytics.recompute_snapshots(brand_id, workspace_id)``.
"""
from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import UUID

from procrastinate import RetryStrategy

from app.core.db import SessionLocal, session_scope
from app.core.events import on_event
from app.core.logging import get_logger
from app.workers.app import procrastinate_app
from app.workers.queue import AlreadyEnqueued, defer_in_txn

log = get_logger("jobs.analytics")
_READ_RETRY = RetryStrategy(max_attempts=2, exponential_wait=30)   # 3 attempts over ~6 h-ish windows (30 s, then minutes)


@procrastinate_app.task(name="jobs.analytics.sync_account", queue="analytics", retry=_READ_RETRY)
async def sync_account(account_id: str, workspace_id: str | None = None, force: bool = False) -> dict[str, Any]:
    from app.services.analytics_sync_service import AnalyticsSyncService
    async with session_scope(UUID(workspace_id) if workspace_id else None) as db:
        res = await AnalyticsSyncService.sync_account(db, UUID(account_id), force=bool(force))
    log.info("analytics.sync_account", account_id=account_id, status=res.get("status"), pulled=res.get("posts_pulled"))
    return {k: v for k, v in res.items() if k != "errors"} | {"errors": len(res.get("errors") or [])}


@procrastinate_app.task(name="jobs.analytics.pull_post_metrics", queue="analytics", retry=_READ_RETRY)
async def pull_post_metrics(published_post_id: str, workspace_id: str | None = None) -> dict[str, Any]:
    from app.services.analytics_sync_service import AnalyticsSyncService
    async with session_scope(UUID(workspace_id) if workspace_id else None) as db:
        res = await AnalyticsSyncService.sync_post(db, UUID(published_post_id))
    return res


@procrastinate_app.task(name="jobs.analytics.recompute_snapshots", queue="analytics", retry=1)
async def recompute_snapshots(brand_id: str, workspace_id: str) -> dict[str, Any]:
    from app.analytics.snapshots import recompute_snapshots as _recompute
    async with session_scope(UUID(workspace_id)) as db:
        n = await _recompute(db, UUID(workspace_id), UUID(brand_id))
    return {"snapshots": n}


@on_event("PUBLISH_SUCCESS")
async def schedule_metric_pulls(envelope: dict[str, Any]) -> None:
    """Create the decaying pull schedule (1 h, 6 h, 24 h, 72 h, 7 d, 14 d, 30 d, monthly × 6) as jobs with ``run_at``."""
    from app.services.analytics_sync_service import cadence_points
    payload = envelope.get("payload") or {}
    pp_id = payload.get("published_post_id")
    ws = envelope.get("workspace_id")
    platform = payload.get("platform") or ""
    if not pp_id:
        return
    published_at = datetime.fromisoformat(payload["published_at"]) if payload.get("published_at") else datetime.now(UTC)
    if published_at.tzinfo is None:
        published_at = published_at.replace(tzinfo=UTC)
    async with SessionLocal() as db:
        for h in cadence_points(platform):
            try:
                await defer_in_txn(db, "jobs.analytics.pull_post_metrics", queue="analytics", queueing_lock=f"metrics:{pp_id}:{h}",
                                   args={"published_post_id": str(pp_id), "workspace_id": ws}, schedule_at=published_at + timedelta(hours=h))
            except AlreadyEnqueued:
                continue
        await db.commit()


__all__ = ["sync_account", "pull_post_metrics", "recompute_snapshots", "schedule_metric_pulls"]

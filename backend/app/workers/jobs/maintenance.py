"""Jobs: maintenance + ``scheduler_hooks()`` (called by the scheduler leader every tick, rate-limited internally).

Cadences: token monitor hourly (doc 18 §18.4), recurring materialization every 10 min (doc 12 §12.2), competitor due
syncs (competitors module's own hooks, if importable), analytics cadence every 5 min (doc 13 §13.3), retention nightly.
"""
from __future__ import annotations

import time
from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import text

from app.core.db import SessionLocal
from app.core.logging import get_logger
from app.workers.app import procrastinate_app

log = get_logger("jobs.maintenance")

_last: dict[str, float] = {}
INTERVALS = {"token_monitor": 3600, "materialize_recurring": 600, "analytics_cadence": 300, "retention": 86400, "competitors": 600}


def _due(key: str, now: float | None = None) -> bool:
    now = now or time.monotonic()
    if now - _last.get(key, 0.0) >= INTERVALS[key]:
        _last[key] = now
        return True
    return False


async def scheduler_hooks() -> None:
    """Every tick; each hook runs only when its interval elapsed. Failures are logged, never raised to the loop."""
    if _due("token_monitor"):
        try:
            from app.services.social_account_service import SocialAccountService
            async with SessionLocal() as db:
                n = await SocialAccountService.token_monitor(db)
                await db.commit()
            log.info("hooks.token_monitor", handled=n)
        except Exception as e:  # noqa: BLE001
            log.warning("hooks.token_monitor_failed", error=str(e)[:300])
    if _due("materialize_recurring"):
        try:
            from app.services.scheduling_service import materialize_recurring
            async with SessionLocal() as db:
                n = await materialize_recurring(db)
                await db.commit()
            if n:
                log.info("hooks.materialized", created=n)
        except Exception as e:  # noqa: BLE001
            log.warning("hooks.materialize_failed", error=str(e)[:300])
    if _due("competitors"):
        try:
            from app.workers.jobs import competitors as comp
            hooks = getattr(comp, "scheduler_hooks", None)
            if hooks is not None:
                await hooks()
            else:
                async with SessionLocal() as db:
                    await comp.enqueue_due_syncs(db)
                    await db.commit()
        except ImportError:
            pass
        except Exception as e:  # noqa: BLE001
            log.warning("hooks.competitors_failed", error=str(e)[:300])
    if _due("analytics_cadence"):
        try:
            from app.services.analytics_sync_service import dispatch_analytics_cadence
            async with SessionLocal() as db:
                n = await dispatch_analytics_cadence(db)
                await db.commit()
            if n:
                log.info("hooks.analytics_cadence", enqueued=n)
        except ImportError:
            pass
        except Exception as e:  # noqa: BLE001
            log.warning("hooks.analytics_failed", error=str(e)[:300])
    if _due("retention"):
        try:
            from app.workers.queue import AlreadyEnqueued, defer_in_txn
            async with SessionLocal() as db:
                try:
                    await defer_in_txn(db, "jobs.maintenance.enforce_retention", queue="maintenance", queueing_lock="maintenance:retention", args={})
                except AlreadyEnqueued:
                    pass
                await db.commit()
        except Exception as e:  # noqa: BLE001
            log.warning("hooks.retention_failed", error=str(e)[:300])


@procrastinate_app.task(name="jobs.maintenance.enforce_retention", queue="maintenance", retry=1)
async def enforce_retention() -> dict[str, Any]:
    """Nightly housekeeping: expired OAuth states, relayed outbox rows (7 d), old attempt payloads (90 d), revoked tokens
    (30 d), competitor rows past ``retention_until`` (YouTube 30-day rule, doc 27 §27.7) and LinkedIn member activity
    raw payloads (48 h, doc 27 §27.4)."""
    now = datetime.now(UTC)
    out: dict[str, Any] = {}
    async with SessionLocal() as db:
        out["oauth_states"] = (await db.execute(text("DELETE FROM oauth_states WHERE expires_at < :t OR consumed_at < :t"),
                                                {"t": now - timedelta(days=1)})).rowcount
        out["events_outbox"] = (await db.execute(text("DELETE FROM events_outbox WHERE published_at IS NOT NULL AND published_at < :t"),
                                                 {"t": now - timedelta(days=7)})).rowcount
        out["publish_attempts_payloads"] = (await db.execute(text(
            "UPDATE publish_attempts SET platform_response=NULL WHERE platform_response IS NOT NULL AND finished_at < :t"), {"t": now - timedelta(days=90)})).rowcount
        out["oauth_tokens_revoked"] = (await db.execute(text("DELETE FROM oauth_tokens WHERE revoked_at IS NOT NULL AND revoked_at < :t"),
                                                        {"t": now - timedelta(days=30)})).rowcount
        out["linkedin_member_raw"] = (await db.execute(text(
            "UPDATE published_posts SET raw = raw - 'remote' WHERE platform='linkedin' AND raw ? 'remote' AND published_at < :t"),
            {"t": now - timedelta(hours=48)})).rowcount
        try:
            out["competitor_posts"] = (await db.execute(text("DELETE FROM competitor_posts WHERE retention_until IS NOT NULL AND retention_until < :t"),
                                                        {"t": now})).rowcount
        except Exception as e:  # noqa: BLE001 - table owned by the competitors module
            log.warning("retention.competitor_posts_skipped", error=str(e)[:200])
        try:
            out["procrastinate_jobs"] = (await db.execute(text(
                "DELETE FROM procrastinate_jobs WHERE status IN ('succeeded','cancelled') AND id IN "
                "(SELECT job_id FROM procrastinate_events WHERE at < :t)"), {"t": now - timedelta(days=7)})).rowcount
        except Exception as e:  # noqa: BLE001
            log.warning("retention.jobs_skipped", error=str(e)[:200])
        await db.commit()
    log.info("retention.done", **{k: v for k, v in out.items() if isinstance(v, int)})
    return out


__all__ = ["scheduler_hooks", "enforce_retention"]

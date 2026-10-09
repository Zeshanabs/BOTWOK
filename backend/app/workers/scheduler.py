"""Scheduler leader loop (doc 12): due posts → queued + job, retries, outbox relay, maintenance hooks."""
from __future__ import annotations

import asyncio
from datetime import UTC, datetime

from sqlalchemy import text

from app.core.db import SessionLocal
from app.core.events import consumers_for, publish_realtime
from app.core.logging import get_logger

log = get_logger("scheduler")
LOCK_KEY = 7390042
TICK_S = 5


async def relay_outbox() -> int:
    """Publish unpublished outbox rows to Redis (SSE) and dispatch registered consumers. At-least-once."""
    async with SessionLocal() as db:
        rows = (await db.execute(text(
            "SELECT id, event_id, workspace_id, name, payload, actor, occurred_at FROM events_outbox "
            "WHERE published_at IS NULL AND attempts < 10 ORDER BY id LIMIT 200"))).mappings().all()
        n = 0
        for r in rows:
            envelope = {"event_id": str(r["event_id"]), "name": r["name"], "workspace_id": str(r["workspace_id"]) if r["workspace_id"] else None,
                        "payload": r["payload"], "actor": r["actor"], "occurred_at": r["occurred_at"].isoformat()}
            try:
                await publish_realtime(envelope["workspace_id"], envelope)
                for fn in consumers_for(r["name"]):
                    try:
                        await fn(envelope)
                    except Exception as e:
                        log.warning("consumer.failed", event=r["name"], error=str(e))
                await db.execute(text("UPDATE events_outbox SET published_at=now() WHERE id=:id"), {"id": r["id"]})
                n += 1
            except Exception as e:
                log.warning("relay.failed", event=r["name"], error=str(e))
                await db.execute(text("UPDATE events_outbox SET attempts=attempts+1 WHERE id=:id"), {"id": r["id"]})
        await db.commit()
        return n


async def _tick() -> None:
    try:
        from app.services.scheduling_service import dispatch_due_posts, dispatch_retries, expire_leases
        async with SessionLocal() as db:
            n1 = await dispatch_due_posts(db)
            n2 = await dispatch_retries(db)
            n3 = await expire_leases(db)
            await db.commit()
            if n1 or n2 or n3:
                log.info("scheduler.dispatch", due=n1, retries=n2, leases=n3)
    except ImportError:
        pass
    try:
        from app.workers.jobs.maintenance import scheduler_hooks
        await scheduler_hooks()
    except (ImportError, AttributeError):
        pass
    try:  # automation triggers (inert until app.workflows lands)
        from app.workflows.triggers import dispatch_cron, dispatch_waiting
        async with SessionLocal() as db:
            n1 = await dispatch_cron(db)
            n2 = await dispatch_waiting(db)
            await db.commit()
            if n1 or n2:
                log.info("automation.dispatch", cron=n1, waiting=n2)
    except ImportError:
        pass
    except Exception as e:
        log.warning("automation.dispatch_failed", error=str(e))
    try:  # cross-cutting: expire pending approvals past their deadline (every tick is cheap: indexed query)
        from app.services.approval_service import ApprovalService
        async with SessionLocal() as db:
            await ApprovalService.expire(db)
            await db.commit()
    except Exception as e:
        log.debug("approvals.expire_skipped", error=str(e))
    await relay_outbox()


async def scheduler_loop() -> None:
    from app.workers.app import procrastinate_app
    try:
        from app.events import load_consumers
        load_consumers()
    except Exception as e:
        log.warning("consumers.not_loaded", error=str(e))
    await procrastinate_app.open_async()
    async with SessionLocal() as db:
        held = (await db.execute(text("SELECT pg_try_advisory_lock(:k)"), {"k": LOCK_KEY})).scalar()
        while not held:
            log.info("scheduler.standby")
            await asyncio.sleep(15)
            held = (await db.execute(text("SELECT pg_try_advisory_lock(:k)"), {"k": LOCK_KEY})).scalar()
        log.info("scheduler.leader", at=datetime.now(UTC).isoformat())
        while True:
            try:
                await _tick()
            except Exception as e:
                log.error("scheduler.tick_failed", error=str(e))
            await asyncio.sleep(TICK_S)

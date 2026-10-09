"""Jobs: research (queue ``research``).

* ``jobs.research.run``         — execute the research pipeline for one research_runs row (retry 2)
* ``jobs.research.poll_feeds``  — poll due RSS/Atom feeds (hourly cadence per feed)
* ``jobs.research.embed_source``— (re)embed a source's chunks once an embedding provider is available
"""
from __future__ import annotations

from uuid import UUID

from app.core.events import on_event
from app.core.logging import get_logger
from app.workers.app import procrastinate_app

log = get_logger("jobs.research")


@procrastinate_app.task(name="jobs.research.run", queue="research", retry=2)
async def run_research(run_id: str, workspace_id: str) -> dict:
    from app.core.db import SessionLocal, set_workspace
    from app.models.research import ResearchRun
    from app.research.pipeline import run_pipeline
    ws = UUID(workspace_id)
    async with SessionLocal() as db:
        await set_workspace(db, ws)
        run = await db.get(ResearchRun, UUID(run_id))
        if run is None or run.workspace_id != ws:
            log.warning("research.run_missing", run_id=run_id)
            return {"status": "missing"}
        if run.status in ("completed", "cancelled"):
            return {"status": run.status}
        res = await run_pipeline(db, run)
        return {"status": res["status"], "source_count": res["source_count"], "cost_usd": res["cost_usd"]}


@procrastinate_app.task(name="jobs.research.poll_feeds", queue="research", retry=1)
async def poll_feeds(workspace_id: str | None = None, limit: int = 50) -> dict:
    from app.core.db import SessionLocal, set_workspace
    from app.research.feeds import due_feeds, poll_feed
    ws = UUID(workspace_id) if workspace_id else None
    polled = new = 0
    async with SessionLocal() as db:
        if ws:
            await set_workspace(db, ws)
        for feed in await due_feeds(db, workspace_id=ws, limit=limit):
            await set_workspace(db, feed.workspace_id)
            try:
                res = await poll_feed(db, feed)
                new += int(res.get("new", 0))
                polled += 1
                await db.commit()
            except Exception as e:  # one broken feed must not stop the batch
                await db.rollback()
                log.warning("research.feed_poll_failed", feed_id=str(feed.id), error=str(e)[:300])
    return {"polled": polled, "new": new}


@procrastinate_app.task(name="jobs.research.embed_source", queue="research", retry=2)
async def embed_source(source_id: str, workspace_id: str) -> dict:
    from app.core.db import session_scope
    from app.research.ai import get_embedder
    from app.research.store import embed_existing_chunks
    ws = UUID(workspace_id)
    async with session_scope(ws) as db:
        embedder = await get_embedder(db, ws)
        if embedder is None:
            return {"embedded": 0, "reason": "no embedding provider"}
        n = await embed_existing_chunks(db, UUID(source_id), embedder)
    return {"embedded": n}


async def enqueue_feed_polls() -> int | None:
    """Scheduler hook helper: one global poll job per hour (queueing lock prevents pile-ups)."""
    from app.research.queue import defer
    return await defer("jobs.research.poll_feeds", queue="research", lock="research:poll_feeds")


@on_event("SOURCE_SAVED")
async def _embed_on_source_saved(envelope: dict) -> None:
    """Doc 18: SOURCE_SAVED → chunk+embed job, only when an embedding provider exists and chunks still lack vectors."""
    payload = envelope.get("payload") or {}
    sid, ws = payload.get("source_id"), envelope.get("workspace_id")
    if not sid or not ws:
        return
    from sqlalchemy import select

    from app.core.db import SessionLocal, set_workspace
    from app.models.research import ResearchChunk
    from app.research.ai import get_embedder
    async with SessionLocal() as db:
        await set_workspace(db, UUID(ws))
        if await get_embedder(db, UUID(ws)) is None:
            return
        missing = (await db.execute(select(ResearchChunk.id).where(ResearchChunk.source_id == UUID(sid),
                                                                   ResearchChunk.embedding.is_(None)).limit(1))).first()
    if missing:
        from app.research.queue import defer
        await defer("jobs.research.embed_source", queue="research", lock=f"embed:{sid}", source_id=sid, workspace_id=ws)

"""Deferring Procrastinate jobs from API processes (the app is opened lazily; duplicate locks are not errors)."""
from __future__ import annotations

import asyncio
from typing import Any

from app.core.logging import get_logger

log = get_logger("research.queue")
_open_lock: asyncio.Lock | None = None


async def defer(task_name: str, *, queue: str, lock: str | None = None, **kwargs: Any) -> int | None:
    """Enqueue ``task_name``; returns the job id, or None when an identical job is already queued (queueing_lock).
    Raises on infrastructure failure so callers can fall back."""
    global _open_lock
    from procrastinate import exceptions as pexc

    from app.workers.app import procrastinate_app

    cfg: dict[str, Any] = {"queue": queue}
    if lock:
        cfg["queueing_lock"] = lock
    deferrer = procrastinate_app.configure_task(name=task_name, **cfg)
    try:
        return await deferrer.defer_async(**kwargs)
    except pexc.AlreadyEnqueued:
        return None
    except pexc.AppNotOpen:
        if _open_lock is None:
            _open_lock = asyncio.Lock()
        async with _open_lock:
            try:
                await procrastinate_app.open_async()
            except Exception as e:  # already open from another coroutine is fine
                log.debug("queue.open_failed", error=str(e)[:200])
        try:
            return await procrastinate_app.configure_task(name=task_name, **cfg).defer_async(**kwargs)
        except pexc.AlreadyEnqueued:
            return None

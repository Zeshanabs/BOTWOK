"""EventBus: transactional outbox write + Redis fan-out (SSE) + consumer registry."""
from __future__ import annotations

import json
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime
from typing import Any
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.ids import new_id
from app.core.logging import get_logger
from app.core.redis import get_redis

log = get_logger("events")

Consumer = Callable[[dict[str, Any]], Awaitable[None]]
_consumers: dict[str, list[Consumer]] = {}


def on_event(name: str):
    def deco(fn: Consumer) -> Consumer:
        _consumers.setdefault(name, []).append(fn)
        return fn
    return deco


def consumers_for(name: str) -> list[Consumer]:
    return _consumers.get(name, [])


async def emit(session: AsyncSession, name: str, payload: dict[str, Any], *, workspace_id: UUID | None, actor: dict | None = None,
               correlation_id: str | None = None) -> UUID:
    """Write to events_outbox in the caller's transaction. The relay publishes after commit."""
    event_id = new_id()
    await session.execute(
        text("INSERT INTO events_outbox (event_id, workspace_id, name, payload, actor, occurred_at) "
             "VALUES (:id, :ws, :name, CAST(:payload AS jsonb), CAST(:actor AS jsonb), :at)"),
        {"id": str(event_id), "ws": str(workspace_id) if workspace_id else None, "name": name,
         "payload": json.dumps({**payload, "correlation_id": correlation_id}, default=str),
         "actor": json.dumps(actor or {"type": "system"}), "at": datetime.now(UTC)},
    )
    return event_id


async def publish_realtime(workspace_id: str | None, envelope: dict[str, Any]) -> None:
    """Redis fan-out for SSE (called by the outbox relay)."""
    r = get_redis()
    channel = f"ws:{workspace_id}" if workspace_id else "ws:system"
    data = json.dumps(envelope, default=str)
    await r.publish(channel, data)
    await r.xadd(f"stream:{channel}", {"data": data}, maxlen=2000, approximate=True)

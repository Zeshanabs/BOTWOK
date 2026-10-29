"""AuditService: immutable audit_logs writes + cursor listing.

Usage (every module): ``await audit(db, member, "content.approve", "content_item", item.id, before=..., after=...)``.
`member_or_actor` may be a deps ``Member``, a ``User``, an ``ApiKey``, a dict ``{"type": "agent", "id": "writer",
"workspace_id": ...}``, the string ``"system"``, or ``None`` (system).
"""
from __future__ import annotations

import ipaddress
import json
from datetime import date, datetime
from decimal import Decimal
from enum import Enum
from typing import Any
from uuid import UUID

from fastapi import Request
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.logging import request_context
from app.core.pagination import decode_cursor, encode_cursor
from app.models.identity import ApiKey, User
from app.models.platform import AuditLog

ACTOR_TYPES = {"user", "agent", "system", "api_key"}


def _default(o: Any) -> Any:
    if isinstance(o, UUID | Decimal):
        return str(o) if isinstance(o, UUID) else float(o)
    if isinstance(o, datetime | date):
        return o.isoformat()
    if isinstance(o, Enum):
        return o.value
    if isinstance(o, set | frozenset):
        return list(o)
    if isinstance(o, bytes):
        return "<bytes>"
    return str(o)


def jsonable(value: Any) -> Any:
    """Make an arbitrary value JSON-safe for jsonb columns (UUID/datetime/Decimal/Enum → primitives)."""
    if value is None:
        return None
    return json.loads(json.dumps(value, default=_default))


def safe_ip(value: str | None) -> str | None:
    """Return a valid IP string for INET columns, else None (e.g. Starlette's 'testclient')."""
    if not value:
        return None
    try:
        return str(ipaddress.ip_address(value))
    except ValueError:
        return None


def resolve_actor(member_or_actor: Any) -> tuple[str, str, UUID | None]:
    """→ (actor_type, actor_id, workspace_id)."""
    a = member_or_actor
    if a is None or a == "system":
        return "system", "system", None
    if isinstance(a, dict):
        t = str(a.get("type") or "system")
        ws = a.get("workspace_id")
        return (t if t in ACTOR_TYPES else "system"), str(a.get("id") or t), (UUID(str(ws)) if ws else None)
    if isinstance(a, ApiKey):
        return "api_key", str(a.id), a.workspace_id
    if isinstance(a, User):
        return "user", str(a.id), None
    user = getattr(a, "user", None)  # deps.Member (duck-typed to avoid importing the API layer)
    if user is not None and hasattr(a, "workspace_id"):
        return "user", str(user.id), a.workspace_id
    return "system", str(a), None


async def audit(db: AsyncSession, member_or_actor: Any, action: str, target_type: str | None = None,
                target_id: Any = None, before: Any = None, after: Any = None, meta: dict[str, Any] | None = None,
                request: Request | None = None, *, workspace_id: UUID | None = None) -> AuditLog:
    """Append an audit row in the caller's transaction (the caller commits)."""
    actor_type, actor_id, ws = resolve_actor(member_or_actor)
    ctx = request_context.get() or {}
    ip = ua = None
    request_id = ctx.get("request_id")
    if request is not None:
        ip = safe_ip(request.client.host if request.client else None)
        ua = (request.headers.get("user-agent") or "")[:500] or None
        request_id = request_id or request.headers.get("x-request-id")
    row = AuditLog(
        workspace_id=workspace_id or ws, actor_type=actor_type, actor_id=actor_id, action=action,
        target_type=target_type, target_id=str(target_id) if target_id is not None else None,
        before=jsonable(before), after=jsonable(after), meta=jsonable(meta), ip=ip, user_agent=ua, request_id=request_id,
    )
    db.add(row)
    return row


async def list_audit(db: AsyncSession, workspace_id: UUID, cursor: str | None = None, limit: int = 50, *,
                     action: str | None = None, actor_id: str | None = None, target_type: str | None = None,
                     target_id: str | None = None) -> tuple[list[AuditLog], str | None]:
    """Newest first; cursor is the last seen id. Returns (rows, next_cursor)."""
    limit = max(1, min(limit, 200))
    q = select(AuditLog).where(AuditLog.workspace_id == workspace_id)
    c = decode_cursor(cursor)
    if c and c.get("id"):
        q = q.where(AuditLog.id < int(c["id"]))
    if action:
        q = q.where(AuditLog.action.startswith(action))
    if actor_id:
        q = q.where(AuditLog.actor_id == actor_id)
    if target_type:
        q = q.where(AuditLog.target_type == target_type)
    if target_id:
        q = q.where(AuditLog.target_id == target_id)
    rows = list((await db.execute(q.order_by(AuditLog.id.desc()).limit(limit + 1))).scalars())
    nxt = encode_cursor({"id": rows[limit - 1].id}) if len(rows) > limit else None
    return rows[:limit], nxt

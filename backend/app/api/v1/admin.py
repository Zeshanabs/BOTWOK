"""Admin routes: health, audit logs, event log (outbox), jobs (procrastinate), costs (usage_ledger)."""
from __future__ import annotations

import asyncio
import re
import time
from datetime import UTC, datetime, timedelta
from typing import Annotated, Any, Literal

from fastapi import APIRouter, Depends, Query
from sqlalchemy import func, select, text

from app.api.deps import DB, CurrentMember, Member, require_role
from app.core.pagination import Page, decode_cursor, encode_cursor
from app.core.redis import get_redis
from app.models.platform import EventOutbox, UsageLedger
from app.schemas.identity import (
    AuditLogOut,
    CostKindOut,
    CostsOut,
    EventOut,
    HealthCheck,
    HealthOut,
    JobOut,
    JobsPage,
)
from app.services.audit_service import list_audit

router = APIRouter(prefix="/admin", tags=["admin"])
Admin = Annotated[Member, Depends(require_role("admin"))]
SCHEDULER_LOCK_KEY = 7390042


async def _timed(coro: Any, limit_s: float = 5.0) -> tuple[Any, int]:
    t0 = time.perf_counter()
    res = await asyncio.wait_for(coro, limit_s)
    return res, int((time.perf_counter() - t0) * 1000)


@router.get("/health", response_model=HealthOut)
async def health(member: CurrentMember, db: DB) -> HealthOut:
    checks: dict[str, HealthCheck] = {}
    try:
        _, ms = await _timed(db.execute(text("SELECT 1")))
        checks["database"] = HealthCheck(ok=True, latency_ms=ms)
    except Exception as e:
        checks["database"] = HealthCheck(ok=False, detail=str(e)[:200])
    try:
        _, ms = await _timed(get_redis().ping(), 3)
        checks["redis"] = HealthCheck(ok=True, latency_ms=ms)
    except Exception as e:
        checks["redis"] = HealthCheck(ok=False, detail=str(e)[:200] or type(e).__name__)
    try:
        from app.integrations.storage.s3 import ensure_buckets
        _, ms = await _timed(ensure_buckets(), 5)
        checks["storage"] = HealthCheck(ok=True, latency_ms=ms)
    except Exception as e:
        checks["storage"] = HealthCheck(ok=False, detail=str(e)[:200] or type(e).__name__)
    if checks["database"].ok:
        try:
            n = (await db.execute(text("SELECT count(*) FROM pg_locks WHERE locktype='advisory' AND objid=:k AND granted"),
                                  {"k": SCHEDULER_LOCK_KEY})).scalar_one()
            checks["scheduler"] = HealthCheck(ok=n > 0, detail=None if n else "no scheduler leader holds the lock",
                                              info={"leaders": int(n)})
        except Exception as e:
            checks["scheduler"] = HealthCheck(ok=False, detail=str(e)[:200])
        try:
            v = (await db.execute(text("SELECT version_num FROM alembic_version"))).scalars().all()
            checks["migrations"] = HealthCheck(ok=bool(v), info={"version": v[0] if len(v) == 1 else v})
        except Exception as e:
            checks["migrations"] = HealthCheck(ok=False, detail=str(e)[:200])
    core_ok = checks["database"].ok and checks["redis"].ok
    status: Literal["ok", "degraded", "down"] = ("ok" if all(c.ok for c in checks.values()) else "degraded") if core_ok else "down"
    return HealthOut(status=status, checks=checks)


@router.get("/audit-logs", response_model=Page[AuditLogOut])
async def audit_logs(member: Admin, db: DB, cursor: str | None = None, limit: int = Query(default=50, ge=1, le=200),
                     action: str | None = None, actor_id: str | None = None, target_type: str | None = None,
                     target_id: str | None = None) -> Page[AuditLogOut]:
    rows, nxt = await list_audit(db, member.workspace_id, cursor, limit, action=action, actor_id=actor_id,
                                 target_type=target_type, target_id=target_id)
    return Page[AuditLogOut](items=[AuditLogOut.model_validate(r) for r in rows], next_cursor=nxt)


@router.get("/events", response_model=Page[EventOut])
async def events(member: Admin, db: DB, cursor: str | None = None, limit: int = Query(default=50, ge=1, le=200),
                 name: str | None = None, unpublished: bool = False) -> Page[EventOut]:
    q = select(EventOutbox).where(EventOutbox.workspace_id == member.workspace_id)
    c = decode_cursor(cursor)
    if c and c.get("id"):
        q = q.where(EventOutbox.id < int(c["id"]))
    if name:
        q = q.where(EventOutbox.name == name)
    if unpublished:
        q = q.where(EventOutbox.published_at.is_(None))
    rows = list((await db.execute(q.order_by(EventOutbox.id.desc()).limit(limit + 1))).scalars())
    nxt = encode_cursor({"id": rows[limit - 1].id}) if len(rows) > limit else None
    return Page[EventOut](items=[EventOut.model_validate(r) for r in rows[:limit]], next_cursor=nxt)


@router.get("/jobs", response_model=JobsPage)
async def jobs(member: Admin, db: DB, status: str | None = None, queue: str | None = None,
               limit: int = Query(default=50, ge=1, le=200)) -> JobsPage:
    """Procrastinate jobs for this workspace (jobs whose args carry workspace_id) plus system jobs."""
    schema = (await db.execute(text("SELECT table_schema FROM information_schema.tables WHERE table_name='procrastinate_jobs' "
                                    "ORDER BY (table_schema='procrastinate') DESC LIMIT 1"))).scalar_one_or_none()
    if not schema or not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", schema):
        return JobsPage(items=[], available=False, detail="procrastinate schema not applied")
    where = ["(args->>'workspace_id' = :ws OR NOT (args ? 'workspace_id'))"]
    params: dict[str, Any] = {"ws": str(member.workspace_id), "limit": limit}
    if status:
        where.append("status::text = :status")
        params["status"] = status
    if queue:
        where.append("queue_name = :queue")
        params["queue"] = queue
    sql = (f'SELECT id, task_name, status::text AS status, queue_name, attempts, scheduled_at FROM "{schema}".procrastinate_jobs '
           f"WHERE {' AND '.join(where)} ORDER BY id DESC LIMIT :limit")
    rows = (await db.execute(text(sql), params)).mappings().all()
    return JobsPage(items=[JobOut(**dict(r)) for r in rows])


@router.get("/costs", response_model=CostsOut)
async def costs(member: Admin, db: DB, period: Literal["day", "week", "month"] = "month",
                start: datetime | None = None, end: datetime | None = None) -> CostsOut:
    now = datetime.now(UTC)
    day = now.replace(hour=0, minute=0, second=0, microsecond=0)
    default_start = {"day": day, "week": day - timedelta(days=day.weekday()), "month": day.replace(day=1)}[period]
    label = "custom" if (start or end) else period
    start = start or default_start
    end = end or now
    if start.tzinfo is None:
        start = start.replace(tzinfo=UTC)
    if end.tzinfo is None:
        end = end.replace(tzinfo=UTC)
    rows = (await db.execute(
        select(UsageLedger.kind, func.coalesce(func.sum(UsageLedger.quantity), 0), func.coalesce(func.sum(UsageLedger.cost_usd), 0))
        .where(UsageLedger.workspace_id == member.workspace_id, UsageLedger.occurred_at >= start, UsageLedger.occurred_at < end)
        .group_by(UsageLedger.kind).order_by(UsageLedger.kind))).all()
    by_kind = [CostKindOut(kind=k, quantity=float(q), cost_usd=float(c)) for k, q, c in rows]
    return CostsOut(period=label, start=start, end=end,
                    total_cost_usd=round(sum(b.cost_usd for b in by_kind), 6), by_kind=by_kind)

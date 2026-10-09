"""Analytics API (doc 13 §13.4, doc 17): sync, overview (KPIs with basis/coverage), posts, accounts, breakdown."""
from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Query, status
from sqlalchemy import select

from app.analytics.queries import (
    DIMENSIONS,
    account_snapshot,
    brand_tz,
    breakdown,
    compare,
    kpis,
    labels_for,
    metric_value,
    post_rows,
)
from app.api.deps import DB, CurrentMember, Member, require_role
from app.core.errors import validation
from app.models.enums import AccountStatus
from app.models.social import SocialAccount
from app.schemas.analytics import BreakdownOut, OverviewOut, PostMetricsOut, PostsOut, SyncIn, SyncOut
from app.workers.queue import AlreadyEnqueued, defer_in_txn

router = APIRouter(prefix="/analytics", tags=["analytics"])
Editor = Annotated[Member, Depends(require_role("editor"))]


@router.post("/sync", response_model=SyncOut, status_code=status.HTTP_202_ACCEPTED)
async def sync(body: SyncIn, db: DB, member: Editor):
    q = select(SocialAccount).where(SocialAccount.workspace_id == member.workspace_id, SocialAccount.status == AccountStatus.active)
    if body.social_account_id:
        q = q.where(SocialAccount.id == body.social_account_id)
    if body.brand_id:
        q = q.where(SocialAccount.brand_id == body.brand_id)
    accounts = (await db.execute(q)).scalars().unique().all()
    ids: list[str] = []
    for a in accounts:
        try:
            await defer_in_txn(db, "jobs.analytics.sync_account", queue="analytics", queueing_lock=f"analytics:{a.id}",
                               args={"account_id": str(a.id), "workspace_id": str(a.workspace_id), "force": body.force})
            ids.append(str(a.id))
        except AlreadyEnqueued:
            ids.append(str(a.id))
    await db.commit()
    return SyncOut(enqueued=len(ids), account_ids=ids)


def _window(from_: datetime | None, to: datetime | None) -> tuple[datetime, datetime]:
    to = to or datetime.now(UTC)
    from_ = from_ or to - timedelta(days=30)
    return from_, to


@router.get("/overview", response_model=OverviewOut, response_model_by_alias=True)
async def overview(db: DB, member: CurrentMember, brand_id: UUID | None = None, from_: Annotated[datetime | None, Query(alias="from")] = None,
                   to: datetime | None = None, compare_: Annotated[str | None, Query(alias="compare")] = None):
    f, t = _window(from_, to)
    rows = await post_rows(db, member.workspace_id, brand_id=brand_id, since=f, until=t)
    current = kpis(rows)
    prev_meta = None
    if compare_ == "previous":
        span = t - f
        prev_rows = await post_rows(db, member.workspace_id, brand_id=brand_id, since=f - span, until=f)
        current = compare(current, kpis(prev_rows))
        prev_meta = {"from": (f - span).isoformat(), "to": f.isoformat()}
    accounts = await account_snapshot(db, member.workspace_id, brand_id, days=max(1, (t - f).days or 30))
    return OverviewOut.model_validate({"brand_id": str(brand_id) if brand_id else None, "from": f.isoformat(), "to": t.isoformat(), "kpis": current,
                                       "previous_period": prev_meta, "accounts": accounts})


@router.get("/posts", response_model=PostsOut)
async def posts(db: DB, member: CurrentMember, brand_id: UUID | None = None, from_: Annotated[datetime | None, Query(alias="from")] = None,
                to: datetime | None = None, platform: str | None = None, social_account_id: UUID | None = None, campaign_id: UUID | None = None,
                pillar_id: UUID | None = None, sort: str = "published_at", limit: Annotated[int, Query(ge=1, le=500)] = 100):
    f, t = _window(from_, to)
    rows = await post_rows(db, member.workspace_id, brand_id=brand_id, since=f, until=t, platform=platform, social_account_id=social_account_id,
                           campaign_id=campaign_id, pillar_id=pillar_id)
    if sort != "published_at":
        rows.sort(key=lambda r: (metric_value(r, sort) is None, -(metric_value(r, sort) or 0)))
    rows = rows[:limit]
    items = [PostMetricsOut(**{**r, "published_at": r["published_at"].isoformat(), "captured_at": r["captured_at"].isoformat() if r["captured_at"] else None,
                               "metrics": r["metrics"], "availability": {k: str(v) for k, v in r["availability"].items()}}) for r in rows]
    with_metric = sum(1 for r in rows if r["captured_at"] is not None)
    return PostsOut(items=items, coverage={"posts": len(rows), "with_metrics": with_metric})


@router.get("/accounts")
async def accounts(db: DB, member: CurrentMember, brand_id: UUID | None = None, days: Annotated[int, Query(ge=1, le=365)] = 30):
    return {"accounts": await account_snapshot(db, member.workspace_id, brand_id, days=days), "days": days}


@router.get("/breakdown", response_model=BreakdownOut)
async def breakdown_(db: DB, member: CurrentMember, by: str = "platform", metric: str = "engagement_rate", brand_id: UUID | None = None,
                     from_: Annotated[datetime | None, Query(alias="from")] = None, to: datetime | None = None, platform: str | None = None):
    if by not in DIMENSIONS:
        raise validation(f"by must be one of {DIMENSIONS}", [{"code": "invalid_dimension", "field": "by", "message": by}])
    f, t = _window(from_, to)
    rows = await post_rows(db, member.workspace_id, brand_id=brand_id, since=f, until=t, platform=platform)
    tz = await brand_tz(db, brand_id)
    labels = await labels_for(db, member.workspace_id, by)
    return BreakdownOut.model_validate(breakdown(rows, by, metric, tz=tz, labels=labels))

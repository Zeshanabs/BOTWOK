"""analytics_snapshots: materialized aggregates by scope/period (doc 13 §13.1), recomputed incrementally after syncs."""
from __future__ import annotations

import statistics
from collections import defaultdict
from datetime import UTC, date, datetime, timedelta
from typing import Any
from uuid import UUID

from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.analytics.queries import ENGAGEMENT_PARTS, engagement_total, post_rows
from app.models.scheduling import AnalyticsSnapshot

SCOPES = ("brand", "platform", "account", "campaign", "pillar", "format")
PERIODS = ("day", "week", "month")
SUM_METRICS = ("impressions", "reach", "views", "likes", "comments", "shares", "saves", "clicks", "link_clicks", "follows_from_post")


def period_start(d: date, period: str) -> date:
    if period == "day":
        return d
    if period == "week":
        return d - timedelta(days=d.weekday())
    return d.replace(day=1)


def _scope_id(row: dict[str, Any], scope: str) -> str | None:
    return {"brand": "brand", "platform": row.get("platform"), "account": row.get("social_account_id"), "campaign": row.get("campaign_id"),
            "pillar": row.get("pillar_id"), "format": row.get("format")}.get(scope)


def aggregate(rows: list[dict[str, Any]]) -> dict[str, Any]:
    out: dict[str, Any] = {"posts": len(rows), "coverage": {}}
    for m in SUM_METRICS:
        vals = [r["metrics"].get(m) for r in rows if r["availability"].get(m) in ("available", "derived") and r["metrics"].get(m) is not None]
        out[m] = float(sum(vals)) if vals else None
        out["coverage"][m] = len(vals)
    eng = [engagement_total(r["metrics"], r["availability"]) for r in rows]
    eng = [e for e in eng if e is not None]
    out["engagement"] = float(sum(eng)) if eng else None
    out["coverage"]["engagement"] = len(eng)
    rates = [r["engagement_rate"] for r in rows if r.get("engagement_rate") is not None]
    out["engagement_rate_avg"] = round(statistics.mean(rates), 5) if rates else None
    out["engagement_rate_median"] = round(statistics.median(rates), 5) if rates else None
    out["coverage"]["engagement_rate"] = len(rates)
    bases: dict[str, int] = defaultdict(int)
    for r in rows:
        if r.get("engagement_rate_basis"):
            bases[r["engagement_rate_basis"]] += 1
    out["basis"] = dict(bases)
    out["parts"] = list(ENGAGEMENT_PARTS)
    return out


async def recompute_snapshots(db: AsyncSession, workspace_id: UUID, brand_id: UUID, *, since: datetime | None = None, periods: tuple[str, ...] = PERIODS,
                              scopes: tuple[str, ...] = SCOPES) -> int:
    """Recompute every (scope, period) bucket touched by posts published since ``since`` (default 60 days)."""
    since = since or datetime.now(UTC) - timedelta(days=60)
    rows = await post_rows(db, workspace_id, brand_id=brand_id, since=since)
    buckets: dict[tuple[str, str, str, date], list[dict[str, Any]]] = defaultdict(list)
    for r in rows:
        d = r["published_at"].astimezone(UTC).date()
        for scope in scopes:
            sid = _scope_id(r, scope)
            if sid is None:
                continue
            for period in periods:
                buckets[(scope, sid, period, period_start(d, period))].append(r)
    n = 0
    now = datetime.now(UTC)
    for (scope, sid, period, start), group in buckets.items():
        stmt = pg_insert(AnalyticsSnapshot).values(workspace_id=workspace_id, brand_id=brand_id, scope=scope, scope_id=sid, period=period, period_start=start,
                                                   metrics=aggregate(group), computed_at=now)
        stmt = stmt.on_conflict_do_update(index_elements=["brand_id", "scope", "scope_id", "period", "period_start"],
                                          set_={"metrics": stmt.excluded.metrics, "computed_at": now})
        await db.execute(stmt)
        n += 1
    return n

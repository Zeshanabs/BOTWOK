"""analytics.query — READ tool over normalized metrics (doc 06). Registered when the AI core's registry is importable."""
from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import UUID

from app.analytics.queries import brand_tz, breakdown, kpis, labels_for, post_rows

try:
    from app.tools.registry import SideEffect, ToolContext, tool
except ImportError:  # pragma: no cover - AI core not landed
    SideEffect = ToolContext = tool = None  # type: ignore[assignment]

READ_ROLES = {"viewer", "approver", "editor", "admin", "owner"}


async def _rows(ctx: Any, brand_id: Any, from_: datetime | None, to: datetime | None, platform: str | None, limit: int) -> list[dict[str, Any]]:
    db = getattr(ctx, "db", None)
    bid = UUID(str(brand_id)) if brand_id else getattr(ctx, "brand_id", None)
    since = from_ or datetime.now(UTC) - timedelta(days=90)
    if db is not None:
        return await post_rows(db, ctx.workspace_id, brand_id=bid, since=since, until=to, platform=platform, limit=limit)
    async with ctx.session() as s:
        return await post_rows(s, ctx.workspace_id, brand_id=bid, since=since, until=to, platform=platform, limit=limit)


async def analytics_query(ctx: Any, metric: str = "engagement_rate", group_by: str | None = None, brand_id: str | None = None,
                          from_: datetime | None = None, to: datetime | None = None, platform: str | None = None, limit: int = 500) -> dict[str, Any]:
    """Query normalized post metrics: KPIs for the period, or a breakdown by pillar|format|platform|campaign|hour|weekday|account.
    Missing metrics are null and reported in ``coverage``; engagement_rate carries its ``basis`` (impressions/reach/views/followers)."""
    rows = await _rows(ctx, brand_id, from_, to, platform, limit)
    db = getattr(ctx, "db", None)
    if group_by:
        tz = await brand_tz(db, UUID(str(brand_id))) if (db is not None and brand_id) else None
        labels = await labels_for(db, ctx.workspace_id, group_by) if db is not None else {}
        return breakdown(rows, group_by, metric, tz=tz, labels=labels)
    return {"metric": metric, "kpis": kpis(rows), "posts": len(rows), "from": (from_ or datetime.now(UTC) - timedelta(days=90)).isoformat(),
            "to": (to or datetime.now(UTC)).isoformat()}


if tool is not None:
    analytics_query = tool("analytics.query", side_effect=SideEffect.READ, roles=READ_ROLES, timeout_s=30, idempotent=True)(analytics_query)

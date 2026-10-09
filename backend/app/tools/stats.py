"""stats.* — deterministic statistics tools the performance_analyst must use (doc 13 §13.5). READ class, numpy only."""
from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import UUID

from app.analytics import stats as S
from app.analytics.queries import brand_tz, labels_for, post_rows

try:
    from app.tools.registry import SideEffect, ToolContext, tool
except ImportError:  # pragma: no cover
    SideEffect = ToolContext = tool = None  # type: ignore[assignment]

READ_ROLES = {"viewer", "approver", "editor", "admin", "owner"}


async def _rows(ctx: Any, brand_id: Any, period_days: int, platform: str | None) -> list[dict[str, Any]]:
    bid = UUID(str(brand_id)) if brand_id else getattr(ctx, "brand_id", None)
    since = datetime.now(UTC) - timedelta(days=period_days)
    db = getattr(ctx, "db", None)
    if db is not None:
        return await post_rows(db, ctx.workspace_id, brand_id=bid, since=since, platform=platform)
    async with ctx.session() as s:
        return await post_rows(s, ctx.workspace_id, brand_id=bid, since=since, platform=platform)


async def stats_compare_groups(ctx: Any, metric: str = "engagement_rate", group_by: str = "format", period_days: int = 90, brand_id: str | None = None,
                               platform: str | None = None) -> dict[str, Any]:
    """Per group: n, mean, median, bootstrap CI95, effect vs overall (ratio), Mann–Whitney p-value, min_n_ok (n ≥ 5)."""
    rows = await _rows(ctx, brand_id, period_days, platform)
    db = getattr(ctx, "db", None)
    tz = await brand_tz(db, UUID(str(brand_id))) if (db is not None and brand_id) else None
    labels = await labels_for(db, ctx.workspace_id, group_by) if db is not None else {}
    return S.compare_groups(rows, metric, group_by, tz=tz, labels=labels)


async def stats_time_of_day(ctx: Any, metric: str = "engagement_rate", period_days: int = 90, brand_id: str | None = None,
                            platform: str | None = None) -> dict[str, Any]:
    """Weekday × hour heatmap (brand timezone) with n per cell; cells with n < 3 are flagged."""
    rows = await _rows(ctx, brand_id, period_days, platform)
    db = getattr(ctx, "db", None)
    tz = await brand_tz(db, UUID(str(brand_id))) if (db is not None and brand_id) else None
    return S.time_of_day(rows, metric, tz=tz)


async def stats_trend(ctx: Any, metric: str = "engagement_rate", period_days: int = 90, granularity: str = "week", brand_id: str | None = None,
                      platform: str | None = None) -> dict[str, Any]:
    """Series by day|week|month with slope and change vs the previous half of the period."""
    rows = await _rows(ctx, brand_id, period_days, platform)
    return S.trend(rows, metric, granularity=granularity)


async def stats_top_posts(ctx: Any, metric: str = "engagement_rate", k: int = 10, period_days: int = 90, brand_id: str | None = None,
                          platform: str | None = None) -> dict[str, Any]:
    """Top-k published posts by a metric with text/format/pillar."""
    rows = await _rows(ctx, brand_id, period_days, platform)
    return S.top_posts(rows, metric, k=k)


if tool is not None:
    stats_compare_groups = tool("stats.compare_groups", side_effect=SideEffect.READ, roles=READ_ROLES, timeout_s=30, idempotent=True)(stats_compare_groups)
    stats_time_of_day = tool("stats.time_of_day", side_effect=SideEffect.READ, roles=READ_ROLES, timeout_s=30, idempotent=True)(stats_time_of_day)
    stats_trend = tool("stats.trend", side_effect=SideEffect.READ, roles=READ_ROLES, timeout_s=30, idempotent=True)(stats_trend)
    stats_top_posts = tool("stats.top_posts", side_effect=SideEffect.READ, roles=READ_ROLES, timeout_s=30, idempotent=True)(stats_top_posts)

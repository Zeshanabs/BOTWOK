"""Shared read queries over the normalized metric tables (doc 13 §13.4): used by the Analytics API, the ``analytics.query``
tool and the stats tools. Every response carries ``coverage`` (how many posts had the metric) and ``basis`` labels."""
from __future__ import annotations

import statistics
from collections import defaultdict
from datetime import UTC, date, datetime, timedelta
from typing import Any
from uuid import UUID
from zoneinfo import ZoneInfo

from sqlalchemy import and_, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.analytics.normalize import POST_METRIC_KEYS
from app.models.brand import Brand, ContentPillar
from app.models.content import Campaign, ContentItem, ContentVariant
from app.models.enums import Platform
from app.models.scheduling import AccountMetric, PostMetric, PublishedPost
from app.models.social import SocialAccount

ENGAGEMENT_PARTS = ("likes", "comments", "shares", "saves", "clicks")
DIMENSIONS = ("pillar", "format", "platform", "campaign", "hour", "weekday", "account", "content_type")


def _latest_metrics_subquery():
    return (select(PostMetric.published_post_id, func.max(PostMetric.captured_at).label("captured_at"))
            .where(PostMetric.window == "lifetime").group_by(PostMetric.published_post_id).subquery())


async def post_rows(db: AsyncSession, workspace_id: UUID, *, brand_id: UUID | None = None, since: datetime | None = None, until: datetime | None = None,
                    platform: str | None = None, social_account_id: UUID | None = None, campaign_id: UUID | None = None, pillar_id: UUID | None = None,
                    limit: int | None = None) -> list[dict[str, Any]]:
    """Latest lifetime capture per published post joined with its variant/item (one dict per post)."""
    latest = _latest_metrics_subquery()
    q = (select(PublishedPost, PostMetric, ContentVariant, ContentItem, SocialAccount)
         .join(latest, latest.c.published_post_id == PublishedPost.id, isouter=True)
         .join(PostMetric, and_(PostMetric.published_post_id == PublishedPost.id, PostMetric.captured_at == latest.c.captured_at), isouter=True)
         .join(ContentVariant, ContentVariant.id == PublishedPost.content_variant_id, isouter=True)
         .join(ContentItem, ContentItem.id == ContentVariant.content_item_id, isouter=True)
         .join(SocialAccount, SocialAccount.id == PublishedPost.social_account_id)
         .where(PublishedPost.workspace_id == workspace_id, PublishedPost.deleted_at.is_(None)))
    if brand_id:
        q = q.where(PublishedPost.brand_id == brand_id)
    if since:
        q = q.where(PublishedPost.published_at >= since)
    if until:
        q = q.where(PublishedPost.published_at <= until)
    if platform:
        q = q.where(PublishedPost.platform == Platform(platform))
    if social_account_id:
        q = q.where(PublishedPost.social_account_id == social_account_id)
    if campaign_id:
        q = q.where(ContentItem.campaign_id == campaign_id)
    if pillar_id:
        q = q.where(ContentItem.pillar_id == pillar_id)
    q = q.order_by(PublishedPost.published_at.desc())
    if limit:
        q = q.limit(limit)
    out: list[dict[str, Any]] = []
    for pp, pm, v, item, acc in (await db.execute(q)).unique().all():
        metrics = {k: (getattr(pm, k) if pm is not None else None) for k in POST_METRIC_KEYS}
        metrics = {k: (float(val) if val is not None else None) for k, val in metrics.items()}
        avail = dict(pm.availability or {}) if pm is not None else {}
        out.append({"published_post_id": str(pp.id), "external_id": pp.external_id, "external_url": pp.external_url, "published_at": pp.published_at,
                    "platform": pp.platform.value, "social_account_id": str(pp.social_account_id), "account_name": acc.display_name,
                    "content_variant_id": str(pp.content_variant_id) if pp.content_variant_id else None,
                    "content_item_id": str(item.id) if item else None, "title": item.title if item else None,
                    "text": (v.text if v else None), "format": v.format.value if v else None, "pillar_id": str(item.pillar_id) if item and item.pillar_id else None,
                    "campaign_id": str(item.campaign_id) if item and item.campaign_id else None,
                    "content_type": item.content_type.value if item and item.content_type else None,
                    "captured_at": pm.captured_at if pm is not None else None, "metrics": metrics, "availability": avail,
                    "engagement_rate": float(pm.engagement_rate) if pm is not None and pm.engagement_rate is not None else None,
                    "engagement_rate_basis": pm.engagement_rate_basis if pm is not None else None, "segments": pp.segments or []})
    return out


def engagement_total(metrics: dict[str, Any], availability: dict[str, Any]) -> float | None:
    parts = [metrics.get(k) for k in ENGAGEMENT_PARTS if availability.get(k) in ("available", "derived") and metrics.get(k) is not None]
    return float(sum(parts)) if parts else None


def metric_value(row: dict[str, Any], metric: str) -> float | None:
    if metric == "engagement_rate":
        return row.get("engagement_rate")
    if metric == "engagement":
        return engagement_total(row["metrics"], row["availability"])
    v = row["metrics"].get(metric)
    return float(v) if v is not None and row["availability"].get(metric) in ("available", "derived") else None


def group_key(row: dict[str, Any], by: str, tz: ZoneInfo | None = None) -> str | None:
    if by == "pillar":
        return row.get("pillar_id")
    if by == "campaign":
        return row.get("campaign_id")
    if by == "format":
        return row.get("format")
    if by == "platform":
        return row.get("platform")
    if by == "account":
        return row.get("social_account_id")
    if by == "content_type":
        return row.get("content_type")
    at: datetime = row["published_at"]
    local = at.astimezone(tz or UTC)
    if by == "hour":
        return f"{local.hour:02d}"
    if by == "weekday":
        return str(local.weekday())
    return None


def _ci95(values: list[float]) -> tuple[float | None, float | None]:
    if len(values) < 2:
        return None, None
    m = statistics.mean(values)
    se = statistics.stdev(values) / (len(values) ** 0.5)
    return round(m - 1.96 * se, 5), round(m + 1.96 * se, 5)


def breakdown(rows: list[dict[str, Any]], by: str, metric: str, *, tz: ZoneInfo | None = None, labels: dict[str, str] | None = None) -> dict[str, Any]:
    groups: dict[str, list[float]] = defaultdict(list)
    sizes: dict[str, int] = defaultdict(int)
    covered = 0
    for r in rows:
        k = group_key(r, by, tz)
        if k is None:
            k = "(none)"
        sizes[k] += 1
        v = metric_value(r, metric)
        if v is None:
            continue
        covered += 1
        groups[k].append(v)
    out = []
    overall = [v for vs in groups.values() for v in vs]
    overall_mean = statistics.mean(overall) if overall else None
    for k, n in sorted(sizes.items(), key=lambda kv: -kv[1]):
        vals = groups.get(k, [])
        mean = statistics.mean(vals) if vals else None
        lo, hi = _ci95(vals)
        out.append({"key": k, "label": (labels or {}).get(k, k), "n": n, "n_with_metric": len(vals), "value": round(mean, 5) if mean is not None else None,
                    "median": round(statistics.median(vals), 5) if vals else None, "ci": [lo, hi] if lo is not None else None,
                    "effect_vs_overall": round(mean / overall_mean, 3) if (mean is not None and overall_mean) else None, "min_n_ok": len(vals) >= 5})
    bases = defaultdict(int)
    for r in rows:
        if r.get("engagement_rate_basis"):
            bases[r["engagement_rate_basis"]] += 1
    return {"by": by, "metric": metric, "groups": out, "coverage": {"posts": len(rows), "with_metric": covered}, "basis": dict(bases),
            "overall": round(overall_mean, 5) if overall_mean is not None else None}


async def labels_for(db: AsyncSession, workspace_id: UUID, by: str) -> dict[str, str]:
    if by == "pillar":
        rows = (await db.execute(select(ContentPillar.id, ContentPillar.name).where(ContentPillar.workspace_id == workspace_id))).all()
        return {str(i): n for i, n in rows}
    if by == "campaign":
        rows = (await db.execute(select(Campaign.id, Campaign.name).where(Campaign.workspace_id == workspace_id))).all()
        return {str(i): n for i, n in rows}
    if by == "account":
        rows = (await db.execute(select(SocialAccount.id, SocialAccount.display_name).where(SocialAccount.workspace_id == workspace_id))).all()
        return {str(i): n for i, n in rows}
    if by == "weekday":
        return {str(i): d for i, d in enumerate(("Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"))}
    return {}


def kpis(rows: list[dict[str, Any]]) -> dict[str, Any]:
    """Sum/average KPIs over rows with per-metric coverage and basis labels (missing stays missing, never 0)."""
    out: dict[str, Any] = {"posts_published": {"value": len(rows), "coverage": len(rows), "basis": "count"}}
    for metric in ("impressions", "reach", "views", "likes", "comments", "shares", "saves", "clicks", "link_clicks", "follows_from_post"):
        vals = [metric_value(r, metric) for r in rows]
        vals = [v for v in vals if v is not None]
        out[metric] = {"value": float(sum(vals)) if vals else None, "coverage": len(vals), "basis": "sum"}
    eng = [engagement_total(r["metrics"], r["availability"]) for r in rows]
    eng = [e for e in eng if e is not None]
    out["engagement"] = {"value": float(sum(eng)) if eng else None, "coverage": len(eng), "basis": "sum(likes+comments+shares+saves+clicks)"}
    rates = [r["engagement_rate"] for r in rows if r.get("engagement_rate") is not None]
    bases = defaultdict(int)
    for r in rows:
        if r.get("engagement_rate") is not None and r.get("engagement_rate_basis"):
            bases[r["engagement_rate_basis"]] += 1
    out["engagement_rate"] = {"value": round(statistics.mean(rates), 5) if rates else None, "coverage": len(rates), "basis": dict(bases) or None,
                              "median": round(statistics.median(rates), 5) if rates else None}
    return out


def compare(current: dict[str, Any], previous: dict[str, Any]) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for k, cur in current.items():
        prev = previous.get(k, {})
        c, p = cur.get("value"), prev.get("value")
        delta = None
        if c is not None and p is not None:
            delta = round((c - p) / p, 4) if p else None
        out[k] = {**cur, "previous": p, "delta_pct": delta}
    return out


async def account_snapshot(db: AsyncSession, workspace_id: UUID, brand_id: UUID | None = None, days: int = 30) -> list[dict[str, Any]]:
    q = select(SocialAccount).where(SocialAccount.workspace_id == workspace_id)
    if brand_id:
        q = q.where(SocialAccount.brand_id == brand_id)
    accounts = (await db.execute(q)).scalars().unique().all()
    out = []
    since = date.today() - timedelta(days=days)
    for a in accounts:
        rows = (await db.execute(select(AccountMetric).where(AccountMetric.social_account_id == a.id, AccountMetric.date >= since)
                                 .order_by(AccountMetric.date.asc()))).scalars().all()
        latest = rows[-1] if rows else None
        first = rows[0] if rows else None
        followers = latest.followers if latest else None
        delta = (latest.followers - first.followers) if latest and first and latest.followers is not None and first.followers is not None else None
        posts = (await db.execute(select(func.count()).select_from(PublishedPost).where(PublishedPost.social_account_id == a.id, PublishedPost.deleted_at.is_(None),
                                                                                       PublishedPost.published_at >= datetime.now(UTC) - timedelta(days=days)))).scalar() or 0
        out.append({"account_id": str(a.id), "platform": a.platform.value, "display_name": a.display_name, "handle": a.handle, "status": a.status.value,
                    "followers": followers, "followers_delta": delta, "posts_in_period": int(posts),
                    "latest": {k: getattr(latest, k) for k in ("date", "followers", "following", "impressions", "reach", "views", "profile_views", "website_clicks",
                                                                "posts_count", "engagement_total")} if latest else None,
                    "availability": dict(latest.availability or {}) if latest else {}, "last_synced": latest.date.isoformat() if latest else None,
                    "series": [{"date": r.date.isoformat(), "followers": r.followers, "views": r.views, "reach": r.reach} for r in rows]})
    return out


async def brand_tz(db: AsyncSession, brand_id: UUID | None) -> ZoneInfo:
    if brand_id:
        b = await db.get(Brand, brand_id)
        if b and b.timezone:
            try:
                return ZoneInfo(b.timezone)
            except Exception:  # noqa: BLE001
                pass
    return ZoneInfo("UTC")

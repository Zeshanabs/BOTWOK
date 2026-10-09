"""X competitor collector (class A, metered): user lookup (+ timeline when the adapter returns posts). Every read is
counted as quota/cost so paid reads are visible in usage_ledger."""
from __future__ import annotations

from sqlalchemy.ext.asyncio import AsyncSession

from app.models.competitor import Competitor, CompetitorProfile
from app.models.enums import Availability
from app.research.collectors.base import CollectorResult, call_public_profile, first_int, items_from_media


async def collect_x(db: AsyncSession, competitor: Competitor, profile: CompetitorProfile) -> CollectorResult:
    payload, failure = await call_public_profile(db, competitor, profile, "x")
    if failure is not None:
        return failure
    assert payload is not None
    rows = payload.get("tweets") or payload.get("posts") or payload.get("data") or []
    items = items_from_media(rows if isinstance(rows, list) else [], availability=Availability.official_api)
    followers = first_int(payload, "public_metrics.followers_count", "followers_count", "followers")
    media = first_int(payload, "public_metrics.tweet_count", "tweet_count")
    cost = float(payload.get("cost_usd") or 0.0)
    return CollectorResult(status="ok", availability=Availability.official_api, items=items, quota_used=1 + len(items),
                           cost_usd=cost, snapshot={"followers_count": followers, "media_count": media,
                                                    "raw": {"username": payload.get("username"), "id": payload.get("id")}},
                           profile_updates={"followers_count": followers, "media_count": media,
                                            "platform_account_id": payload.get("id"), "display_name": payload.get("name")},
                           meta={"metered": True, "posts": "collected" if items else "not_collected (timeline reads are metered)"})

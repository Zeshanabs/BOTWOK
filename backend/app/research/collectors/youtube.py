"""YouTube competitor collector (class A, policy-limited): channel statistics + recent videos via the Data API adapter.

YouTube API Services policy: a non-audited app may keep another channel's statistics for at most 30 days and may not
derive metrics (scores, rankings) from them — items carry ``retention_days=30`` and snapshots are labeled
"last 30 days, raw counts"; ``stats.describe`` skips engagement derivation for YouTube.
"""
from __future__ import annotations

from sqlalchemy.ext.asyncio import AsyncSession

from app.models.competitor import Competitor, CompetitorProfile
from app.models.enums import Availability
from app.research.collectors.base import CollectorResult, call_public_profile, first_int, items_from_media

RETENTION_DAYS = 30
POLICY_NOTE = "YouTube API Services policy: other channels' statistics kept 30 days; raw counts only, no derived metrics"


async def collect_youtube(db: AsyncSession, competitor: Competitor, profile: CompetitorProfile) -> CollectorResult:
    payload, failure = await call_public_profile(db, competitor, profile, "youtube")
    if failure is not None:
        failure.meta["policy"] = POLICY_NOTE
        return failure
    assert payload is not None
    rows = payload.get("videos") or payload.get("items") or payload.get("media") or []
    items = items_from_media(rows, availability=Availability.official_api, retention_days=RETENTION_DAYS)
    followers = first_int(payload, "subscriber_count", "subscribers", "followers", "statistics.subscriberCount")
    media = first_int(payload, "video_count", "media_count", "statistics.videoCount")
    return CollectorResult(status="ok", availability=Availability.official_api, items=items,
                           quota_used=float(payload.get("quota_units", 1 + len(rows) // 50 + 1)),
                           snapshot={"followers_count": followers, "media_count": media,
                                     "raw": {"policy": POLICY_NOTE, "retention_days": RETENTION_DAYS,
                                             "label": "last 30 days, raw counts"}},
                           profile_updates={"followers_count": followers, "media_count": media},
                           meta={"policy": POLICY_NOTE, "no_derived_metrics": True})

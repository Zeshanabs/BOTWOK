"""Instagram competitor collector (class A): Business Discovery through the brand's connected Instagram account on the
Facebook Login flavor (followers, media_count, last ~25 media with like/comment counts, Reels views when returned)."""
from __future__ import annotations

from sqlalchemy.ext.asyncio import AsyncSession

from app.models.competitor import Competitor, CompetitorProfile
from app.models.enums import Availability
from app.research.collectors.base import CollectorResult, call_public_profile, first_int, items_from_media


async def collect_instagram(db: AsyncSession, competitor: Competitor, profile: CompetitorProfile) -> CollectorResult:
    payload, failure = await call_public_profile(db, competitor, profile, "instagram", flavor="facebook_login")
    if failure is not None:
        return failure
    assert payload is not None
    items = items_from_media(payload.get("media") or [], availability=Availability.official_api)
    return CollectorResult(
        status="ok", availability=Availability.official_api, items=items, quota_used=1,
        snapshot={"followers_count": first_int(payload, "followers", "followers_count"),
                  "media_count": first_int(payload, "media_count"), "raw": {k: v for k, v in payload.items() if k != "media"}},
        profile_updates={"followers_count": first_int(payload, "followers", "followers_count"),
                         "media_count": first_int(payload, "media_count"), "display_name": payload.get("name")})

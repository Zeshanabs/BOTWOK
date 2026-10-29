"""LinkedIn organization collector (class A minimal + E): follower count only — other organizations' posts are not
readable through any LinkedIn API, so posts are always ``not_collected``."""
from __future__ import annotations

from sqlalchemy.ext.asyncio import AsyncSession

from app.models.competitor import Competitor, CompetitorProfile
from app.models.enums import Availability
from app.research.collectors.base import CollectorResult, call_public_profile, first_int

POSTS_NOTE = "LinkedIn does not expose other organizations' posts (not collected)"


async def collect_linkedin(db: AsyncSession, competitor: Competitor, profile: CompetitorProfile) -> CollectorResult:
    payload, failure = await call_public_profile(db, competitor, profile, "linkedin")
    if failure is not None:
        failure.meta["posts"] = POSTS_NOTE
        return failure
    assert payload is not None
    followers = first_int(payload, "followers", "followers_count")
    return CollectorResult(status="ok", availability=Availability.official_api, items=[], quota_used=2,
                           snapshot={"followers_count": followers, "raw": {"name": payload.get("name"),
                                                                            "posts": "not_collected"}},
                           profile_updates={"followers_count": followers, "display_name": payload.get("name")},
                           meta={"posts": POSTS_NOTE})

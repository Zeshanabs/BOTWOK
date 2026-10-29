"""Competitor collectors per platform/kind (doc 08 §8.3)."""
from __future__ import annotations

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.safe_fetch import SafeFetcher
from app.models.competitor import Competitor, CompetitorProfile
from app.models.enums import Availability
from app.research.collectors.base import CollectedItem, CollectorResult

WEB_KINDS = ("website", "blog", "rss", "other")
NOT_COLLECTED_REASONS = {
    "tiktok": "TikTok has no commercial API for other accounts (paste public post URLs as notes instead)",
    "pinterest": "Pinterest does not expose other accounts through its API",
    "gbp": "Google Business Profile data of other businesses is not available through the API",
    "facebook": "Other Pages require Page Public Content Access (App Review + Business Verification)",
}


async def collect(db: AsyncSession, competitor: Competitor, profile: CompetitorProfile, *,
                  fetcher: SafeFetcher | None = None) -> CollectorResult:
    """Dispatch to the collector for ``profile`` (website/blog → crawl; platforms → official-API adapters)."""
    platform = profile.platform.value if profile.platform is not None else None
    if platform is None:
        if profile.kind == "rss" and profile.url:
            return CollectorResult(status="ok", availability=Availability.public_web, feeds=[profile.url])
        from app.research.collectors.website import collect_website
        return await collect_website(competitor, profile, fetcher=fetcher)
    if platform == "instagram":
        from app.research.collectors.instagram_bd import collect_instagram
        return await collect_instagram(db, competitor, profile)
    if platform == "youtube":
        from app.research.collectors.youtube import collect_youtube
        return await collect_youtube(db, competitor, profile)
    if platform == "x":
        from app.research.collectors.x import collect_x
        return await collect_x(db, competitor, profile)
    if platform == "linkedin":
        from app.research.collectors.linkedin_org import collect_linkedin
        return await collect_linkedin(db, competitor, profile)
    if platform == "threads":
        from app.research.collectors.base import call_public_profile, first_int
        payload, failure = await call_public_profile(db, competitor, profile, "threads")
        if failure is not None:
            if failure.status == "unavailable" and "approv" in (failure.reason or "").lower():
                failure.status = "needs_approval"
            return failure
        assert payload is not None
        followers = first_int(payload, "follower_count", "followers_count", "followers")
        return CollectorResult(status="ok", availability=Availability.official_api, quota_used=1,
                               snapshot={"followers_count": followers, "raw": {"username": payload.get("username")}},
                               profile_updates={"followers_count": followers})
    return CollectorResult(status="not_collected", availability=Availability.not_collected,
                           reason=NOT_COLLECTED_REASONS.get(platform, f"{platform} competitor data is not available"))


__all__ = ["CollectedItem", "CollectorResult", "collect", "WEB_KINDS", "NOT_COLLECTED_REASONS"]

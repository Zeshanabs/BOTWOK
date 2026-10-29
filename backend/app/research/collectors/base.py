"""Competitor collectors (doc 08 §8.3): one per platform/kind, all returning ``CollectorResult``.

Collectors never scrape gated surfaces: website/blog use the public web (robots honored), platforms go through the
publishing builder's official-API adapters (``get_adapter(platform).get_public_profile``) and the brand's own connected
account. When an adapter, account, token or approval is missing, the result says so (``status`` + ``reason``) instead of
guessing.
"""
from __future__ import annotations

import inspect
import re
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.logging import get_logger
from app.integrations.search.base import parse_date
from app.models.competitor import Competitor, CompetitorProfile
from app.models.enums import AccountStatus, Availability, ContentFormat
from app.models.social import SocialAccount
from app.research.dedupe import content_hash

log = get_logger("competitors.collectors")
_HASHTAG_RE = re.compile(r"(?<![\w&])#(\w{2,60})", re.UNICODE)
_MENTION_RE = re.compile(r"(?<![\w@])@([A-Za-z0-9_.]{2,30})")
_URL_RE = re.compile(r"https?://\S+")


@dataclass
class CollectedItem:
    text: str | None
    url: str | None = None
    external_id: str | None = None
    posted_at: datetime | None = None
    format: ContentFormat | None = None
    hashtags: list[str] = field(default_factory=list)
    mentions: list[str] = field(default_factory=list)
    media_urls: list[str] = field(default_factory=list)
    like_count: int | None = None
    comment_count: int | None = None
    share_count: int | None = None
    view_count: int | None = None
    availability: Availability = Availability.public_web
    retention_days: int | None = None
    meta: dict[str, Any] = field(default_factory=dict)

    @property
    def content_hash(self) -> str:
        basis = self.text or ""
        if self.external_id:
            basis = f"{self.external_id}|{basis}"
        elif self.url and not basis:
            basis = self.url
        return content_hash(basis) if basis else content_hash(self.url or "")


@dataclass
class CollectorResult:
    status: str = "ok"                 # ok | unavailable | not_collected | needs_approval | error | partial
    availability: Availability = Availability.not_collected
    items: list[CollectedItem] = field(default_factory=list)
    snapshot: dict[str, Any] = field(default_factory=dict)    # followers_count, media_count, bio, raw…
    profile_updates: dict[str, Any] = field(default_factory=dict)
    reason: str | None = None
    quota_used: float = 0.0
    cost_usd: float = 0.0
    feeds: list[str] = field(default_factory=list)
    meta: dict[str, Any] = field(default_factory=dict)


def parse_tags(text: str | None) -> tuple[list[str], list[str]]:
    if not text:
        return [], []
    tags = list(dict.fromkeys(t.lower() for t in _HASHTAG_RE.findall(text)))
    mentions = list(dict.fromkeys(m.lower().rstrip(".") for m in _MENTION_RE.findall(text)))
    return tags, mentions


def has_link(text: str | None) -> bool:
    return bool(text and _URL_RE.search(text))


async def brand_account(db: AsyncSession, workspace_id: Any, brand_id: Any, platform: str,
                        flavor: str | None = None) -> SocialAccount | None:
    stmt = select(SocialAccount).where(SocialAccount.workspace_id == workspace_id, SocialAccount.brand_id == brand_id,
                                       SocialAccount.platform == platform, SocialAccount.disconnected_at.is_(None),
                                       SocialAccount.status == AccountStatus.active)
    if flavor:
        stmt = stmt.where(SocialAccount.auth_flavor == flavor)
    return (await db.execute(stmt.order_by(SocialAccount.created_at).limit(1))).scalar_one_or_none()


def _adapter(platform: str) -> Any | None:
    try:
        from app.integrations.social.registry import get_adapter
        return get_adapter(platform)
    except Exception as e:  # registry/adapters not installed yet, or unknown platform
        log.info("competitors.adapter_unavailable", platform=platform, error=str(e)[:200])
        return None


async def call_public_profile(db: AsyncSession, competitor: Competitor, profile: CompetitorProfile, platform: str, *,
                              flavor: str | None = None) -> tuple[dict[str, Any] | None, CollectorResult | None]:
    """Invoke ``adapter.get_public_profile`` through the brand's connected account. Returns (payload, None) on success or
    (None, CollectorResult describing why nothing was collected)."""
    adapter = _adapter(platform)
    fn = getattr(adapter, "get_public_profile", None) if adapter is not None else None
    if fn is None:
        return None, CollectorResult(status="unavailable", availability=Availability.official_api,
                                     reason=f"{platform} public-profile reads are not available in this installation")
    handle = (profile.handle or profile.platform_account_id or "").lstrip("@").strip()
    if not handle:
        return None, CollectorResult(status="error", availability=Availability.official_api, reason="profile has no handle")
    account = await brand_account(db, competitor.workspace_id, competitor.brand_id, platform, flavor)
    params = inspect.signature(fn).parameters
    needs_tokens = "tokens" in params
    if (needs_tokens or "account" in params) and account is None:
        return None, CollectorResult(status="unavailable", availability=Availability.official_api,
                                     reason=f"connect a {platform} account for this brand to read public profiles"
                                            + (" (Facebook Login flavor)" if flavor == "facebook_login" else ""))
    kwargs: dict[str, Any] = {}
    if "account" in params:
        kwargs["account"] = account
    if needs_tokens:
        try:
            from app.services.token_vault import TokenVault
            kwargs["tokens"] = await TokenVault().get_tokens(db, account)  # type: ignore[arg-type]
        except Exception as e:
            return None, CollectorResult(status="unavailable", availability=Availability.official_api,
                                         reason=f"no usable token for the connected {platform} account: {type(e).__name__}")
    for name in ("username", "handle", "organization_id", "channel_id", "user_id"):
        if name in params:
            kwargs[name] = handle
            break
    try:
        payload = await fn(**kwargs)
    except Exception as e:
        category = getattr(e, "category", None)
        code = getattr(e, "code", None)
        if category == "unsupported" or code in ("permission_required", "unsupported"):
            return None, CollectorResult(status="needs_approval" if code == "permission_required" else "unavailable",
                                         availability=Availability.official_api, reason=str(e)[:300])
        if category == "rate_limited":
            return None, CollectorResult(status="error", availability=Availability.official_api,
                                         reason=f"rate limited: {e}"[:300], meta={"retry_after_s": getattr(e, "retry_after_s", None)})
        return None, CollectorResult(status="error", availability=Availability.official_api, reason=f"{type(e).__name__}: {e}"[:300])
    return (payload if isinstance(payload, dict) else {"raw": payload}), None


def first_int(d: dict[str, Any], *keys: str) -> int | None:
    for k in keys:
        cur: Any = d
        for part in k.split("."):
            cur = cur.get(part) if isinstance(cur, dict) else None
        if cur is not None:
            try:
                return int(cur)
            except (TypeError, ValueError):
                continue
    return None


def media_format(media_type: str | None, product_type: str | None = None) -> ContentFormat | None:
    mt = (media_type or "").upper()
    pt = (product_type or "").upper()
    if pt == "REELS":
        return ContentFormat.short_video
    if pt == "STORY":
        return ContentFormat.story
    return {"IMAGE": ContentFormat.image, "VIDEO": ContentFormat.video, "CAROUSEL_ALBUM": ContentFormat.carousel,
            "TEXT_POST": ContentFormat.text, "TEXT": ContentFormat.text, "REEL": ContentFormat.short_video,
            "SHORT": ContentFormat.short_video}.get(mt)


def items_from_media(rows: list[dict[str, Any]], *, availability: Availability = Availability.official_api,
                     retention_days: int | None = None) -> list[CollectedItem]:
    out: list[CollectedItem] = []
    for r in rows or []:
        if not isinstance(r, dict):
            continue
        text = r.get("caption") or r.get("text") or r.get("description") or r.get("title")
        tags, mentions = parse_tags(text)
        out.append(CollectedItem(
            text=text, url=r.get("permalink") or r.get("url"), external_id=str(r.get("id")) if r.get("id") else None,
            posted_at=parse_date(r.get("timestamp") or r.get("created_at") or r.get("published_at") or r.get("publishedAt")),
            format=media_format(r.get("media_type"), r.get("media_product_type")) or (ContentFormat.text if text else None),
            hashtags=tags, mentions=mentions, media_urls=[u for u in [r.get("media_url"), r.get("thumbnail_url")] if u],
            like_count=first_int(r, "like_count", "likes", "public_metrics.like_count", "statistics.likeCount"),
            comment_count=first_int(r, "comments_count", "comment_count", "public_metrics.reply_count", "statistics.commentCount"),
            share_count=first_int(r, "shares", "share_count", "public_metrics.retweet_count"),
            view_count=first_int(r, "view_count", "views", "public_metrics.impression_count", "statistics.viewCount"),
            availability=availability, retention_days=retention_days))
    return out

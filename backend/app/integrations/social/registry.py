"""Adapter registry: platform code → SocialAdapter instance (doc 11 §11.1)."""
from __future__ import annotations

from functools import lru_cache
from typing import Any

from app.core.ports.social_adapter import SocialAdapter
from app.integrations.social.base import VERIFIED_AT, BaseAdapter

PLATFORMS = ("facebook", "instagram", "threads", "linkedin", "x", "tiktok", "youtube", "pinterest", "gbp")

# Static facts from doc 26 that are not part of ``Capabilities`` (approval gates, data rules); shown in the UI.
PLATFORM_NOTES: dict[str, dict[str, Any]] = {
    "facebook": {"name": "Facebook Page", "approval": "App Review for pages_manage_posts/pages_read_engagement; dev mode works for app roles",
                 "flavors": ["default"], "tier": "V1"},
    "instagram": {"name": "Instagram (Professional)", "approval": "App Review (Advanced Access) + Business Verification; Instagram Login needs no Page",
                  "flavors": ["facebook_login", "instagram_login"], "tier": "V1"},
    "threads": {"name": "Threads", "approval": "App Review for non-own data", "flavors": ["default"], "tier": "V1"},
    "linkedin": {"name": "LinkedIn", "approval": "member posting self-serve; Community Management application for organizations/analytics",
                 "flavors": ["member", "organization"], "tier": "V1"},
    "x": {"name": "X", "approval": "developer account + pay-per-use credits (post $0.015, post with URL $0.20)",
          "flavors": ["default"], "tier": "V1"},
    "tiktok": {"name": "TikTok", "approval": "app review; Content Posting audit for public direct posts (team tools rejected) → inbox upload default",
               "flavors": ["inbox_upload", "direct_post"], "tier": "V2"},
    "youtube": {"name": "YouTube", "approval": "Google OAuth verification; YouTube compliance audit (unaudited uploads locked private)",
                "flavors": ["default"], "tier": "V1"},
    "pinterest": {"name": "Pinterest", "approval": "Trial (sandbox pins) → Standard (OAuth flow video)", "flavors": ["default"], "tier": "V2"},
    "gbp": {"name": "Google Business Profile", "approval": "access request form; quota 0 until approved", "flavors": ["default"], "tier": "V2"},
}


@lru_cache(maxsize=1)
def _adapters() -> dict[str, BaseAdapter]:
    from app.integrations.social.gbp import GBPAdapter
    from app.integrations.social.linkedin import LinkedInAdapter
    from app.integrations.social.meta.facebook import FacebookAdapter
    from app.integrations.social.meta.instagram import InstagramAdapter
    from app.integrations.social.meta.threads import ThreadsAdapter
    from app.integrations.social.pinterest import PinterestAdapter
    from app.integrations.social.tiktok import TikTokAdapter
    from app.integrations.social.x import XAdapter
    from app.integrations.social.youtube import YouTubeAdapter
    return {
        "facebook": FacebookAdapter(), "instagram": InstagramAdapter(), "threads": ThreadsAdapter(),
        "linkedin": LinkedInAdapter(), "x": XAdapter(), "tiktok": TikTokAdapter(), "youtube": YouTubeAdapter(),
        "pinterest": PinterestAdapter(), "gbp": GBPAdapter(),
    }


class _LazyAdapters(dict):
    """``ADAPTERS`` dict that materializes adapters on first access (keeps import cheap and test-overridable)."""

    def _load(self) -> None:
        if not super().__len__():
            super().update(_adapters())

    def __getitem__(self, k: str) -> BaseAdapter:
        self._load()
        return super().__getitem__(k)

    def get(self, k: str, default: Any = None) -> Any:  # type: ignore[override]
        self._load()
        return super().get(k, default)

    def items(self):  # type: ignore[override]
        self._load()
        return super().items()

    def keys(self):  # type: ignore[override]
        self._load()
        return super().keys()

    def values(self):  # type: ignore[override]
        self._load()
        return super().values()

    def __contains__(self, k: object) -> bool:
        self._load()
        return super().__contains__(k)

    def __len__(self) -> int:
        self._load()
        return super().__len__()


ADAPTERS: dict[str, BaseAdapter] = _LazyAdapters()


def get_adapter(platform: str) -> SocialAdapter:
    key = platform.value if hasattr(platform, "value") else str(platform)
    try:
        return ADAPTERS[key]  # type: ignore[return-value]
    except KeyError as e:
        raise LookupError(f"unknown platform {platform!r}") from e


def capabilities_matrix() -> dict[str, Any]:
    """Doc 26 matrix as data for ``GET /social/capabilities`` and the Admin → Integrations page."""
    out: dict[str, Any] = {"verified_at": VERIFIED_AT, "platforms": {}}
    for code in PLATFORMS:
        adapter = ADAPTERS[code]
        caps = adapter.capabilities(None)
        out["platforms"][code] = {
            **PLATFORM_NOTES.get(code, {}),
            "verified_at": getattr(adapter, "verified_at", VERIFIED_AT),
            "formats": caps.formats, "max_text": caps.max_text, "max_media": caps.max_media,
            "native_schedule": caps.native_schedule, "can_delete": caps.can_delete,
            "supports_alt_text": caps.supports_alt_text, "limits": caps.limits, "notes": caps.notes,
            "can_list_own_posts": getattr(adapter, "can_list_own_posts", True),
        }
    return out

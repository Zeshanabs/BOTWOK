"""Threads adapter (doc 27 §27.3, docs/platforms/meta-facebook-instagram-threads.md §3). VERIFIED_AT 2026-10-08.

Threads Login (``threads.net/oauth/authorize``) with the Threads app id/secret; API at ``graph.threads.net/v1.0``.
Short-lived → long-lived (60 d, ``th_exchange_token``) → refresh (``th_refresh_token``, token ≥ 24 h old).
Publishing: ``POST /{user}/threads`` (TEXT / IMAGE / VIDEO / CAROUSEL with children) → wait ≥ 30 s for media →
``POST /{user}/threads_publish``. Chains (segments) are replies to the previous post (``reply_to_id``).
Limits: 500 chars (UTF-8 bytes), ≤ 5 links, carousels 2–20, 250 posts / 24 h (``threads_publishing_limit``).
Profile lookup / keyword search need approved permissions (``threads_profile_discovery`` / ``threads_keyword_search``).
"""
from __future__ import annotations

import asyncio
from datetime import UTC, datetime
from typing import Any
from urllib.parse import urlencode

from app.config import settings
from app.core.ports.social_adapter import (
    Capabilities,
    ConnectableAccount,
    PublishError,
    PublishRequest,
    PublishResult,
    RemotePost,
    TokenSet,
    ValidationResult,
)
from app.integrations.social.base import (
    BaseAdapter,
    account_attr,
    find_urls,
    heartbeat,
    issue,
    media_info,
    result,
    save_state,
)
from app.integrations.social.meta.client import (
    THREADS_HOST,
    THREADS_VERSION,
    MetaGraphClient,
    insights_to_dict,
)

VERIFIED_AT = "2026-10-08"
SCOPES = ["threads_basic", "threads_content_publish", "threads_manage_insights", "threads_manage_replies", "threads_read_replies",
          "threads_delete"]
OPTIONAL_SCOPES = ["threads_keyword_search", "threads_profile_discovery"]
TEXT_MAX_BYTES = 500
LINKS_MAX = 5
CAROUSEL_RANGE = (2, 20)
POSTS_PER_24H = 250
MEDIA_WAIT_S = 30
MEDIA_INSIGHTS = "views,likes,replies,reposts,quotes,shares"
ACCOUNT_INSIGHTS = "views,likes,replies,reposts,quotes,clicks,followers_count"


def threads_length(text: str) -> int:
    """Threads counts emojis as UTF-8 bytes: ASCII = 1, multi-byte characters by their byte length."""
    return sum(1 if ord(c) < 128 else len(c.encode("utf-8")) for c in text)


def _threads_app() -> tuple[str, str]:
    return (getattr(settings, "threads_app_id", "") or settings.meta_app_id, getattr(settings, "threads_app_secret", "") or settings.meta_app_secret)


class ThreadsAdapter(BaseAdapter):
    platform = "threads"
    verified_at = VERIFIED_AT
    VERIFIED_AT = VERIFIED_AT
    docs = ["https://developers.facebook.com/docs/threads/posts", "https://developers.facebook.com/docs/threads/get-started/long-lived-tokens",
            "https://developers.facebook.com/docs/threads/insights"]

    def __init__(self) -> None:
        super().__init__()
        self.graph = MetaGraphClient("threads", THREADS_HOST, THREADS_VERSION)
        self.graph.app_secret = ""

    def capabilities(self, account: Any) -> Capabilities:
        return Capabilities(
            formats=["text", "link", "image", "video", "carousel", "poll"],
            max_text=TEXT_MAX_BYTES, max_media=CAROUSEL_RANGE[1], native_schedule=False, can_delete=True, supports_alt_text=True,
            limits={"posts_per_24h": POSTS_PER_24H, "replies_per_24h": 1000, "deletes_per_24h": 100, "links_max": LINKS_MAX,
                    "carousel": list(CAROUSEL_RANGE), "image_max_bytes": 8 * 1024**2, "video_max_s": 300, "video_max_bytes": 1024**3,
                    "media_wait_s": MEDIA_WAIT_S, "token_lifetime_days": 60},
            notes=["public media URL required", "no Stories", "wait ≥ 30 s before publishing media containers",
                   "profile lookup / keyword search only with approved permissions", "views/shares metrics marked 'in development' by Meta"],
        )

    # ---- OAuth -------------------------------------------------------------------------------------------
    def auth_url(self, state: str, redirect_uri: str, flavor: str = "default", code_challenge: str | None = None) -> str:
        app_id, _ = _threads_app()
        q = {"client_id": app_id, "redirect_uri": redirect_uri, "scope": ",".join(SCOPES), "response_type": "code", "state": state}
        return f"https://threads.net/oauth/authorize?{urlencode(q)}"

    async def exchange_code(self, code: str, redirect_uri: str, code_verifier: str | None = None) -> TokenSet:
        app_id, secret = _threads_app()
        short = await self.graph.http.post_json(f"{THREADS_HOST}/oauth/access_token",
                                                data={"client_id": app_id, "client_secret": secret, "grant_type": "authorization_code",
                                                      "redirect_uri": redirect_uri, "code": code})
        long_ = await self.graph.http.get_json(f"{THREADS_HOST}/access_token",
                                               params={"grant_type": "th_exchange_token", "client_secret": secret, "access_token": short["access_token"]})
        return TokenSet(access_token=long_["access_token"], expires_at=self.expires_in(long_.get("expires_in", 60 * 86400)), scopes=list(SCOPES),
                        extra={"user_id": str(short.get("user_id"))})

    async def refresh(self, tokens: TokenSet) -> TokenSet:
        body = await self.graph.http.get_json(f"{THREADS_HOST}/refresh_access_token",
                                              params={"grant_type": "th_refresh_token", "access_token": tokens.access_token})
        return TokenSet(access_token=body["access_token"], expires_at=self.expires_in(body.get("expires_in", 60 * 86400)), scopes=tokens.scopes,
                        extra=dict(tokens.extra))

    def refresh_supported(self, tokens: TokenSet | None = None) -> bool:
        return True

    async def list_connectable_accounts(self, tokens: TokenSet, flavor: str = "default") -> list[ConnectableAccount]:
        me = await self.graph.get("/me", tokens.access_token, {"fields": "id,username,name,threads_profile_picture_url"})
        return [ConnectableAccount(external_id=str(me["id"]), display_name=me.get("name") or me.get("username") or me["id"],
                                   handle=me.get("username"), avatar_url=me.get("threads_profile_picture_url"), account_type="profile")]

    async def probe(self, account: Any, tokens: TokenSet) -> dict[str, Any]:
        uid = account_attr(account, "external_id")
        aid = account_attr(account, "id")
        required = {"threads_basic", "threads_content_publish"}
        granted = set(tokens.scopes or account_attr(account, "scopes", []) or [])
        health: dict[str, Any] = {"token_valid": False, "scopes_missing": sorted(required - granted) if granted else [],
                                  "limits_remaining": None, "expires_at": tokens.expires_at.isoformat() if tokens.expires_at else None,
                                  "refreshable": True, "profile_discovery": "threads_profile_discovery" in granted,
                                  "keyword_search": "threads_keyword_search" in granted}
        try:
            await self.graph.get(f"/{uid}", tokens.access_token, {"fields": "id,username"}, account_id=aid)
            health["token_valid"] = True
        except PublishError as e:
            health["error"] = {"category": e.category, "code": e.code, "message": e.message}
            if e.category != "auth":
                raise
            return health
        try:
            lim = await self.graph.get(f"/{uid}/threads_publishing_limit", tokens.access_token, {"fields": "quota_usage,config"}, account_id=aid)
            data = (lim.get("data") or [{}])[0]
            usage = data.get("quota_usage")
            total = (data.get("config") or {}).get("quota_total", POSTS_PER_24H)
            health["publishing_quota_usage"] = usage
            health["limits_remaining"] = {"posts_24h": (total - usage) if usage is not None else None, "posts_24h_total": total}
        except PublishError as e:
            health["limits_error"] = {"category": e.category, "code": e.code}
        return health

    # ---- validation --------------------------------------------------------------------------------------
    async def validate_content(self, account: Any, req: PublishRequest) -> ValidationResult:
        issues = []
        segments = self._segments(req)
        for i, seg in enumerate(segments):
            n = threads_length(seg)
            if n > TEXT_MAX_BYTES:
                issues.append(issue("threads_text_too_long", f"segment {i + 1} is {n}/{TEXT_MAX_BYTES} (emojis count as UTF-8 bytes)",
                                    f"segments[{i}]" if req.segments else "text"))
            if len(find_urls(seg)) > LINKS_MAX:
                issues.append(issue("threads_too_many_links", f"at most {LINKS_MAX} links", f"segments[{i}]" if req.segments else "text"))
        images, videos, docs = self._media_kinds(req)
        if docs:
            issues.append(issue("threads_unsupported_media", "only images and videos are supported", "media"))
        if len(req.media) > 1 and not CAROUSEL_RANGE[0] <= len(req.media) <= CAROUSEL_RANGE[1]:
            issues.append(issue("threads_carousel_count", f"carousels need {CAROUSEL_RANGE[0]}–{CAROUSEL_RANGE[1]} items", "media"))
        if not (req.text or "").strip() and not req.media:
            issues.append(issue("empty_post", "post needs text or media", "text"))
        for i, m in enumerate(req.media):
            info = media_info(req, i)
            if not m.url:
                issues.append(issue("threads_requires_public_media_url", "Threads fetches media from a public URL", f"media[{i}]"))
            if m in images:
                if (m.mime or "").lower() not in ("image/jpeg", "image/png"):
                    issues.append(issue("threads_image_format", "images must be JPEG or PNG", f"media[{i}]"))
                if (info.get("bytes") or 0) > 8 * 1024**2:
                    issues.append(issue("threads_image_too_large", "image exceeds 8 MB", f"media[{i}]"))
                if not (m.alt_text or info.get("alt_text")):
                    issues.append(issue("alt_text_missing", "image has no alt text", f"media[{i}]", "warning"))
            if m in videos:
                if (info.get("duration_ms") or 0) > 300_000:
                    issues.append(issue("threads_video_too_long", "videos must be ≤ 5 minutes", f"media[{i}]"))
                if (info.get("bytes") or 0) > 1024**3:
                    issues.append(issue("threads_video_too_large", "video exceeds 1 GB", f"media[{i}]"))
        usage = (account_attr(account, "health", {}) or {}).get("publishing_quota_usage")
        if usage is not None:
            if usage >= POSTS_PER_24H:
                issues.append(issue("threads_daily_limit_reached", f"{usage}/{POSTS_PER_24H} API posts used in 24 h", "account"))
            elif usage >= POSTS_PER_24H * 0.9:
                issues.append(issue("threads_daily_limit_near", f"{usage}/{POSTS_PER_24H} API posts used in 24 h", "account", "warning"))
        return result(issues)

    # ---- publish -----------------------------------------------------------------------------------------
    async def publish(self, account: Any, tokens: TokenSet, req: PublishRequest, state: dict[str, Any]) -> PublishResult:
        uid = account_attr(account, "external_id")
        aid = account_attr(account, "id")
        token = tokens.access_token
        segments = self._segments(req)
        done: list[str] = state.setdefault("segment_external_ids", [])
        for i, seg in enumerate(segments):
            if i < len(done):
                continue
            reply_to = done[i - 1] if i > 0 else None
            media = req.media if i == 0 else []
            creation_key = f"creation_id_{i}"
            if not state.get(creation_key):
                for m in media:
                    if not m.url:
                        raise PublishError("validation", "threads_requires_public_media_url", code="threads_requires_public_media_url")
                cid = await self._create_container(uid, token, seg, media, reply_to, req, state, aid)
                state[creation_key] = cid
                state["creation_id"] = cid
                state["media_created_at"] = self.now().isoformat()
                await save_state(state)
            if media:
                await self._wait_media(uid, token, state[creation_key], state, aid)
            pub = await self.graph.post(f"/{uid}/threads_publish", token, {"creation_id": state[creation_key]}, account_id=aid)
            pid = str(pub.get("id") or "")
            if not pid:
                raise PublishError("ambiguous", "threads_publish returned no id", code="no_post_id", raw=pub)
            done.append(pid)
            state["segment_external_ids"] = done
            await save_state(state)
        first = done[0]
        url = None
        try:
            body = await self.graph.get(f"/{first}", token, {"fields": "permalink"}, account_id=aid)
            url = body.get("permalink")
        except PublishError:
            pass
        return PublishResult(external_id=first, external_url=url, published_at=self.now(),
                             segments=[{"index": i, "external_id": pid} for i, pid in enumerate(done)], raw={"segments": len(done)})

    async def _create_container(self, uid: str, token: str, text: str, media: list, reply_to: str | None, req: PublishRequest,
                                state: dict[str, Any], aid: Any) -> str:
        base: dict[str, Any] = {"text": text}
        if reply_to:
            base["reply_to_id"] = reply_to
        if req.metadata.get("topic_tag"):
            base["topic_tag"] = req.metadata["topic_tag"]
        if req.metadata.get("reply_control"):
            base["reply_control"] = req.metadata["reply_control"]
        if not media:
            data = {**base, "media_type": "TEXT"}
            if req.metadata.get("link"):
                data["link_attachment"] = req.metadata["link"]
            body = await self.graph.post(f"/{uid}/threads", token, data, account_id=aid)
            return str(body["id"])
        if len(media) == 1:
            m = media[0]
            is_video = (m.mime or "").startswith("video/")
            data = {**base, "media_type": "VIDEO" if is_video else "IMAGE", ("video_url" if is_video else "image_url"): m.url}
            if m.alt_text:
                data["alt_text"] = m.alt_text
            body = await self.graph.post(f"/{uid}/threads", token, data, account_id=aid)
            return str(body["id"])
        children: list[str] = state.setdefault("child_ids", [])
        for i, m in enumerate(media[:CAROUSEL_RANGE[1]]):
            if i < len(children):
                continue
            is_video = (m.mime or "").startswith("video/")
            data = {"media_type": "VIDEO" if is_video else "IMAGE", ("video_url" if is_video else "image_url"): m.url, "is_carousel_item": "true"}
            if m.alt_text:
                data["alt_text"] = m.alt_text
            body = await self.graph.post(f"/{uid}/threads", token, data, account_id=aid)
            children.append(str(body["id"]))
            await save_state(state)
            await heartbeat(state)
        state["media_created_at"] = self.now().isoformat()
        for cid in children:
            await self._wait_media(uid, token, cid, state, aid)
        body = await self.graph.post(f"/{uid}/threads", token, {**base, "media_type": "CAROUSEL", "children": ",".join(children)}, account_id=aid)
        return str(body["id"])

    async def _wait_media(self, uid: str, token: str, container_id: str, state: dict[str, Any], aid: Any) -> None:
        """Meta recommends waiting ~30 s before publishing media; poll ``status`` until FINISHED."""
        created = state.get("media_created_at")
        if created:
            elapsed = (self.now() - datetime.fromisoformat(created)).total_seconds()
            if elapsed < MEDIA_WAIT_S:
                await asyncio.sleep(MEDIA_WAIT_S - elapsed)
        deadline = asyncio.get_event_loop().time() + 600
        while True:
            body = await self.graph.get(f"/{container_id}", token, {"fields": "status,error_message"}, account_id=aid)
            status = body.get("status")
            if status in ("FINISHED", "PUBLISHED"):
                return
            if status == "ERROR":
                raise PublishError("validation", f"container failed: {body.get('error_message')}", code="container_error", raw=body)
            if status == "EXPIRED":
                raise PublishError("permanent", "container expired", code="container_expired", raw=body)
            if asyncio.get_event_loop().time() > deadline:
                raise PublishError("transient", "container still processing after 10 minutes", code="container_timeout", raw=body)
            await heartbeat(state)
            await asyncio.sleep(5)

    async def get_status(self, account: Any, tokens: TokenSet, state: dict[str, Any]) -> dict[str, Any] | None:
        done = state.get("segment_external_ids") or []
        if done:
            return {"status": "published", "external_id": done[0], "partial": True}
        if not state.get("creation_id"):
            return None
        try:
            body = await self.graph.get(f"/{state['creation_id']}", tokens.access_token, {"fields": "status,error_message"},
                                        account_id=account_attr(account, "id"))
        except PublishError:
            return None
        st = body.get("status")
        if st == "PUBLISHED":
            return {"status": "published_unknown_id"}
        if st in ("FINISHED", "IN_PROGRESS"):
            return {"status": "pending"}
        return {"status": "failed", "message": body.get("error_message")}

    # ---- reads / delete ----------------------------------------------------------------------------------
    async def get_post(self, account: Any, tokens: TokenSet, external_id: str) -> RemotePost:
        body = await self.graph.get(f"/{external_id}", tokens.access_token, {"fields": "id,text,timestamp,permalink,media_type"},
                                    account_id=account_attr(account, "id"))
        return RemotePost(external_id=body.get("id", external_id), text=body.get("text"), created_at=_iso(body.get("timestamp")),
                          url=body.get("permalink"), raw=body)

    async def delete_post(self, account: Any, tokens: TokenSet, external_id: str) -> None:
        await self.graph.delete(f"/{external_id}", tokens.access_token, account_id=account_attr(account, "id"))

    async def find_recent_posts(self, account: Any, tokens: TokenSet, since: datetime) -> list[RemotePost]:
        uid = account_attr(account, "external_id")
        rows = await self.graph.get_all(f"/{uid}/threads", tokens.access_token,
                                        {"fields": "id,text,timestamp,permalink,media_type", "since": int(since.timestamp()), "limit": 25},
                                        limit=50, account_id=account_attr(account, "id"))
        return [RemotePost(external_id=r["id"], text=r.get("text"), created_at=_iso(r.get("timestamp")), url=r.get("permalink"), raw=r) for r in rows]

    # ---- metrics -----------------------------------------------------------------------------------------
    async def get_post_metrics(self, account: Any, tokens: TokenSet, external_id: str) -> dict[str, Any]:
        from app.analytics.normalize import normalize_post_metrics
        aid = account_attr(account, "id")
        raw: dict[str, Any] = {"insights": {}, "errors": {}}
        try:
            ins = await self.graph.get(f"/{external_id}/insights", tokens.access_token, {"metric": MEDIA_INSIGHTS}, account_id=aid)
            raw["insights"] = insights_to_dict(ins)
        except PublishError as e:
            if e.category == "auth":
                raise
            raw["errors"]["insights"] = {"category": e.category, "code": e.code}
            for metric in MEDIA_INSIGHTS.split(","):
                try:
                    ins = await self.graph.get(f"/{external_id}/insights", tokens.access_token, {"metric": metric}, account_id=aid)
                    raw["insights"].update(insights_to_dict(ins))
                except PublishError as e2:
                    raw["errors"][metric] = e2.code
        return normalize_post_metrics("threads", raw)

    async def get_account_metrics(self, account: Any, tokens: TokenSet) -> dict[str, Any]:
        from app.analytics.normalize import normalize_account_metrics
        uid = account_attr(account, "external_id")
        aid = account_attr(account, "id")
        raw: dict[str, Any] = {"insights": {}}
        try:
            ins = await self.graph.get(f"/{uid}/threads_insights", tokens.access_token, {"metric": ACCOUNT_INSIGHTS}, account_id=aid)
            raw["insights"] = insights_to_dict(ins)
        except PublishError as e:
            if e.category == "auth":
                raise
            raw["error"] = {"category": e.category, "code": e.code}
        return normalize_account_metrics("threads", raw)

    async def get_public_profile(self, account: Any, tokens: TokenSet, username: str) -> dict[str, Any]:
        granted = set(tokens.scopes or account_attr(account, "scopes", []) or [])
        if "threads_profile_discovery" not in granted:
            raise PublishError("unsupported", "profile lookup requires the approved threads_profile_discovery permission", code="permission_required")
        body = await self.graph.get("/profile_lookup", tokens.access_token, {"username": username}, account_id=account_attr(account, "id"))
        return {**body, "availability": "official_api"}

    async def keyword_search(self, account: Any, tokens: TokenSet, q: str, search_type: str = "TOP", limit: int = 25) -> list[dict[str, Any]]:
        granted = set(tokens.scopes or account_attr(account, "scopes", []) or [])
        if "threads_keyword_search" not in granted:
            raise PublishError("unsupported", "keyword search requires the approved threads_keyword_search permission", code="permission_required")
        body = await self.graph.get("/keyword_search", tokens.access_token,
                                    {"q": q, "search_type": search_type, "limit": min(limit, 100), "fields": "id,text,media_type,permalink,timestamp,username"},
                                    account_id=account_attr(account, "id"))
        return body.get("data", [])

    def rate_limits(self) -> list[dict[str, Any]]:
        return [{"scope": "posts", "limit": POSTS_PER_24H, "window_s": 86400}, {"scope": "replies", "limit": 1000, "window_s": 86400},
                {"scope": "deletes", "limit": 100, "window_s": 86400}]


def _iso(v: Any) -> datetime | None:
    if not v:
        return None
    try:
        return datetime.strptime(str(v), "%Y-%m-%dT%H:%M:%S%z").astimezone(UTC)
    except ValueError:
        try:
            return datetime.fromisoformat(str(v).replace("Z", "+00:00"))
        except ValueError:
            return None

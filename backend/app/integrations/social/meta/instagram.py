"""Instagram Professional adapter (doc 27 §27.2, docs/platforms/meta-facebook-instagram-threads.md §2). VERIFIED_AT 2026-10-08.

Two auth flavors with the same publish flow:
* ``facebook_login`` (default): Facebook Login, IG accounts discovered via ``/{page}?fields=instagram_business_account``,
  Page token used for all calls (graph.facebook.com). Unlocks Business Discovery (``get_public_profile``).
* ``instagram_login``: ``instagram.com/oauth/authorize`` with ``instagram_business_*`` scopes, graph.instagram.com host,
  long-lived 60-day tokens refreshed with ``ig_refresh_token``.
Publishing is the container flow: ``POST /{ig}/media`` (image_url / video_url + media_type=REELS|STORIES / carousel
children) → poll ``status_code`` → ``POST /{ig}/media_publish``. ``state["creation_id"]`` lets a retry resume.
Media must be on a **public URL** (JPEG only for images, aspect 4:5–1.91:1). 100 API posts / 24 h
(``content_publishing_limit``), containers expire after 24 h (never pre-created).
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
    heartbeat,
    issue,
    media_info,
    result,
    save_state,
)
from app.integrations.social.meta.client import GRAPH_HOST, IG_HOST, MetaGraphClient, insights_to_dict

VERIFIED_AT = "2026-10-08"
FB_SCOPES = ["instagram_basic", "instagram_content_publish", "instagram_manage_insights", "instagram_manage_comments",
             "instagram_manage_contents", "pages_show_list", "pages_read_engagement", "business_management"]
IG_SCOPES = ["instagram_business_basic", "instagram_business_content_publish", "instagram_business_manage_insights",
             "instagram_business_manage_comments"]
POSTS_PER_24H = 100
CONTAINERS_PER_24H = 400
CAPTION_MAX = 2200
HASHTAG_MAX = 30
CAROUSEL_MAX = 10
MIN_ASPECT, MAX_ASPECT = 0.8, 1.91
MEDIA_INSIGHTS = {"FEED": "views,reach,likes,comments,saved,shares,total_interactions",
                  "REELS": "views,reach,likes,comments,saved,shares,total_interactions,ig_reels_avg_watch_time,ig_reels_video_view_total_time,reels_skip_rate",
                  "STORY": "views,reach,replies,shares,total_interactions,navigation,link_clicks"}
ACCOUNT_INSIGHTS = "reach,views,accounts_engaged,total_interactions,profile_links_taps"


def _ig_app() -> tuple[str, str]:
    return (getattr(settings, "instagram_app_id", "") or settings.meta_app_id, getattr(settings, "instagram_app_secret", "") or settings.meta_app_secret)


class InstagramAdapter(BaseAdapter):
    platform = "instagram"
    verified_at = VERIFIED_AT
    VERIFIED_AT = VERIFIED_AT
    docs = ["https://developers.facebook.com/docs/instagram-platform/content-publishing",
            "https://developers.facebook.com/docs/instagram-platform/instagram-api-with-instagram-login",
            "https://developers.facebook.com/docs/instagram-platform/reference/instagram-media/insights"]

    def __init__(self) -> None:
        super().__init__()
        self.fb = MetaGraphClient("instagram", GRAPH_HOST)
        self.ig = MetaGraphClient("instagram", IG_HOST)
        self.ig.app_secret = ""   # appsecret_proof is a graph.facebook.com feature

    # ---- flavor helpers ----------------------------------------------------------------------------------
    @staticmethod
    def _flavor(account: Any) -> str:
        f = account_attr(account, "auth_flavor", "facebook_login") or "facebook_login"
        return "instagram_login" if f == "instagram_login" else "facebook_login"

    def _client(self, account: Any) -> MetaGraphClient:
        return self.ig if self._flavor(account) == "instagram_login" else self.fb

    def _token(self, account: Any, tokens: TokenSet) -> str:
        if self._flavor(account) == "facebook_login":
            return tokens.extra.get("page_token") or tokens.access_token
        return tokens.access_token

    def capabilities(self, account: Any) -> Capabilities:
        flavor = self._flavor(account) if account is not None else "facebook_login"
        return Capabilities(
            formats=["image", "carousel", "video", "short_video", "story"],
            max_text=CAPTION_MAX, max_media=CAROUSEL_MAX, native_schedule=False, can_delete=True, supports_alt_text=True,
            limits={"posts_per_24h": POSTS_PER_24H, "containers_per_24h": CONTAINERS_PER_24H, "hashtags": HASHTAG_MAX,
                    "image_formats": ["image/jpeg"], "image_aspect": [MIN_ASPECT, MAX_ASPECT], "image_max_bytes": 8 * 1024**2,
                    "reels_duration_s": [3, 900], "reels_max_bytes": 300 * 1024**2, "story_video_s": [3, 60],
                    "story_max_bytes": 100 * 1024**2, "collaborators": 3, "token_lifetime_days": 60},
            notes=[f"flavor={flavor}", "public media URL required (PUBLIC_MEDIA_BASE_URL)", "no text-only posts", "JPEG only",
                   "alt text images only", "Business Discovery/Hashtag Search only via facebook_login",
                   "impressions removed Apr 2025 → views"],
        )

    # ---- OAuth -------------------------------------------------------------------------------------------
    def auth_url(self, state: str, redirect_uri: str, flavor: str = "facebook_login", code_challenge: str | None = None) -> str:
        if flavor == "instagram_login":
            app_id, _ = _ig_app()
            q = {"client_id": app_id, "redirect_uri": redirect_uri, "scope": ",".join(IG_SCOPES), "response_type": "code", "state": state,
                 "enable_fb_login": "0", "force_reauth": "true"}
            return f"https://www.instagram.com/oauth/authorize?{urlencode(q)}"
        q = {"client_id": settings.meta_app_id, "redirect_uri": redirect_uri, "state": state, "scope": ",".join(FB_SCOPES), "response_type": "code"}
        return f"https://www.facebook.com/{settings.meta_graph_version}/dialog/oauth?{urlencode(q)}"

    async def exchange_code(self, code: str, redirect_uri: str, code_verifier: str | None = None) -> TokenSet:
        # flavor is carried through ``code_verifier`` convention: "flavor:instagram_login" (no PKCE on Meta)
        if code_verifier == "flavor:instagram_login":
            return await self._exchange_instagram_login(code, redirect_uri)
        short = await self.fb.get("/oauth/access_token", None, {"client_id": settings.meta_app_id, "client_secret": settings.meta_app_secret,
                                                               "redirect_uri": redirect_uri, "code": code})
        body = await self.fb.get("/oauth/access_token", None, {"grant_type": "fb_exchange_token", "client_id": settings.meta_app_id,
                                                              "client_secret": settings.meta_app_secret, "fb_exchange_token": short["access_token"]})
        me = await self.fb.get("/me", body["access_token"], {"fields": "id,name"})
        perms = await self.fb.get("/me/permissions", body["access_token"])
        scopes = [p["permission"] for p in perms.get("data", []) if p.get("status") == "granted"]
        return TokenSet(access_token=body["access_token"], expires_at=self.expires_in(body.get("expires_in", 60 * 86400)), scopes=scopes,
                        extra={"user_id": me.get("id"), "flavor": "facebook_login"})

    async def _exchange_instagram_login(self, code: str, redirect_uri: str) -> TokenSet:
        app_id, secret = _ig_app()
        short = await self.ig.http.post_json("https://api.instagram.com/oauth/access_token",
                                             data={"client_id": app_id, "client_secret": secret, "grant_type": "authorization_code",
                                                   "redirect_uri": redirect_uri, "code": code})
        long_ = await self.ig.http.get_json(f"{IG_HOST}/access_token", params={"grant_type": "ig_exchange_token", "client_secret": secret,
                                                                              "access_token": short["access_token"]})
        perms = short.get("permissions") or []
        if isinstance(perms, str):
            perms = perms.split(",")
        return TokenSet(access_token=long_["access_token"], expires_at=self.expires_in(long_.get("expires_in", 60 * 86400)), scopes=perms,
                        extra={"user_id": str(short.get("user_id")), "flavor": "instagram_login"})

    async def refresh(self, tokens: TokenSet) -> TokenSet:
        if tokens.extra.get("flavor") == "instagram_login":
            body = await self.ig.http.get_json(f"{IG_HOST}/refresh_access_token", params={"grant_type": "ig_refresh_token",
                                                                                         "access_token": tokens.access_token})
            return TokenSet(access_token=body["access_token"], expires_at=self.expires_in(body.get("expires_in", 60 * 86400)),
                            scopes=tokens.scopes, extra=dict(tokens.extra))
        body = await self.fb.get("/oauth/access_token", None, {"grant_type": "fb_exchange_token", "client_id": settings.meta_app_id,
                                                              "client_secret": settings.meta_app_secret, "fb_exchange_token": tokens.access_token})
        ts = TokenSet(access_token=body["access_token"], expires_at=self.expires_in(body.get("expires_in", 60 * 86400)), scopes=tokens.scopes,
                      extra=dict(tokens.extra))
        page_id = tokens.extra.get("page_id")
        if page_id:
            pages = await self.fb.get("/me/accounts", ts.access_token, {"fields": "id,access_token"})
            for p in pages.get("data", []):
                if str(p.get("id")) == str(page_id):
                    ts.extra.update({"page_token": p["access_token"], "page_id": page_id})
        return ts

    def refresh_supported(self, tokens: TokenSet | None = None) -> bool:
        return True

    async def list_connectable_accounts(self, tokens: TokenSet, flavor: str = "facebook_login") -> list[ConnectableAccount]:
        if flavor == "instagram_login" or tokens.extra.get("flavor") == "instagram_login":
            me = await self.ig.get("/me", tokens.access_token, {"fields": "user_id,username,name,profile_picture_url,followers_count,account_type"})
            ext = str(me.get("user_id") or me.get("id"))
            return [ConnectableAccount(external_id=ext, display_name=me.get("name") or me.get("username") or ext, handle=me.get("username"),
                                       avatar_url=me.get("profile_picture_url"), account_type=(me.get("account_type") or "professional").lower(),
                                       extra={"followers_count": me.get("followers_count"), "flavor": "instagram_login"})]
        pages = await self.fb.get_all("/me/accounts", tokens.access_token,
                                      {"fields": "id,name,access_token,instagram_business_account{id,username,name,profile_picture_url,followers_count}"})
        out = []
        for p in pages:
            ig = p.get("instagram_business_account")
            if not ig:
                continue
            out.append(ConnectableAccount(external_id=str(ig["id"]), display_name=ig.get("name") or ig.get("username") or ig["id"],
                                          handle=ig.get("username"), avatar_url=ig.get("profile_picture_url"), account_type="professional",
                                          parent_external_id=str(p["id"]),
                                          extra={"page_token": p.get("access_token"), "page_id": str(p["id"]), "page_name": p.get("name"),
                                                 "followers_count": ig.get("followers_count"), "flavor": "facebook_login"}))
        return out

    async def probe(self, account: Any, tokens: TokenSet) -> dict[str, Any]:
        flavor = self._flavor(account)
        ig_id = account_attr(account, "external_id")
        aid = account_attr(account, "id")
        client, token = self._client(account), self._token(account, tokens)
        required = {"instagram_business_content_publish"} if flavor == "instagram_login" else {"instagram_content_publish", "instagram_basic"}
        granted = set(tokens.scopes or account_attr(account, "scopes", []) or [])
        health: dict[str, Any] = {"token_valid": False, "scopes_missing": sorted(required - granted) if granted else [],
                                  "limits_remaining": None, "expires_at": tokens.expires_at.isoformat() if tokens.expires_at else None,
                                  "refreshable": True, "flavor": flavor}
        try:
            me = await client.get(f"/{ig_id}", token, {"fields": "id,username,followers_count,media_count"}, account_id=aid)
            health["token_valid"] = True
            health["followers"] = me.get("followers_count")
        except PublishError as e:
            health["error"] = {"category": e.category, "code": e.code, "message": e.message}
            if e.category != "auth":
                raise
            return health
        try:
            lim = await client.get(f"/{ig_id}/content_publishing_limit", token, {"fields": "quota_usage,config"}, account_id=aid)
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
        fmt = req.metadata.get("format") or ("carousel" if len(req.media) > 1 else "image")
        text = req.text or ""
        if not req.media:
            issues.append(issue("instagram_media_required", "Instagram posts need an image or a video (no text-only posts)", "media"))
        if len(text) > CAPTION_MAX:
            issues.append(issue("instagram_caption_too_long", f"caption is {len(text)}/{CAPTION_MAX} characters", "text"))
        if text.count("#") > HASHTAG_MAX:
            issues.append(issue("instagram_too_many_hashtags", f"more than {HASHTAG_MAX} hashtags", "text"))
        if text.count("@") > 20:
            issues.append(issue("instagram_too_many_mentions", "more than 20 @-tags", "text"))
        images, videos, docs = self._media_kinds(req)
        if docs:
            issues.append(issue("instagram_unsupported_media", "only JPEG images and MP4/MOV videos are supported", "media"))
        if fmt == "carousel" or len(req.media) > 1:
            if not 2 <= len(req.media) <= CAROUSEL_MAX:
                issues.append(issue("instagram_carousel_count", f"carousels need 2–{CAROUSEL_MAX} items", "media"))
        for i, m in enumerate(req.media):
            info = media_info(req, i)
            if not m.url:
                issues.append(issue("instagram_requires_public_media_url", "Instagram fetches media from a public URL; configure PUBLIC_MEDIA_BASE_URL or a tunnel",
                                    f"media[{i}]"))
            if m in images:
                if (m.mime or "").lower() != "image/jpeg":
                    issues.append(issue("instagram_jpeg_only", "Instagram accepts JPEG images only", f"media[{i}]"))
                w, h = info.get("width"), info.get("height")
                if w and h and fmt not in ("story", "short_video") and not (MIN_ASPECT - 0.005 <= w / h <= MAX_ASPECT + 0.005):
                    issues.append(issue("instagram_aspect_ratio", f"image aspect {w}:{h} must be between 4:5 and 1.91:1", f"media[{i}]"))
                if (info.get("bytes") or 0) > 8 * 1024**2:
                    issues.append(issue("instagram_image_too_large", "image exceeds 8 MB", f"media[{i}]"))
                if w and (w < 320 or w > 1440):
                    issues.append(issue("instagram_image_width", "image width must be 320–1440 px", f"media[{i}]", "warning"))
            if m in videos:
                dur = (info.get("duration_ms") or 0) / 1000
                size = info.get("bytes") or 0
                if fmt == "story":
                    if dur and not 3 <= dur <= 60:
                        issues.append(issue("instagram_story_duration", "story videos must be 3–60 s", f"media[{i}]"))
                    if size > 100 * 1024**2:
                        issues.append(issue("instagram_story_too_large", "story video exceeds 100 MB", f"media[{i}]"))
                else:
                    if dur and not 3 <= dur <= 900:
                        issues.append(issue("instagram_reel_duration", "Reels must be 3 s – 15 min", f"media[{i}]"))
                    if size > 300 * 1024**2:
                        issues.append(issue("instagram_reel_too_large", "Reel exceeds 300 MB", f"media[{i}]"))
            if m in images and fmt not in ("story", "short_video") and not (m.alt_text or info.get("alt_text")):
                issues.append(issue("alt_text_missing", "image has no alt text", f"media[{i}]", "warning"))
        health = account_attr(account, "health", {}) or {}
        usage = health.get("publishing_quota_usage")
        if usage is not None:
            if usage >= POSTS_PER_24H:
                issues.append(issue("instagram_daily_limit_reached", f"{usage}/{POSTS_PER_24H} API posts used in the last 24 h", "account"))
            elif usage >= POSTS_PER_24H * 0.9:
                issues.append(issue("ig_daily_limit_near", f"{usage}/{POSTS_PER_24H} API posts used in 24h", "account", "warning"))
        if req.metadata.get("collaborators") and len(req.metadata["collaborators"]) > 3:
            issues.append(issue("instagram_collaborators", "at most 3 collaborators", "collaborators"))
        return result(issues)

    # ---- publish (container flow) -----------------------------------------------------------------------
    async def publish(self, account: Any, tokens: TokenSet, req: PublishRequest, state: dict[str, Any]) -> PublishResult:
        if state.get("media_id"):
            return await self._result(account, tokens, state["media_id"], state.get("published_at"))
        client, token = self._client(account), self._token(account, tokens)
        ig_id = account_attr(account, "external_id")
        aid = account_attr(account, "id")
        fmt = req.metadata.get("format") or ("carousel" if len(req.media) > 1 else "image")
        for m in req.media:
            if not m.url:
                raise PublishError("validation", "instagram_requires_public_media_url", code="instagram_requires_public_media_url")
        if not state.get("creation_id"):
            caption = req.text or ""
            common: dict[str, Any] = {}
            if req.metadata.get("is_ai_generated") is not None:
                common["is_ai_generated"] = "true" if req.metadata["is_ai_generated"] else "false"
            if req.metadata.get("location_id"):
                common["location_id"] = req.metadata["location_id"]
            if req.metadata.get("collaborators"):
                common["collaborators"] = ",".join(req.metadata["collaborators"][:3])
            if fmt == "carousel" or len(req.media) > 1:
                children: list[str] = state.setdefault("child_ids", [])
                for i, m in enumerate(req.media[:CAROUSEL_MAX]):
                    if i < len(children):
                        continue
                    data = {"is_carousel_item": "true"}
                    if (m.mime or "").startswith("video/"):
                        data.update({"media_type": "VIDEO", "video_url": m.url})
                    else:
                        data["image_url"] = m.url
                        if m.alt_text:
                            data["alt_text"] = m.alt_text
                    body = await client.post(f"/{ig_id}/media", token, data, account_id=aid)
                    children.append(str(body["id"]))
                    await save_state(state)
                    await heartbeat(state)
                for cid in children:
                    await self._wait_container(client, token, cid, state, aid)
                body = await client.post(f"/{ig_id}/media", token, {"media_type": "CAROUSEL", "children": ",".join(children), "caption": caption, **common},
                                         account_id=aid)
            else:
                m = req.media[0]
                is_video = (m.mime or "").startswith("video/")
                if fmt == "story":
                    data = {"media_type": "STORIES", ("video_url" if is_video else "image_url"): m.url}
                elif is_video:
                    data = {"media_type": "REELS", "video_url": m.url, "caption": caption,
                            "share_to_feed": "true" if req.metadata.get("share_to_feed", True) else "false"}
                    if req.metadata.get("cover_url"):
                        data["cover_url"] = req.metadata["cover_url"]
                else:
                    data = {"image_url": m.url, "caption": caption}
                    if m.alt_text:
                        data["alt_text"] = m.alt_text
                body = await client.post(f"/{ig_id}/media", token, {**data, **common}, account_id=aid)
            state["creation_id"] = str(body["id"])
            await save_state(state)
        await self._wait_container(client, token, state["creation_id"], state, aid)
        pub = await client.post(f"/{ig_id}/media_publish", token, {"creation_id": state["creation_id"]}, account_id=aid)
        media_id = str(pub.get("id") or "")
        if not media_id:
            raise PublishError("ambiguous", "media_publish returned no id", code="no_post_id", raw=pub)
        state["media_id"] = media_id
        state["published_at"] = self.now().isoformat()
        await save_state(state)
        return await self._result(account, tokens, media_id, state["published_at"])

    async def _wait_container(self, client: MetaGraphClient, token: str, container_id: str, state: dict[str, Any], aid: Any) -> None:
        deadline = asyncio.get_event_loop().time() + 600
        while True:
            body = await client.get(f"/{container_id}", token, {"fields": "status_code,status"}, account_id=aid)
            code = body.get("status_code")
            if code in ("FINISHED", "PUBLISHED"):
                return
            if code == "ERROR":
                raise PublishError("validation", f"container failed: {body.get('status')}", code="container_error", raw=body)
            if code == "EXPIRED":
                raise PublishError("permanent", "container expired (not published within 24 h)", code="container_expired", raw=body)
            if asyncio.get_event_loop().time() > deadline:
                raise PublishError("transient", "container still processing after 10 minutes", code="container_timeout", raw=body)
            await heartbeat(state)
            await asyncio.sleep(3)

    async def get_status(self, account: Any, tokens: TokenSet, state: dict[str, Any]) -> dict[str, Any] | None:
        if state.get("media_id"):
            return {"status": "published", "external_id": state["media_id"]}
        cid = state.get("creation_id")
        if not cid:
            return None
        try:
            body = await self._client(account).get(f"/{cid}", self._token(account, tokens), {"fields": "status_code,status"},
                                                   account_id=account_attr(account, "id"))
        except PublishError:
            return None
        code = body.get("status_code")
        if code == "PUBLISHED":
            return {"status": "published_unknown_id"}   # container published; the media id must be found via find_recent_posts
        if code in ("FINISHED", "IN_PROGRESS"):
            return {"status": "pending"}
        return {"status": "failed", "message": body.get("status")}

    async def _result(self, account: Any, tokens: TokenSet, media_id: str, published_at: str | None) -> PublishResult:
        url = None
        try:
            body = await self._client(account).get(f"/{media_id}", self._token(account, tokens), {"fields": "permalink"},
                                                   account_id=account_attr(account, "id"))
            url = body.get("permalink")
        except PublishError:
            pass
        at = datetime.fromisoformat(published_at) if published_at else self.now()
        return PublishResult(external_id=media_id, external_url=url, published_at=at, raw={"id": media_id})

    # ---- reads / delete ----------------------------------------------------------------------------------
    async def get_post(self, account: Any, tokens: TokenSet, external_id: str) -> RemotePost:
        body = await self._client(account).get(f"/{external_id}", self._token(account, tokens),
                                               {"fields": "id,caption,timestamp,permalink,media_type"}, account_id=account_attr(account, "id"))
        return RemotePost(external_id=body.get("id", external_id), text=body.get("caption"), created_at=_iso(body.get("timestamp")),
                          url=body.get("permalink"), raw=body)

    async def delete_post(self, account: Any, tokens: TokenSet, external_id: str) -> None:
        await self._client(account).delete(f"/{external_id}", self._token(account, tokens), account_id=account_attr(account, "id"))

    async def find_recent_posts(self, account: Any, tokens: TokenSet, since: datetime) -> list[RemotePost]:
        rows = await self._client(account).get_all(f"/{account_attr(account, 'external_id')}/media", self._token(account, tokens),
                                                   {"fields": "id,caption,timestamp,permalink,media_type", "limit": 25}, limit=50,
                                                   account_id=account_attr(account, "id"))
        out = []
        for r in rows:
            ts = _iso(r.get("timestamp"))
            if ts and ts < since:
                continue
            out.append(RemotePost(external_id=r["id"], text=r.get("caption"), created_at=ts, url=r.get("permalink"), raw=r))
        return out

    # ---- metrics -----------------------------------------------------------------------------------------
    async def get_post_metrics(self, account: Any, tokens: TokenSet, external_id: str) -> dict[str, Any]:
        from app.analytics.normalize import normalize_post_metrics
        client, token = self._client(account), self._token(account, tokens)
        aid = account_attr(account, "id")
        raw: dict[str, Any] = {"insights": {}, "fields": {}, "errors": {}}
        try:
            fields = await client.get(f"/{external_id}", token, {"fields": "id,media_type,media_product_type,like_count,comments_count,timestamp"},
                                      account_id=aid)
            raw["fields"] = fields
        except PublishError as e:
            if e.category == "auth":
                raise
            raw["errors"]["fields"] = {"category": e.category, "code": e.code}
            fields = {}
        product = (fields.get("media_product_type") or "FEED").upper()
        metrics = MEDIA_INSIGHTS.get(product, MEDIA_INSIGHTS["FEED"])
        try:
            ins = await client.get(f"/{external_id}/insights", token, {"metric": metrics}, account_id=aid)
            raw["insights"] = insights_to_dict(ins)
        except PublishError as e:
            if e.category == "auth":
                raise
            raw["errors"]["insights"] = {"category": e.category, "code": e.code}
            for metric in metrics.split(","):
                try:
                    ins = await client.get(f"/{external_id}/insights", token, {"metric": metric}, account_id=aid)
                    raw["insights"].update(insights_to_dict(ins))
                except PublishError as e2:
                    raw["errors"][metric] = e2.code
        raw["media_product_type"] = product
        return normalize_post_metrics("instagram", raw, flavor=self._flavor(account))

    async def get_account_metrics(self, account: Any, tokens: TokenSet) -> dict[str, Any]:
        from app.analytics.normalize import normalize_account_metrics
        client, token = self._client(account), self._token(account, tokens)
        ig_id = account_attr(account, "external_id")
        aid = account_attr(account, "id")
        raw: dict[str, Any] = {"insights": {}}
        me = await client.get(f"/{ig_id}", token, {"fields": "followers_count,follows_count,media_count"}, account_id=aid)
        raw.update({k: me.get(k) for k in ("followers_count", "follows_count", "media_count")})
        try:
            ins = await client.get(f"/{ig_id}/insights", token, {"metric": ACCOUNT_INSIGHTS, "period": "day", "metric_type": "total_value"},
                                   account_id=aid)
            raw["insights"] = insights_to_dict(ins)
        except PublishError as e:
            if e.category == "auth":
                raise
            raw["error"] = {"category": e.category, "code": e.code}
        return normalize_account_metrics("instagram", raw, flavor=self._flavor(account))

    async def get_public_profile(self, account: Any, tokens: TokenSet, username: str) -> dict[str, Any]:
        """Business Discovery (facebook_login only): followers, media_count and recent media with like/comment counts."""
        if self._flavor(account) != "facebook_login":
            raise PublishError("unsupported", "Business Discovery is only available through the Facebook Login flavor", code="unsupported")
        ig_id = account_attr(account, "external_id")
        fields = (f"business_discovery.username({username}){{username,name,followers_count,media_count,"
                  "media.limit(25){id,caption,like_count,comments_count,timestamp,media_type,permalink,view_count}}")
        body = await self.fb.get(f"/{ig_id}", self._token(account, tokens), {"fields": fields}, account_id=account_attr(account, "id"))
        bd = body.get("business_discovery") or {}
        return {"username": bd.get("username"), "name": bd.get("name"), "followers": bd.get("followers_count"),
                "media_count": bd.get("media_count"), "media": (bd.get("media") or {}).get("data", []), "availability": "official_api"}

    def rate_limits(self) -> list[dict[str, Any]]:
        return [{"scope": "posts", "limit": POSTS_PER_24H, "window_s": 86400}, {"scope": "containers", "limit": CONTAINERS_PER_24H, "window_s": 86400},
                {"scope": "ig_buc", "limit": "4800 × impressions / 24 h"}]


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

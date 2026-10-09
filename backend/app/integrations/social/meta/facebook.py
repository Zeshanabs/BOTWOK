"""Facebook Page adapter (doc 27 §27.1, docs/platforms/meta-facebook-instagram-threads.md §1). VERIFIED_AT 2026-10-08.

Facebook Login → short-lived user token → long-lived (60 d) via ``fb_exchange_token`` → Page tokens from
``/me/accounts`` (stored as ``kind=page``; they do not expire). Publishing: ``/{page}/feed`` (text/link),
``/{page}/photos`` (single photo), ``/{page}/videos``, Reels (``/{page}/video_reels`` 3-phase) and Stories
(``/{page}/photo_stories`` / ``/{page}/video_stories``). Multi-photo feed posts use ``attached_media`` whose parameter
name is UNVERIFIED (open question) → rejected at validation until verified. Page Insights with the June-2026
``*_media_view`` replacements; unique impression metrics are reported as ``deprecated``.
"""
from __future__ import annotations

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
    load_media_bytes,
    media_info,
    result,
    save_state,
)
from app.integrations.social.meta.client import MetaGraphClient, insights_to_dict

VERIFIED_AT = "2026-10-08"
SCOPES = ["pages_show_list", "pages_manage_posts", "pages_read_engagement", "pages_read_user_content",
          "pages_manage_engagement", "read_insights", "publish_video", "business_management"]
REELS_PER_24H = 30
POST_INSIGHT_METRICS = ["post_media_view", "post_total_media_view_unique", "post_clicks", "post_reactions_by_type_total",
                        "post_video_views", "post_video_avg_time_watched"]
PAGE_INSIGHT_METRICS = ["page_media_view", "page_total_media_view_unique", "page_follows", "page_daily_follows_unique",
                        "page_post_engagements", "page_views_total"]


class FacebookAdapter(BaseAdapter):
    platform = "facebook"
    verified_at = VERIFIED_AT
    VERIFIED_AT = VERIFIED_AT
    docs = ["https://developers.facebook.com/docs/pages-api/posts", "https://developers.facebook.com/docs/video-api/guides/reels-publishing",
            "https://developers.facebook.com/docs/page-stories-api", "https://developers.facebook.com/docs/platforminsights/page"]

    def __init__(self) -> None:
        super().__init__()
        self.graph = MetaGraphClient("facebook")

    @staticmethod
    def _page_token(tokens: TokenSet) -> str:
        return tokens.extra.get("page_token") or tokens.access_token

    def capabilities(self, account: Any) -> Capabilities:
        return Capabilities(
            formats=["text", "link", "image", "video", "short_video", "story"],
            max_text=63206, max_media=1, native_schedule=True, can_delete=True, supports_alt_text=False,
            limits={"reels_per_24h": REELS_PER_24H, "reels_duration_s": [3, 90], "story_video_s": [3, 60],
                    "page_buc_calls_per_engaged_user_24h": 4800, "native_schedule_window": "10 min – 30 d (Reels ≤ 29 d; Stories none)"},
            notes=["multi-photo feed posts (attached_media) unverified → blocked at validation", "polls/alt text unverified",
                   "Botwok schedules; native scheduled_publish_time is an optional V2 hand-off",
                   "90-day user inactivity data cutoff → re-consent on probe failure"],
        )

    # ---- OAuth -------------------------------------------------------------------------------------------
    def auth_url(self, state: str, redirect_uri: str, flavor: str = "default", code_challenge: str | None = None) -> str:
        q = {"client_id": settings.meta_app_id, "redirect_uri": redirect_uri, "state": state, "scope": ",".join(SCOPES),
             "response_type": "code"}
        return f"https://www.facebook.com/{settings.meta_graph_version}/dialog/oauth?{urlencode(q)}"

    async def exchange_code(self, code: str, redirect_uri: str, code_verifier: str | None = None) -> TokenSet:
        short = await self.graph.get("/oauth/access_token", None, {"client_id": settings.meta_app_id, "client_secret": settings.meta_app_secret,
                                                                  "redirect_uri": redirect_uri, "code": code})
        return await self._long_lived(short["access_token"])

    async def _long_lived(self, user_token: str) -> TokenSet:
        body = await self.graph.get("/oauth/access_token", None, {"grant_type": "fb_exchange_token", "client_id": settings.meta_app_id,
                                                                 "client_secret": settings.meta_app_secret, "fb_exchange_token": user_token})
        me = await self.graph.get("/me", body["access_token"], {"fields": "id,name"})
        perms = await self.graph.get("/me/permissions", body["access_token"])
        scopes = [p["permission"] for p in perms.get("data", []) if p.get("status") == "granted"]
        return TokenSet(access_token=body["access_token"], expires_at=self.expires_in(body.get("expires_in", 60 * 86400)),
                        scopes=scopes, extra={"user_id": me.get("id"), "token_type": "user_long_lived"})

    async def refresh(self, tokens: TokenSet) -> TokenSet:
        """Re-exchange the (still valid) long-lived user token for a fresh 60-day one and refresh the page token."""
        ts = await self._long_lived(tokens.access_token)
        page_id = tokens.extra.get("page_id")
        if page_id:
            pages = await self.graph.get("/me/accounts", ts.access_token, {"fields": "id,access_token"})
            for p in pages.get("data", []):
                if str(p.get("id")) == str(page_id):
                    ts.extra.update({"page_token": p["access_token"], "page_id": page_id})
        return ts

    def refresh_supported(self, tokens: TokenSet | None = None) -> bool:
        return True

    async def list_connectable_accounts(self, tokens: TokenSet, flavor: str = "default") -> list[ConnectableAccount]:
        pages = await self.graph.get_all("/me/accounts", tokens.access_token, {"fields": "id,name,access_token,category,picture{url},tasks"})
        out = []
        for p in pages:
            out.append(ConnectableAccount(external_id=str(p["id"]), display_name=p.get("name") or p["id"], account_type="page",
                                          avatar_url=((p.get("picture") or {}).get("data") or {}).get("url"),
                                          parent_external_id=tokens.extra.get("user_id"),
                                          extra={"page_token": p.get("access_token"), "page_id": str(p["id"]), "tasks": p.get("tasks", []),
                                                 "category": p.get("category")}))
        return out

    async def probe(self, account: Any, tokens: TokenSet) -> dict[str, Any]:
        page_id = account_attr(account, "external_id")
        required = {"pages_manage_posts", "pages_read_engagement", "pages_show_list"}
        granted = set(tokens.scopes or account_attr(account, "scopes", []) or [])
        health: dict[str, Any] = {"token_valid": False, "scopes_missing": sorted(required - granted) if granted else [],
                                  "limits_remaining": None, "expires_at": tokens.expires_at.isoformat() if tokens.expires_at else None,
                                  "refreshable": True}
        try:
            page = await self.graph.get(f"/{page_id}", self._page_token(tokens), {"fields": "id,name,followers_count,fan_count"},
                                        account_id=account_attr(account, "id"))
            health["token_valid"] = True
            health["followers"] = page.get("followers_count", page.get("fan_count"))
        except PublishError as e:
            health["error"] = {"category": e.category, "code": e.code, "message": e.message}
            if e.category != "auth":
                raise
        return health

    # ---- validation --------------------------------------------------------------------------------------
    async def validate_content(self, account: Any, req: PublishRequest) -> ValidationResult:
        issues = []
        fmt = req.metadata.get("format")
        images, videos, docs = self._media_kinds(req)
        if docs:
            issues.append(issue("facebook_unsupported_media", "documents cannot be posted to a Page", "media"))
        if len(images) > 1:
            issues.append(issue("facebook_multi_photo_unverified", "multi-photo feed posts (attached_media) are not verified yet; post one image", "media"))
        if len(videos) > 1 or (videos and images):
            issues.append(issue("facebook_one_video", "one video per post, without images", "media"))
        if not (req.text or req.media or req.metadata.get("link")):
            issues.append(issue("empty_post", "post needs text, a link or media", "text"))
        if fmt == "poll" or req.metadata.get("poll"):
            issues.append(issue("facebook_polls_unverified", "Page polls are not documented in the Pages API", "poll"))
        for i, m in enumerate(req.media):
            info = media_info(req, i)
            if m in videos:
                dur = (info.get("duration_ms") or 0) / 1000
                if fmt in ("short_video", "reel") and dur and not 3 <= dur <= 90:
                    issues.append(issue("facebook_reel_duration", "Reels must be 3–90 s", f"media[{i}]"))
                if fmt == "story" and dur and not 3 <= dur <= 60:
                    issues.append(issue("facebook_story_duration", "video stories must be 3–60 s", f"media[{i}]"))
        if fmt == "story" and not req.media:
            issues.append(issue("facebook_story_media", "stories need a photo or a video", "media"))
        return result(issues)

    # ---- publish -----------------------------------------------------------------------------------------
    async def publish(self, account: Any, tokens: TokenSet, req: PublishRequest, state: dict[str, Any]) -> PublishResult:
        if state.get("post_id"):
            return self._result(state["post_id"], state.get("published_at"))
        page_id = account_attr(account, "external_id")
        token = self._page_token(tokens)
        aid = account_attr(account, "id")
        fmt = req.metadata.get("format") or "text"
        images, videos, _docs = self._media_kinds(req)
        post_id: str
        if fmt == "story":
            post_id = await self._publish_story(page_id, token, images, videos, state, aid)
        elif fmt in ("short_video", "reel") and videos:
            post_id = await self._publish_reel(page_id, token, videos[0], req, state, aid)
        elif videos:
            m = videos[0]
            data: dict[str, Any] = {"description": req.text or "", "title": req.metadata.get("title")}
            if m.url:
                data["file_url"] = m.url
                body = await self.graph.post(f"/{page_id}/videos", token, data, account_id=aid)
            else:
                blob = await load_media_bytes(m)
                body = await self.graph.post(f"/{page_id}/videos", token, data, account_id=aid, files={"source": ("video", blob, m.mime)})
            post_id = str(body.get("id"))
        elif images:
            m = images[0]
            data = {"message": req.text or ""}
            if m.url:
                data["url"] = m.url
                body = await self.graph.post(f"/{page_id}/photos", token, data, account_id=aid)
            else:
                blob = await load_media_bytes(m)
                body = await self.graph.post(f"/{page_id}/photos", token, data, account_id=aid, files={"source": ("photo", blob, m.mime)})
            post_id = str(body.get("post_id") or body.get("id"))
        else:
            data = {"message": req.text or ""}
            if req.metadata.get("link"):
                data["link"] = req.metadata["link"]
            body = await self.graph.post(f"/{page_id}/feed", token, data, account_id=aid)
            post_id = str(body.get("id"))
        if not post_id or post_id == "None":
            raise PublishError("ambiguous", "Facebook returned no post id", code="no_post_id", raw=body)
        state["post_id"] = post_id
        state["published_at"] = self.now().isoformat()
        await save_state(state)
        return self._result(post_id, state["published_at"])

    async def _publish_reel(self, page_id: str, token: str, m, req: PublishRequest, state: dict[str, Any], aid: Any) -> str:
        if not state.get("video_id"):
            start = await self.graph.post(f"/{page_id}/video_reels", token, {"upload_phase": "start"}, account_id=aid)
            state["video_id"], state["upload_url"] = start["video_id"], start["upload_url"]
            await save_state(state)
        if not state.get("uploaded"):
            headers = {"Authorization": f"OAuth {token}"}
            if m.url:
                headers["file_url"] = m.url
                await self.graph.http.request("POST", state["upload_url"], headers=headers, write=True, timeout_s=600)
            else:
                blob = await load_media_bytes(m)
                headers.update({"offset": "0", "file_size": str(len(blob))})
                await self.graph.http.request("POST", state["upload_url"], headers=headers, content=blob, write=True, timeout_s=600)
            state["uploaded"] = True
            await save_state(state)
            await heartbeat(state)
        fin = await self.graph.post(f"/{page_id}/video_reels", token, {"upload_phase": "finish", "video_id": state["video_id"],
                                                                        "video_state": "PUBLISHED", "description": req.text or ""},
                                    account_id=aid)
        return str(fin.get("post_id") or state["video_id"])

    async def _publish_story(self, page_id: str, token: str, images: list, videos: list, state: dict[str, Any], aid: Any) -> str:
        if videos:
            m = videos[0]
            if not state.get("video_id"):
                start = await self.graph.post(f"/{page_id}/video_stories", token, {"upload_phase": "start"}, account_id=aid)
                state["video_id"], state["upload_url"] = start["video_id"], start["upload_url"]
                await save_state(state)
            if not state.get("uploaded"):
                headers = {"Authorization": f"OAuth {token}"}
                if m.url:
                    headers["file_url"] = m.url
                    await self.graph.http.request("POST", state["upload_url"], headers=headers, write=True, timeout_s=600)
                else:
                    blob = await load_media_bytes(m)
                    headers.update({"offset": "0", "file_size": str(len(blob))})
                    await self.graph.http.request("POST", state["upload_url"], headers=headers, content=blob, write=True, timeout_s=600)
                state["uploaded"] = True
                await save_state(state)
            fin = await self.graph.post(f"/{page_id}/video_stories", token, {"upload_phase": "finish", "video_id": state["video_id"]},
                                        account_id=aid)
            return str(fin.get("post_id") or state["video_id"])
        m = images[0]
        if not state.get("photo_id"):
            data = {"published": "false"}
            if m.url:
                data["url"] = m.url
                body = await self.graph.post(f"/{page_id}/photos", token, data, account_id=aid)
            else:
                blob = await load_media_bytes(m)
                body = await self.graph.post(f"/{page_id}/photos", token, data, account_id=aid, files={"source": ("photo", blob, m.mime)})
            state["photo_id"] = str(body["id"])
            await save_state(state)
        fin = await self.graph.post(f"/{page_id}/photo_stories", token, {"photo_id": state["photo_id"]}, account_id=aid)
        return str(fin.get("post_id") or state["photo_id"])

    def _result(self, post_id: str, published_at: str | None) -> PublishResult:
        at = datetime.fromisoformat(published_at) if published_at else self.now()
        return PublishResult(external_id=post_id, external_url=f"https://www.facebook.com/{post_id}", published_at=at, raw={"id": post_id})

    # ---- reads / delete ----------------------------------------------------------------------------------
    async def get_post(self, account: Any, tokens: TokenSet, external_id: str) -> RemotePost:
        body = await self.graph.get(f"/{external_id}", self._page_token(tokens), {"fields": "id,message,created_time,permalink_url"},
                                    account_id=account_attr(account, "id"))
        return RemotePost(external_id=body.get("id", external_id), text=body.get("message"), created_at=_iso(body.get("created_time")),
                          url=body.get("permalink_url"), raw=body)

    async def delete_post(self, account: Any, tokens: TokenSet, external_id: str) -> None:
        await self.graph.delete(f"/{external_id}", self._page_token(tokens), account_id=account_attr(account, "id"))

    async def find_recent_posts(self, account: Any, tokens: TokenSet, since: datetime) -> list[RemotePost]:
        page_id = account_attr(account, "external_id")
        rows = await self.graph.get_all(f"/{page_id}/feed", self._page_token(tokens),
                                        {"fields": "id,message,created_time,permalink_url", "since": int(since.timestamp()), "limit": 25},
                                        limit=50, account_id=account_attr(account, "id"))
        return [RemotePost(external_id=r["id"], text=r.get("message"), created_at=_iso(r.get("created_time")), url=r.get("permalink_url"), raw=r)
                for r in rows]

    # ---- metrics -----------------------------------------------------------------------------------------
    async def get_post_metrics(self, account: Any, tokens: TokenSet, external_id: str) -> dict[str, Any]:
        from app.analytics.normalize import normalize_post_metrics
        token = self._page_token(tokens)
        aid = account_attr(account, "id")
        raw: dict[str, Any] = {"insights": {}, "errors": {}}
        try:
            ins = await self.graph.get(f"/{external_id}/insights", token, {"metric": ",".join(POST_INSIGHT_METRICS)}, account_id=aid)
            raw["insights"] = insights_to_dict(ins)
        except PublishError as e:
            if e.category == "auth":
                raise
            raw["errors"]["insights"] = {"category": e.category, "code": e.code}
            # retry metric by metric so one deprecated name never fails the whole pull
            for metric in POST_INSIGHT_METRICS:
                try:
                    ins = await self.graph.get(f"/{external_id}/insights", token, {"metric": metric}, account_id=aid)
                    raw["insights"].update(insights_to_dict(ins))
                except PublishError as e2:
                    raw["errors"][metric] = e2.code
        try:
            fields = await self.graph.get(f"/{external_id}", token, {"fields": "likes.summary(true).limit(0),comments.summary(true).limit(0),shares"},
                                          account_id=aid)
            raw["likes"] = ((fields.get("likes") or {}).get("summary") or {}).get("total_count")
            raw["comments"] = ((fields.get("comments") or {}).get("summary") or {}).get("total_count")
            raw["shares"] = (fields.get("shares") or {}).get("count")
        except PublishError as e:
            if e.category == "auth":
                raise
            raw["errors"]["fields"] = {"category": e.category, "code": e.code}
        return normalize_post_metrics("facebook", raw)

    async def get_account_metrics(self, account: Any, tokens: TokenSet) -> dict[str, Any]:
        from app.analytics.normalize import normalize_account_metrics
        page_id = account_attr(account, "external_id")
        token = self._page_token(tokens)
        aid = account_attr(account, "id")
        raw: dict[str, Any] = {"insights": {}}
        page = await self.graph.get(f"/{page_id}", token, {"fields": "followers_count,fan_count"}, account_id=aid)
        raw["followers_count"] = page.get("followers_count", page.get("fan_count"))
        try:
            ins = await self.graph.get(f"/{page_id}/insights", token, {"metric": ",".join(PAGE_INSIGHT_METRICS), "period": "day"}, account_id=aid)
            raw["insights"] = insights_to_dict(ins)
        except PublishError as e:
            if e.category == "auth":
                raise
            raw["error"] = {"category": e.category, "code": e.code}
        return normalize_account_metrics("facebook", raw)

    def rate_limits(self) -> list[dict[str, Any]]:
        return [{"scope": "app", "limit": "200 × users / hour"}, {"scope": "page_buc", "limit": "4800 × engaged users / 24 h"},
                {"scope": "reels", "limit": REELS_PER_24H, "window_s": 86400}]


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


"""YouTube adapter (doc 27 §27.7, docs/platforms/tiktok-youtube.md §2). VERIFIED_AT 2026-10-08.

Google OAuth (``youtube.upload``, ``youtube.readonly``, ``yt-analytics.readonly`` + ``youtube.force-ssl`` so
``videos.delete`` works), offline refresh tokens. Resumable ``videos.insert`` (session URL kept in
``state["upload_url"]`` so a retry resumes from the 308 ``Range``), metadata rules (title ≤ 100 chars without ``<>``,
description ≤ 5,000 **bytes**, tags ≤ 500 chars), ``publishAt`` forces ``privacyStatus=private``.
Quota (since 2026-06): ``videos.insert`` and ``search.list`` have their own 100 calls/day buckets at 1 unit/call;
everything else shares 10,000 units/day. Every call returns ``quota_units`` so the caller books the usage ledger.
"""
from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any
from urllib.parse import quote, urlencode

import httpx

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

VERIFIED_AT = "2026-10-08"
AUTH_URL = "https://accounts.google.com/o/oauth2/v2/auth"
TOKEN_URL = "https://oauth2.googleapis.com/token"
REVOKE_URL = "https://oauth2.googleapis.com/revoke"
API = "https://www.googleapis.com/youtube/v3"
UPLOAD_API = "https://www.googleapis.com/upload/youtube/v3/videos"
ANALYTICS_API = "https://youtubeanalytics.googleapis.com/v2/reports"
SCOPES = ["https://www.googleapis.com/auth/youtube.upload", "https://www.googleapis.com/auth/youtube.readonly",
          "https://www.googleapis.com/auth/yt-analytics.readonly", "https://www.googleapis.com/auth/youtube.force-ssl"]
TITLE_MAX = 100
DESCRIPTION_MAX_BYTES = 5000
TAGS_MAX_CHARS = 500
UPLOAD_CHUNK = 8 * 1024 * 1024
QUOTA = {"videos.insert": 1, "videos.list": 1, "channels.list": 1, "playlistItems.list": 1, "videos.delete": 50, "thumbnails.set": 50,
         "search.list": 1, "videos.batchGetStats": 1, "analytics.query": 1}
BUCKETS = {"videos.insert": "video_uploads", "search.list": "search_queries", "videos.batchGetStats": "batch_get_stats"}


def tags_length(tags: list[str]) -> int:
    """YouTube counts commas and the implied quotes around tags containing spaces (e.g. "Foo Baz" = 9)."""
    total = 0
    for i, t in enumerate(tags):
        total += len(t) + (2 if " " in t else 0) + (1 if i > 0 else 0)
    return total


def _g_error(resp: httpx.Response) -> PublishError | None:
    try:
        body = resp.json()
    except ValueError:
        return None
    if not isinstance(body, dict):
        return None
    err = body.get("error")
    if isinstance(err, str):   # oauth2 token endpoint
        desc = body.get("error_description", "")
        if err in ("invalid_grant", "invalid_client", "unauthorized_client"):
            return PublishError("auth", f"google oauth: {err} {desc}", code=err, raw=body)
        return PublishError("validation", f"google oauth: {err} {desc}", code=err, raw=body)
    if not isinstance(err, dict):
        return None
    reasons = [e.get("reason") for e in err.get("errors", []) if isinstance(e, dict)]
    status = err.get("status")
    msg = err.get("message") or ""
    reason = reasons[0] if reasons else status
    if resp.status_code == 401 or reason in ("authError", "invalidCredentials") or status == "UNAUTHENTICATED":
        return PublishError("auth", f"youtube auth: {msg}", code=str(reason), raw=body)
    if reason in ("quotaExceeded", "dailyLimitExceeded", "rateLimitExceeded", "userRateLimitExceeded", "uploadLimitExceeded") or status == "RESOURCE_EXHAUSTED":
        return PublishError("rate_limited", f"youtube quota: {msg}", code=str(reason), retry_after_s=_seconds_until_midnight_pt(), raw=body)
    if reason in ("insufficientPermissions", "forbidden", "youtubeSignupRequired", "channelNotFound") and resp.status_code == 403:
        return PublishError("auth" if reason in ("insufficientPermissions", "youtubeSignupRequired") else "permanent", f"youtube: {msg}",
                            code=str(reason), raw=body)
    if reason in ("invalidPublishAt", "invalidTitle", "invalidDescription", "invalidTags", "invalidVideoMetadata", "invalidPrivacyStatus",
                  "mediaBodyRequired", "invalidFilename", "badRequest") or status == "INVALID_ARGUMENT":
        return PublishError("validation", f"youtube rejected: {msg}", code=str(reason), raw=body)
    if reason in ("videoNotFound", "notFound") or status == "NOT_FOUND":
        return PublishError("permanent", f"youtube: {msg}", code=str(reason), raw=body)
    if resp.status_code == 403:
        return PublishError("permanent", f"youtube forbidden: {msg}", code=str(reason), raw=body)
    return None


def _seconds_until_midnight_pt() -> int:
    from zoneinfo import ZoneInfo
    now = datetime.now(ZoneInfo("America/Los_Angeles"))
    nxt = (now + timedelta(days=1)).replace(hour=0, minute=0, second=0, microsecond=0)
    return int((nxt - now).total_seconds()) + 60


class YouTubeAdapter(BaseAdapter):
    platform = "youtube"
    verified_at = VERIFIED_AT
    VERIFIED_AT = VERIFIED_AT
    docs = ["https://developers.google.com/youtube/v3/docs/videos/insert", "https://developers.google.com/youtube/v3/guides/using_resumable_upload_protocol",
            "https://developers.google.com/youtube/v3/determine_quota_cost", "https://developers.google.com/youtube/analytics/reference/reports/query"]

    def _headers(self, tokens: TokenSet, **extra: str) -> dict[str, str]:
        return {"Authorization": f"Bearer {tokens.access_token}", **extra}

    def capabilities(self, account: Any) -> Capabilities:
        return Capabilities(
            formats=["video", "short_video"], max_text=DESCRIPTION_MAX_BYTES, max_media=1, native_schedule=True, can_delete=True,
            supports_alt_text=False,
            limits={"title_chars": TITLE_MAX, "description_bytes": DESCRIPTION_MAX_BYTES, "tags_chars": TAGS_MAX_CHARS, "video_max_bytes": 256 * 1024**3,
                    "uploads_per_day_quota": 100, "general_quota_units_per_day": 10_000, "shorts": "≤ 3 min vertical/square auto-detected",
                    "publishAt": "requires privacyStatus=private on a never-published video"},
            notes=["unaudited API projects: uploads locked private", "Testing consent screen: refresh tokens expire after 7 days",
                   "Analytics API latency 48–72 h; impressions only via Reporting API reach reports",
                   "non-authorized (competitor) statistics may be stored ≤ 30 days"],
        )

    # ---- OAuth -------------------------------------------------------------------------------------------
    def auth_url(self, state: str, redirect_uri: str, flavor: str = "default", code_challenge: str | None = None) -> str:
        q = {"client_id": settings.google_client_id, "redirect_uri": redirect_uri, "response_type": "code", "scope": " ".join(SCOPES),
             "access_type": "offline", "prompt": "consent", "include_granted_scopes": "true", "state": state}
        if code_challenge:
            q.update({"code_challenge": code_challenge, "code_challenge_method": "S256"})
        return f"{AUTH_URL}?{urlencode(q)}"

    async def exchange_code(self, code: str, redirect_uri: str, code_verifier: str | None = None) -> TokenSet:
        data = {"code": code, "client_id": settings.google_client_id, "client_secret": settings.google_client_secret,
                "redirect_uri": redirect_uri, "grant_type": "authorization_code"}
        if code_verifier:
            data["code_verifier"] = code_verifier
        body = await self.http.post_json(TOKEN_URL, data=data, error_mapper=_g_error)
        return TokenSet(access_token=body["access_token"], refresh_token=body.get("refresh_token"), expires_at=self.expires_in(body.get("expires_in", 3600)),
                        scopes=(body.get("scope") or "").split(), extra={})

    async def refresh(self, tokens: TokenSet) -> TokenSet:
        if not tokens.refresh_token:
            raise PublishError("unsupported", "no Google refresh token stored (consent with access_type=offline required)", code="no_refresh")
        data = {"refresh_token": tokens.refresh_token, "client_id": settings.google_client_id, "client_secret": settings.google_client_secret,
                "grant_type": "refresh_token"}
        body = await self.http.post_json(TOKEN_URL, data=data, error_mapper=_g_error)
        return TokenSet(access_token=body["access_token"], refresh_token=body.get("refresh_token") or tokens.refresh_token,
                        expires_at=self.expires_in(body.get("expires_in", 3600)), scopes=(body.get("scope") or "").split() or tokens.scopes,
                        extra=dict(tokens.extra))

    async def revoke(self, tokens: TokenSet) -> None:
        try:
            await self.http.post_json(REVOKE_URL, params={"token": tokens.refresh_token or tokens.access_token}, retries=1)
        except PublishError:
            return None

    async def list_connectable_accounts(self, tokens: TokenSet, flavor: str = "default") -> list[ConnectableAccount]:
        body = await self.http.get_json(f"{API}/channels?part=snippet,statistics,contentDetails&mine=true", headers=self._headers(tokens),
                                        error_mapper=_g_error)
        out = []
        for ch in body.get("items", []):
            sn = ch.get("snippet") or {}
            out.append(ConnectableAccount(external_id=ch["id"], display_name=sn.get("title") or ch["id"], handle=sn.get("customUrl"),
                                          avatar_url=((sn.get("thumbnails") or {}).get("default") or {}).get("url"), account_type="channel",
                                          extra={"statistics": ch.get("statistics", {}),
                                                 "uploads_playlist": ((ch.get("contentDetails") or {}).get("relatedPlaylists") or {}).get("uploads")}))
        return out

    async def probe(self, account: Any, tokens: TokenSet) -> dict[str, Any]:
        required = {"https://www.googleapis.com/auth/youtube.upload"}
        granted = set(tokens.scopes or account_attr(account, "scopes", []) or [])
        health: dict[str, Any] = {"token_valid": False, "scopes_missing": sorted(required - granted) if granted else [], "limits_remaining": None,
                                  "expires_at": tokens.expires_at.isoformat() if tokens.expires_at else None, "refreshable": bool(tokens.refresh_token),
                                  "quota_units": QUOTA["channels.list"]}
        try:
            body = await self.http.get_json(f"{API}/channels?part=statistics&mine=true", headers=self._headers(tokens),
                                            account_id=account_attr(account, "id"), error_mapper=_g_error)
            health["token_valid"] = True
            items = body.get("items") or []
            health["followers"] = (items[0].get("statistics") or {}).get("subscriberCount") if items else None
        except PublishError as e:
            health["error"] = {"category": e.category, "code": e.code, "message": e.message}
            if e.category != "auth":
                raise
        return health

    # ---- validation --------------------------------------------------------------------------------------
    async def validate_content(self, account: Any, req: PublishRequest) -> ValidationResult:
        issues = []
        md = req.metadata
        title = md.get("title") or ""
        description = md.get("description") if md.get("description") is not None else (req.text or "")
        tags = md.get("tags") or []
        if not title.strip():
            issues.append(issue("youtube_title_required", "a video title is required", "title"))
        if len(title) > TITLE_MAX:
            issues.append(issue("youtube_title_too_long", f"title is {len(title)}/{TITLE_MAX} characters", "title"))
        if "<" in title or ">" in title:
            issues.append(issue("youtube_title_angle_brackets", "title must not contain < or >", "title"))
        dbytes = len(description.encode("utf-8"))
        if dbytes > DESCRIPTION_MAX_BYTES:
            issues.append(issue("youtube_description_too_long", f"description is {dbytes}/{DESCRIPTION_MAX_BYTES} bytes", "description"))
        if "<" in description or ">" in description:
            issues.append(issue("youtube_description_angle_brackets", "description must not contain < or >", "description"))
        if tags and tags_length([str(t) for t in tags]) > TAGS_MAX_CHARS:
            issues.append(issue("youtube_tags_too_long", f"tags total {tags_length([str(t) for t in tags])}/{TAGS_MAX_CHARS} characters", "tags"))
        images, videos, docs = self._media_kinds(req)
        if len(videos) != 1:
            issues.append(issue("youtube_one_video", "exactly one video is required", "media"))
        if images or docs:
            issues.append(issue("youtube_no_images", "images cannot be posted (thumbnails only, verified channels)", "media"))
        privacy = md.get("privacy_status") or md.get("privacyStatus") or "private"
        if privacy not in ("private", "public", "unlisted"):
            issues.append(issue("youtube_privacy_status", "privacyStatus must be private|public|unlisted", "privacy_status"))
        if md.get("publish_at") and privacy != "private":
            issues.append(issue("youtube_publish_at_requires_private", "publishAt requires privacyStatus=private", "publish_at"))
        caps = (account_attr(account, "capabilities", {}) or {})
        if caps.get("audited") is False and privacy != "private":
            issues.append(issue("youtube_unaudited_private", "unaudited API projects publish as private; the video will be locked private", "privacy_status", "warning"))
        for i, _m in enumerate(videos):
            info = media_info(req, i)
            if (info.get("bytes") or 0) > 256 * 1024**3:
                issues.append(issue("youtube_video_too_large", "video exceeds 256 GB", f"media[{i}]"))
        return result(issues)

    # ---- publish (resumable upload) ----------------------------------------------------------------------
    async def publish(self, account: Any, tokens: TokenSet, req: PublishRequest, state: dict[str, Any]) -> PublishResult:
        if state.get("video_id"):
            return self._result(state["video_id"], state.get("published_at"), state.get("quota_units", 0))
        aid = account_attr(account, "id")
        _images, videos, _docs = self._media_kinds(req)
        if not videos:
            raise PublishError("validation", "youtube_one_video", code="youtube_one_video")
        m = videos[0]
        data = await load_media_bytes(m)
        md = req.metadata
        privacy = md.get("privacy_status") or md.get("privacyStatus") or "private"
        body: dict[str, Any] = {
            "snippet": {"title": (md.get("title") or "")[:TITLE_MAX], "description": md.get("description") if md.get("description") is not None else (req.text or ""),
                        "tags": [str(t) for t in (md.get("tags") or [])], "categoryId": str(md.get("category_id") or "22"),
                        **({"defaultLanguage": md["language"]} if md.get("language") else {})},
            "status": {"privacyStatus": privacy, "selfDeclaredMadeForKids": bool(md.get("made_for_kids", False))},
        }
        if md.get("publish_at"):
            body["status"]["privacyStatus"] = "private"
            body["status"]["publishAt"] = md["publish_at"]
        if md.get("contains_synthetic_media") is not None:
            body["status"]["containsSyntheticMedia"] = bool(md["contains_synthetic_media"])
        quota_units = 0
        if not state.get("upload_url"):
            notify = "true" if md.get("notify_subscribers", True) else "false"
            resp = await self.http.request("POST", f"{UPLOAD_API}?uploadType=resumable&part=snippet,status&notifySubscribers={notify}",
                                           headers=self._headers(tokens, **{"X-Upload-Content-Length": str(len(data)),
                                                                            "X-Upload-Content-Type": m.mime or "video/*",
                                                                            "Content-Type": "application/json; charset=UTF-8"}),
                                           json=body, write=True, account_id=aid, error_mapper=_g_error)
            state["upload_url"] = resp.headers.get("location") or resp.headers.get("Location")
            quota_units += QUOTA["videos.insert"]
            state["quota_units"] = quota_units
            if not state["upload_url"]:
                raise PublishError("transient", "no resumable session URL returned", code="no_upload_url")
            await save_state(state)
        video = await self._upload_resumable(tokens, state["upload_url"], data, m.mime or "video/*", state)
        vid = video.get("id")
        if not vid:
            raise PublishError("ambiguous", "upload finished but no video id returned", code="no_post_id", raw=video)
        state["video_id"] = vid
        state["published_at"] = self.now().isoformat()
        await save_state(state)
        return self._result(vid, state["published_at"], state.get("quota_units", quota_units))

    async def _upload_resumable(self, tokens: TokenSet, session_url: str, data: bytes, mime: str, state: dict[str, Any]) -> dict[str, Any]:
        total = len(data)
        offset = int(state.get("uploaded_bytes") or 0)
        if offset:
            # resume: ask the session where we are
            try:
                r = await self.http.request("PUT", session_url, headers=self._headers(tokens, **{"Content-Range": f"bytes */{total}", "Content-Length": "0"}),
                                            ok=(200, 201, 308), write=True)
                if r.status_code in (200, 201):
                    return r.json()
                rng = r.headers.get("range") or r.headers.get("Range")
                offset = int(rng.split("-")[-1]) + 1 if rng else 0
            except PublishError as e:
                if e.category in ("permanent", "validation"):
                    state["upload_url"] = None   # session gone → restart on the next attempt
                    await save_state(state)
                raise
        while offset < total:
            chunk = data[offset:offset + UPLOAD_CHUNK]
            end = offset + len(chunk) - 1
            r = await self.http.request("PUT", session_url, content=chunk, timeout_s=600, write=True,
                                        headers=self._headers(tokens, **{"Content-Type": mime, "Content-Length": str(len(chunk)),
                                                                         "Content-Range": f"bytes {offset}-{end}/{total}"}),
                                        ok=(200, 201, 308), error_mapper=_g_error)
            if r.status_code in (200, 201):
                return r.json()
            rng = r.headers.get("range") or r.headers.get("Range")
            offset = int(rng.split("-")[-1]) + 1 if rng else end + 1
            state["uploaded_bytes"] = offset
            await save_state(state)
            await heartbeat(state)
        raise PublishError("ambiguous", "upload loop ended without a final response", code="upload_incomplete")

    def _result(self, vid: str, published_at: str | None, quota_units: int) -> PublishResult:
        at = datetime.fromisoformat(published_at) if published_at else self.now()
        return PublishResult(external_id=vid, external_url=f"https://www.youtube.com/watch?v={vid}", published_at=at,
                             raw={"id": vid, "quota_units": quota_units, "quota_bucket": BUCKETS["videos.insert"]})

    async def get_status(self, account: Any, tokens: TokenSet, state: dict[str, Any]) -> dict[str, Any] | None:
        if state.get("video_id"):
            return {"status": "published", "external_id": state["video_id"], "external_url": f"https://www.youtube.com/watch?v={state['video_id']}"}
        if state.get("upload_url"):
            return {"status": "pending"}
        return None

    # ---- reads / delete ----------------------------------------------------------------------------------
    async def get_post(self, account: Any, tokens: TokenSet, external_id: str) -> RemotePost:
        body = await self.http.get_json(f"{API}/videos?part=snippet,status&id={quote(external_id)}", headers=self._headers(tokens),
                                        account_id=account_attr(account, "id"), error_mapper=_g_error)
        items = body.get("items") or []
        if not items:
            raise PublishError("permanent", "video not found", code="not_found", raw=body)
        sn = items[0].get("snippet") or {}
        return RemotePost(external_id=items[0]["id"], text=sn.get("title"), created_at=_iso(sn.get("publishedAt")),
                          url=f"https://www.youtube.com/watch?v={items[0]['id']}", raw={**items[0], "quota_units": 1})

    async def delete_post(self, account: Any, tokens: TokenSet, external_id: str) -> None:
        await self.http.request("DELETE", f"{API}/videos?id={quote(external_id)}", headers=self._headers(tokens),
                                account_id=account_attr(account, "id"), ok=(200, 204, 404), error_mapper=_g_error)

    async def find_recent_posts(self, account: Any, tokens: TokenSet, since: datetime) -> list[RemotePost]:
        """Uploads playlist (1 unit) — the docs advise against search.list for a channel's recent uploads."""
        body = await self.http.get_json(f"{API}/channels?part=contentDetails&mine=true", headers=self._headers(tokens),
                                        account_id=account_attr(account, "id"), error_mapper=_g_error)
        items = body.get("items") or []
        playlist = (((items[0].get("contentDetails") or {}).get("relatedPlaylists") or {}).get("uploads")) if items else None
        if not playlist:
            return []
        body = await self.http.get_json(f"{API}/playlistItems?part=snippet,contentDetails&playlistId={playlist}&maxResults=20",
                                        headers=self._headers(tokens), account_id=account_attr(account, "id"), error_mapper=_g_error)
        out = []
        for it in body.get("items", []):
            sn = it.get("snippet") or {}
            vid = (it.get("contentDetails") or {}).get("videoId") or (sn.get("resourceId") or {}).get("videoId")
            ts = _iso(sn.get("publishedAt"))
            if ts and ts < since:
                continue
            out.append(RemotePost(external_id=vid, text=sn.get("title"), created_at=ts, url=f"https://www.youtube.com/watch?v={vid}", raw=it))
        return out

    # ---- metrics -----------------------------------------------------------------------------------------
    async def get_post_metrics(self, account: Any, tokens: TokenSet, external_id: str) -> dict[str, Any]:
        from app.analytics.normalize import normalize_post_metrics
        aid = account_attr(account, "id")
        raw: dict[str, Any] = {"statistics": {}, "analytics": {}, "errors": {}, "quota_units": 0}
        try:
            body = await self.http.get_json(f"{API}/videos?part=statistics,contentDetails&id={quote(external_id)}", headers=self._headers(tokens),
                                            account_id=aid, error_mapper=_g_error)
            raw["quota_units"] += QUOTA["videos.list"]
            items = body.get("items") or []
            raw["statistics"] = (items[0].get("statistics") or {}) if items else {}
            raw["duration"] = ((items[0].get("contentDetails") or {}).get("duration")) if items else None
        except PublishError as e:
            if e.category in ("auth", "rate_limited"):
                raise
            raw["errors"]["statistics"] = {"category": e.category, "code": e.code}
        if "https://www.googleapis.com/auth/yt-analytics.readonly" in set(tokens.scopes or []):
            end = self.now().date()
            start = end - timedelta(days=365)
            q = {"ids": "channel==MINE", "startDate": start.isoformat(), "endDate": end.isoformat(),
                 "metrics": "views,engagedViews,estimatedMinutesWatched,averageViewDuration,averageViewPercentage,likes,dislikes,comments,shares,subscribersGained",
                 "filters": f"video=={external_id}"}
            try:
                body = await self.http.get_json(f"{ANALYTICS_API}?{urlencode(q)}", headers=self._headers(tokens), account_id=aid, error_mapper=_g_error)
                raw["quota_units"] += QUOTA["analytics.query"]
                headers = [h.get("name") for h in body.get("columnHeaders", [])]
                rows = body.get("rows") or []
                if rows:
                    raw["analytics"] = dict(zip(headers, rows[0], strict=False))
            except PublishError as e:
                if e.category == "auth":
                    raise
                raw["errors"]["analytics"] = {"category": e.category, "code": e.code}
        return normalize_post_metrics("youtube", raw)

    async def get_account_metrics(self, account: Any, tokens: TokenSet) -> dict[str, Any]:
        from app.analytics.normalize import normalize_account_metrics
        aid = account_attr(account, "id")
        body = await self.http.get_json(f"{API}/channels?part=statistics&mine=true", headers=self._headers(tokens), account_id=aid, error_mapper=_g_error)
        items = body.get("items") or []
        raw: dict[str, Any] = {"statistics": (items[0].get("statistics") or {}) if items else {}, "analytics": {}, "quota_units": QUOTA["channels.list"]}
        if "https://www.googleapis.com/auth/yt-analytics.readonly" in set(tokens.scopes or []):
            end = self.now().date() - timedelta(days=3)   # 48–72 h latency
            q = {"ids": "channel==MINE", "startDate": end.isoformat(), "endDate": end.isoformat(), "metrics": "views,subscribersGained,subscribersLost"}
            try:
                b = await self.http.get_json(f"{ANALYTICS_API}?{urlencode(q)}", headers=self._headers(tokens), account_id=aid, error_mapper=_g_error)
                raw["quota_units"] += 1
                headers = [h.get("name") for h in b.get("columnHeaders", [])]
                rows = b.get("rows") or []
                if rows:
                    raw["analytics"] = dict(zip(headers, rows[0], strict=False))
            except PublishError as e:
                if e.category == "auth":
                    raise
                raw["analytics_error"] = {"category": e.category, "code": e.code}
        return normalize_account_metrics("youtube", raw)

    async def get_public_profile(self, tokens: TokenSet | None, channel_id: str, video_ids: list[str] | None = None) -> dict[str, Any]:
        """Public channel statistics (+ ``videos.batchGetStats`` for public videos). Store ≤ 30 days (developer policy)."""
        headers = self._headers(tokens) if tokens else {}
        key = "" if tokens else f"&key={settings.google_api_key}"
        body = await self.http.get_json(f"{API}/channels?part=snippet,statistics&id={quote(channel_id)}{key}", headers=headers, error_mapper=_g_error)
        items = body.get("items") or []
        out: dict[str, Any] = {"channel": items[0] if items else None, "videos": [], "quota_units": 1, "availability": "official_api",
                               "retention_days": 30}
        if video_ids:
            ids = "&".join(f"id={quote(v)}" for v in video_ids[:50])
            try:
                b = await self.http.get_json(f"{API}/videos:batchGetStats?{ids}{key}", headers=headers, error_mapper=_g_error)
                out["videos"] = b.get("items") or b.get("stats") or []
                out["quota_units"] += 1
            except PublishError as e:
                out["videos_error"] = {"category": e.category, "code": e.code}
        return out

    def rate_limits(self) -> list[dict[str, Any]]:
        return [{"bucket": "video_uploads", "limit": 100, "window": "day (resets midnight PT)"},
                {"bucket": "search_queries", "limit": 100, "window": "day"}, {"bucket": "general", "limit": 10_000, "window": "day"}]


def _iso(v: Any) -> datetime | None:
    if not v:
        return None
    try:
        return datetime.fromisoformat(str(v).replace("Z", "+00:00")).astimezone(UTC)
    except ValueError:
        return None


"""TikTok adapter (doc 27 §27.6, docs/platforms/tiktok-youtube.md §1). VERIFIED_AT 2026-10-08.

Login Kit PKCE with the desktop quirk: the code challenge is the **hex** SHA-256 of the verifier. Tokens: access 24 h,
refresh 365 d (rotating → always persist the returned one). Modes (``auth_flavor``):
* ``inbox_upload`` (default, ``video.upload``): ``POST /v2/post/publish/inbox/video/init/`` + chunked FILE_UPLOAD; the
  creator finalizes the post in the TikTok app (5 pending / 24 h).
* ``direct_post`` (``video.publish``, requires the Content Posting audit): ``creator_info/query`` → ``video/init`` with
  the mandated ``post_info`` fields (privacy_level chosen by the user, interaction toggles, commercial disclosure,
  ``is_aigc``) → upload → ``status/fetch`` until PUBLISH_COMPLETE. Photo posts use ``content/init`` (PULL_FROM_URL
  from a verified domain only).
No delete endpoint, no scheduling, no captions. Metrics: lifetime view/like/comment/share via ``video/query``.
"""
from __future__ import annotations

import asyncio
from datetime import UTC, datetime
from typing import Any
from urllib.parse import urlencode

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
AUTH_URL = "https://www.tiktok.com/v2/auth/authorize/"
API = "https://open.tiktokapis.com/v2"
TOKEN_URL = f"{API}/oauth/token/"
REVOKE_URL = f"{API}/oauth/revoke/"
SCOPES_INBOX = ["user.info.basic", "user.info.profile", "user.info.stats", "video.list", "video.upload"]
SCOPES_DIRECT = SCOPES_INBOX + ["video.publish"]
CHUNK_MIN, CHUNK_MAX, CHUNK_DEFAULT = 5 * 1024**2, 64 * 1024**2, 10 * 1024**2
LAST_CHUNK_MAX = 128 * 1024**2
VIDEO_MAX_BYTES = 4 * 1024**3
TITLE_MAX = 2200
PHOTO_TITLE_MAX, PHOTO_DESC_MAX, PHOTO_MAX = 90, 4000, 35
PRIVACY_LEVELS = {"PUBLIC_TO_EVERYONE", "MUTUAL_FOLLOW_FRIENDS", "FOLLOWER_OF_CREATOR", "SELF_ONLY"}
USER_FIELDS = "open_id,union_id,avatar_url,display_name,username,follower_count,following_count,likes_count,video_count,is_verified"
VIDEO_FIELDS = "id,create_time,cover_image_url,share_url,video_description,duration,title,like_count,comment_count,share_count,view_count"


def _tt_error(resp: httpx.Response) -> PublishError | None:
    try:
        body = resp.json()
    except ValueError:
        return None
    if not isinstance(body, dict):
        return None
    err = body.get("error") if isinstance(body.get("error"), dict) else body
    code = err.get("code") or err.get("error")
    msg = err.get("message") or err.get("error_description") or ""
    if code in (None, "ok"):
        return None
    code = str(code)
    if code in ("access_token_invalid", "token_expired", "invalid_grant", "scope_not_authorized", "scope_permission_missed", "invalid_token"):
        return PublishError("auth", f"tiktok auth: {code} {msg}", code=code, raw=body)
    if code in ("rate_limit_exceeded", "spam_risk_too_many_posts", "spam_risk_too_many_pending_share", "reached_active_user_cap",
                "spam_risk_user_banned_from_posting"):
        return PublishError("rate_limited", f"tiktok limit: {code} {msg}", code=code, retry_after_s=3600 if code != "rate_limit_exceeded" else 60, raw=body)
    if code in ("invalid_params", "invalid_file_upload", "url_ownership_unverified", "video_pull_failed", "picture_size_check_failed",
                "picture_download_failed", "invalid_publish_id", "file_format_check_failed", "duration_check_failed", "frame_rate_check_failed",
                "picture_resolution_check_failed", "video_resolution_check_failed"):
        return PublishError("validation", f"tiktok rejected: {code} {msg}", code=code, raw=body)
    if code in ("unaudited_client_can_only_post_to_private_accounts", "privacy_level_option_mismatch", "publish_id_not_found",
                "app_version_check_failed", "token_not_authorized_for_specified_scope"):
        return PublishError("permanent", f"tiktok: {code} {msg}", code=code, raw=body)
    if code in ("internal_error", "service_unavailable", "internal"):
        return PublishError("transient", f"tiktok transient: {code} {msg}", code=code, raw=body)
    return PublishError("permanent", f"tiktok error: {code} {msg}", code=code, raw=body)


class TikTokAdapter(BaseAdapter):
    platform = "tiktok"
    verified_at = VERIFIED_AT
    VERIFIED_AT = VERIFIED_AT
    docs = ["https://developers.tiktok.com/doc/content-posting-api-reference-direct-post", "https://developers.tiktok.com/doc/content-posting-api-reference-upload-video",
            "https://developers.tiktok.com/doc/content-posting-api-media-transfer-guide", "https://developers.tiktok.com/doc/login-kit-desktop"]

    @staticmethod
    def _mode(account: Any) -> str:
        f = account_attr(account, "auth_flavor", "inbox_upload") or "inbox_upload"
        return "direct_post" if f == "direct_post" else "inbox_upload"

    def _headers(self, tokens: TokenSet, **extra: str) -> dict[str, str]:
        return {"Authorization": f"Bearer {tokens.access_token}", "Content-Type": "application/json; charset=UTF-8", **extra}

    def capabilities(self, account: Any) -> Capabilities:
        mode = self._mode(account) if account is not None else "inbox_upload"
        return Capabilities(
            formats=["video", "short_video", "carousel"], max_text=TITLE_MAX, max_media=PHOTO_MAX, native_schedule=False, can_delete=False,
            supports_alt_text=False,
            limits={"mode": mode, "direct_posts_per_day": 15, "pending_inbox_uploads_24h": 5, "init_per_min": 6, "creator_info_per_min": 20,
                    "status_per_min": 30, "video_max_bytes": VIDEO_MAX_BYTES, "chunk_bytes": [CHUNK_MIN, CHUNK_MAX], "photo_max": PHOTO_MAX,
                    "photo_max_bytes": 20 * 1024**2, "video_title_max": TITLE_MAX, "photo_title_max": PHOTO_TITLE_MAX, "access_token_s": 86400,
                    "refresh_token_s": 31_536_000},
            notes=["no delete endpoint", "no scheduling", "photo posts PULL_FROM_URL from a verified domain only",
                   "direct_post requires the Content Posting audit (team tools rejected) and TikTok's mandated posting UX",
                   "unaudited clients: SELF_ONLY, private accounts, ≤ 5 posting users / 24 h"],
        )

    # ---- OAuth (hex-SHA256 PKCE) -------------------------------------------------------------------------
    def auth_url(self, state: str, redirect_uri: str, flavor: str = "inbox_upload", code_challenge: str | None = None) -> str:
        scopes = SCOPES_DIRECT if flavor == "direct_post" else SCOPES_INBOX
        q = {"client_key": settings.tiktok_client_key, "scope": ",".join(scopes), "response_type": "code", "redirect_uri": redirect_uri,
             "state": state, "code_challenge": code_challenge or "", "code_challenge_method": "S256"}
        return f"{AUTH_URL}?{urlencode(q)}"

    async def exchange_code(self, code: str, redirect_uri: str, code_verifier: str | None = None) -> TokenSet:
        data = {"client_key": settings.tiktok_client_key, "client_secret": settings.tiktok_client_secret, "code": code,
                "grant_type": "authorization_code", "redirect_uri": redirect_uri, "code_verifier": code_verifier or ""}
        body = await self.http.post_json(TOKEN_URL, data=data, headers={"Content-Type": "application/x-www-form-urlencoded"}, error_mapper=_tt_error)
        return self._tokens_from(body)

    def _tokens_from(self, body: dict[str, Any], previous: TokenSet | None = None) -> TokenSet:
        return TokenSet(access_token=body["access_token"], refresh_token=body.get("refresh_token") or (previous.refresh_token if previous else None),
                        expires_at=self.expires_in(body.get("expires_in", 86400)),
                        refresh_expires_at=self.expires_in(body["refresh_expires_in"]) if body.get("refresh_expires_in") else (previous.refresh_expires_at if previous else None),
                        scopes=(body.get("scope") or "").replace(" ", "").split(",") if body.get("scope") else (previous.scopes if previous else []),
                        extra={**(previous.extra if previous else {}), "open_id": body.get("open_id") or (previous.extra.get("open_id") if previous else None)})

    async def refresh(self, tokens: TokenSet) -> TokenSet:
        if not tokens.refresh_token:
            raise PublishError("unsupported", "no TikTok refresh token stored", code="no_refresh")
        data = {"client_key": settings.tiktok_client_key, "client_secret": settings.tiktok_client_secret, "grant_type": "refresh_token",
                "refresh_token": tokens.refresh_token}
        body = await self.http.post_json(TOKEN_URL, data=data, headers={"Content-Type": "application/x-www-form-urlencoded"}, error_mapper=_tt_error)
        return self._tokens_from(body, previous=tokens)

    async def revoke(self, tokens: TokenSet) -> None:
        try:
            await self.http.post_json(REVOKE_URL, data={"client_key": settings.tiktok_client_key, "client_secret": settings.tiktok_client_secret,
                                                        "token": tokens.access_token}, headers={"Content-Type": "application/x-www-form-urlencoded"}, retries=1)
        except PublishError:
            return None

    async def list_connectable_accounts(self, tokens: TokenSet, flavor: str = "inbox_upload") -> list[ConnectableAccount]:
        body = await self.http.get_json(f"{API}/user/info/?fields={USER_FIELDS}", headers=self._headers(tokens), error_mapper=_tt_error)
        u = (body.get("data") or {}).get("user") or {}
        ext = u.get("open_id") or tokens.extra.get("open_id")
        return [ConnectableAccount(external_id=str(ext), display_name=u.get("display_name") or u.get("username") or str(ext), handle=u.get("username"),
                                   avatar_url=u.get("avatar_url"), account_type="creator",
                                   extra={"follower_count": u.get("follower_count"), "is_verified": u.get("is_verified"), "union_id": u.get("union_id")})]

    async def probe(self, account: Any, tokens: TokenSet) -> dict[str, Any]:
        mode = self._mode(account)
        required = {"video.publish"} if mode == "direct_post" else {"video.upload"}
        granted = set(tokens.scopes or account_attr(account, "scopes", []) or [])
        health: dict[str, Any] = {"token_valid": False, "scopes_missing": sorted(required - granted) if granted else [], "limits_remaining": None,
                                  "expires_at": tokens.expires_at.isoformat() if tokens.expires_at else None, "refreshable": bool(tokens.refresh_token),
                                  "mode": mode}
        try:
            body = await self.http.get_json(f"{API}/user/info/?fields=open_id,display_name,follower_count", headers=self._headers(tokens),
                                            account_id=account_attr(account, "id"), error_mapper=_tt_error)
            health["token_valid"] = True
            health["followers"] = ((body.get("data") or {}).get("user") or {}).get("follower_count")
        except PublishError as e:
            health["error"] = {"category": e.category, "code": e.code, "message": e.message}
            if e.category != "auth":
                raise
            return health
        if mode == "direct_post" and "video.publish" in granted:
            try:
                ci = await self.http.post_json(f"{API}/post/publish/creator_info/query/", headers=self._headers(tokens), json={},
                                               account_id=account_attr(account, "id"), error_mapper=_tt_error)
                health["creator_info"] = ci.get("data") or {}
            except PublishError as e:
                health["creator_info_error"] = {"category": e.category, "code": e.code}
        return health

    # ---- validation --------------------------------------------------------------------------------------
    async def validate_content(self, account: Any, req: PublishRequest) -> ValidationResult:
        issues = []
        mode = self._mode(account)
        md = req.metadata
        images, videos, docs = self._media_kinds(req)
        if docs:
            issues.append(issue("tiktok_unsupported_media", "only videos and photos are supported", "media"))
        if not req.media:
            issues.append(issue("tiktok_media_required", "TikTok has no text-only posts", "media"))
        if videos and images:
            issues.append(issue("tiktok_mixed_media", "a post is either one video or 1–35 photos", "media"))
        if len(videos) > 1:
            issues.append(issue("tiktok_one_video", "one video per post", "media"))
        title = md.get("title") or req.text or ""
        if videos and len(title) > TITLE_MAX:
            issues.append(issue("tiktok_title_too_long", f"title is {len(title)}/{TITLE_MAX} characters", "title"))
        for i, m in enumerate(videos):
            info = media_info(req, i)
            if (info.get("bytes") or 0) > VIDEO_MAX_BYTES:
                issues.append(issue("tiktok_video_too_large", "video exceeds 4 GB", f"media[{i}]"))
            if (m.mime or "").lower() not in ("video/mp4", "video/webm", "video/quicktime"):
                issues.append(issue("tiktok_video_format", "video must be MP4, WebM or MOV", f"media[{i}]"))
            maxd = (((account_attr(account, "health", {}) or {}).get("creator_info") or {}).get("max_video_post_duration_sec"))
            if maxd and (info.get("duration_ms") or 0) / 1000 > maxd:
                issues.append(issue("tiktok_video_too_long", f"video exceeds the creator's max duration ({maxd} s)", f"media[{i}]"))
        if images:
            if len(images) > PHOTO_MAX:
                issues.append(issue("tiktok_too_many_photos", f"at most {PHOTO_MAX} photos", "media"))
            if len(title) > PHOTO_TITLE_MAX:
                issues.append(issue("tiktok_photo_title_too_long", f"photo post title is {len(title)}/{PHOTO_TITLE_MAX}", "title"))
            if len(md.get("description") or "") > PHOTO_DESC_MAX:
                issues.append(issue("tiktok_photo_description_too_long", f"description exceeds {PHOTO_DESC_MAX}", "description"))
            for i, m in enumerate(images):
                if not m.url:
                    issues.append(issue("tiktok_photos_require_public_url", "photo posts are PULL_FROM_URL only (verified domain)", f"media[{i}]"))
                if (m.mime or "").lower() not in ("image/jpeg", "image/webp"):
                    issues.append(issue("tiktok_photo_format", "photos must be JPEG or WebP", f"media[{i}]"))
                if (media_info(req, i).get("bytes") or 0) > 20 * 1024**2:
                    issues.append(issue("tiktok_photo_too_large", "photo exceeds 20 MB", f"media[{i}]"))
        if mode == "direct_post":
            pl = md.get("privacy_level")
            if not pl:
                issues.append(issue("tiktok_privacy_level_required", "direct posts need a privacy level chosen by the user (no default)", "privacy_level"))
            elif pl not in PRIVACY_LEVELS:
                issues.append(issue("tiktok_privacy_level_invalid", f"privacy_level must be one of {sorted(PRIVACY_LEVELS)}", "privacy_level"))
            options = (((account_attr(account, "health", {}) or {}).get("creator_info") or {}).get("privacy_level_options"))
            if pl and options and pl not in options:
                issues.append(issue("tiktok_privacy_level_not_allowed", f"creator allows only {options}", "privacy_level"))
            if md.get("brand_content_toggle") and pl == "SELF_ONLY":
                issues.append(issue("tiktok_branded_content_private", "branded content cannot be private (SELF_ONLY)", "privacy_level"))
            if md.get("commercial_content") and not (md.get("brand_content_toggle") or md.get("brand_organic_toggle")):
                issues.append(issue("tiktok_commercial_disclosure", "commercial content needs 'Your Brand' and/or 'Branded Content' selected", "commercial_content"))
            if not md.get("user_consent"):
                issues.append(issue("tiktok_consent_required", "express user consent (preview + declaration) is mandatory before a direct post", "user_consent"))
        return result(issues)

    # ---- publish -----------------------------------------------------------------------------------------
    async def publish(self, account: Any, tokens: TokenSet, req: PublishRequest, state: dict[str, Any]) -> PublishResult:
        if state.get("publish_id") and state.get("final_status"):
            return self._result(state, account)
        aid = account_attr(account, "id")
        mode = self._mode(account)
        md = req.metadata
        images, videos, _docs = self._media_kinds(req)
        if images and not videos:
            return await self._publish_photos(account, tokens, req, state, mode, images)
        if not videos:
            raise PublishError("validation", "tiktok_media_required", code="tiktok_media_required")
        m = videos[0]
        data = await load_media_bytes(m)
        title = (md.get("title") or req.text or "")[:TITLE_MAX]
        if not state.get("publish_id"):
            size = len(data)
            chunk = CHUNK_DEFAULT
            if size <= CHUNK_MIN:
                chunk, count = size, 1
            else:
                count = max(1, size // chunk)
                if count > 1000:
                    chunk, count = CHUNK_MAX, max(1, size // CHUNK_MAX)
                if size - chunk * count > LAST_CHUNK_MAX - chunk:
                    count += 1
            source = {"source": "FILE_UPLOAD", "video_size": size, "chunk_size": chunk, "total_chunk_count": count}
            if mode == "direct_post":
                ci = await self.http.post_json(f"{API}/post/publish/creator_info/query/", headers=self._headers(tokens), json={}, account_id=aid,
                                               error_mapper=_tt_error)
                info = ci.get("data") or {}
                pl = md.get("privacy_level")
                if not pl or (info.get("privacy_level_options") and pl not in info["privacy_level_options"]):
                    raise PublishError("validation", "tiktok_privacy_level_required", code="tiktok_privacy_level_required", raw=info)
                post_info: dict[str, Any] = {"title": title, "privacy_level": pl, "disable_duet": bool(md.get("disable_duet", True)),
                                             "disable_comment": bool(md.get("disable_comment", True)), "disable_stitch": bool(md.get("disable_stitch", True)),
                                             "brand_content_toggle": bool(md.get("brand_content_toggle", False)),
                                             "brand_organic_toggle": bool(md.get("brand_organic_toggle", False)), "is_aigc": bool(md.get("is_aigc", False))}
                if md.get("video_cover_timestamp_ms") is not None:
                    post_info["video_cover_timestamp_ms"] = int(md["video_cover_timestamp_ms"])
                init = await self.http.post_json(f"{API}/post/publish/video/init/", headers=self._headers(tokens),
                                                 json={"post_info": post_info, "source_info": source}, write=True, account_id=aid, error_mapper=_tt_error)
            else:
                init = await self.http.post_json(f"{API}/post/publish/inbox/video/init/", headers=self._headers(tokens), json={"source_info": source},
                                                 write=True, account_id=aid, error_mapper=_tt_error)
            d = init.get("data") or {}
            state.update({"publish_id": d.get("publish_id"), "upload_url": d.get("upload_url"), "chunk_size": chunk, "total_chunks": count,
                          "uploaded_chunks": 0, "mode": mode})
            await save_state(state)
        if state.get("upload_url") and state.get("uploaded_chunks", 0) < state.get("total_chunks", 1):
            await self._upload_chunks(data, state, m.mime or "video/mp4")
        await self._wait_status(tokens, state, aid, mode)
        return self._result(state, account)

    async def _upload_chunks(self, data: bytes, state: dict[str, Any], mime: str) -> None:
        size = len(data)
        chunk, count = int(state["chunk_size"]), int(state["total_chunks"])
        for i in range(int(state.get("uploaded_chunks", 0)), count):
            start = i * chunk
            end = size - 1 if i == count - 1 else min(start + chunk, size) - 1
            blob = data[start:end + 1]
            await self.http.request("PUT", state["upload_url"], content=blob, timeout_s=600, write=True, ok=(200, 201, 206),
                                    headers={"Content-Type": mime, "Content-Length": str(len(blob)), "Content-Range": f"bytes {start}-{end}/{size}"})
            state["uploaded_chunks"] = i + 1
            await save_state(state)
            await heartbeat(state)

    async def _publish_photos(self, account: Any, tokens: TokenSet, req: PublishRequest, state: dict[str, Any], mode: str, images: list) -> PublishResult:
        aid = account_attr(account, "id")
        md = req.metadata
        if not state.get("publish_id"):
            urls = [m.url for m in images[:PHOTO_MAX]]
            if any(not u for u in urls):
                raise PublishError("validation", "tiktok_photos_require_public_url", code="tiktok_photos_require_public_url")
            post_info: dict[str, Any] = {"title": (md.get("title") or req.text or "")[:PHOTO_TITLE_MAX], "description": (md.get("description") or "")[:PHOTO_DESC_MAX],
                                         "disable_comment": bool(md.get("disable_comment", True)),
                                         "brand_content_toggle": bool(md.get("brand_content_toggle", False)),
                                         "brand_organic_toggle": bool(md.get("brand_organic_toggle", False))}
            if mode == "direct_post":
                if not md.get("privacy_level"):
                    raise PublishError("validation", "tiktok_privacy_level_required", code="tiktok_privacy_level_required")
                post_info["privacy_level"] = md["privacy_level"]
                post_info["auto_add_music"] = bool(md.get("auto_add_music", False))
            body = {"post_info": post_info, "source_info": {"source": "PULL_FROM_URL", "photo_cover_index": int(md.get("photo_cover_index", 0)), "photo_images": urls},
                    "post_mode": "DIRECT_POST" if mode == "direct_post" else "MEDIA_UPLOAD", "media_type": "PHOTO"}
            init = await self.http.post_json(f"{API}/post/publish/content/init/", headers=self._headers(tokens), json=body, write=True, account_id=aid,
                                             error_mapper=_tt_error)
            state.update({"publish_id": (init.get("data") or {}).get("publish_id"), "mode": mode, "kind": "photo"})
            await save_state(state)
        await self._wait_status(tokens, state, aid, mode)
        return self._result(state, account)

    async def _wait_status(self, tokens: TokenSet, state: dict[str, Any], aid: Any, mode: str) -> None:
        deadline = asyncio.get_event_loop().time() + 900
        while True:
            st = await self._fetch_status(tokens, state["publish_id"], aid)
            status = st.get("status")
            state["last_status"] = status
            if status == "PUBLISH_COMPLETE" or (mode == "inbox_upload" and status == "SEND_TO_USER_INBOX"):
                state["final_status"] = status
                ids = st.get("publicaly_available_post_id") or st.get("publicly_available_post_id") or []
                state["post_ids"] = [str(x) for x in ids] if isinstance(ids, list) else [str(ids)]
                await save_state(state)
                return
            if status == "FAILED":
                reason = st.get("fail_reason") or "unknown"
                cat = "validation" if reason in ("file_format_check_failed", "duration_check_failed", "frame_rate_check_failed", "picture_size_check_failed",
                                                 "video_pull_failed", "picture_download_failed") else "permanent"
                raise PublishError(cat, f"tiktok publish failed: {reason}", code=reason, raw=st)
            if asyncio.get_event_loop().time() > deadline:
                raise PublishError("ambiguous", "tiktok publish still processing after 15 minutes", code="publish_timeout", raw=st)
            await heartbeat(state)
            await asyncio.sleep(5)

    async def _fetch_status(self, tokens: TokenSet, publish_id: str, aid: Any) -> dict[str, Any]:
        body = await self.http.post_json(f"{API}/post/publish/status/fetch/", headers=self._headers(tokens), json={"publish_id": publish_id},
                                         write=False, retries=3, account_id=aid, error_mapper=_tt_error)
        return body.get("data") or {}

    def _result(self, state: dict[str, Any], account: Any) -> PublishResult:
        post_ids = state.get("post_ids") or []
        ext = post_ids[0] if post_ids else state["publish_id"]
        handle = account_attr(account, "handle")
        url = f"https://www.tiktok.com/@{handle}/video/{post_ids[0]}" if post_ids and handle else None
        return PublishResult(external_id=str(ext), external_url=url, published_at=self.now(),
                             raw={"publish_id": state.get("publish_id"), "mode": state.get("mode"), "status": state.get("final_status"),
                                  "note": "inbox upload: the creator completes the post in the TikTok app" if state.get("mode") == "inbox_upload" else None})

    async def get_status(self, account: Any, tokens: TokenSet, state: dict[str, Any]) -> dict[str, Any] | None:
        if not state.get("publish_id"):
            return None
        st = await self._fetch_status(tokens, state["publish_id"], account_attr(account, "id"))
        status = st.get("status")
        if status in ("PUBLISH_COMPLETE", "SEND_TO_USER_INBOX"):
            ids = st.get("publicaly_available_post_id") or []
            return {"status": "published", "external_id": str(ids[0]) if ids else state["publish_id"], "raw": st}
        if status == "FAILED":
            return {"status": "failed", "message": st.get("fail_reason")}
        return {"status": "pending"}

    # ---- reads -------------------------------------------------------------------------------------------
    async def get_post(self, account: Any, tokens: TokenSet, external_id: str) -> RemotePost:
        body = await self.http.post_json(f"{API}/video/query/?fields={VIDEO_FIELDS}", headers=self._headers(tokens), json={"filters": {"video_ids": [external_id]}},
                                         write=False, retries=3, account_id=account_attr(account, "id"), error_mapper=_tt_error)
        vids = (body.get("data") or {}).get("videos") or []
        if not vids:
            raise PublishError("permanent", "video not found (inbox drafts are not listed until posted)", code="not_found", raw=body)
        v = vids[0]
        return RemotePost(external_id=str(v["id"]), text=v.get("video_description") or v.get("title"), created_at=_ts(v.get("create_time")), url=v.get("share_url"), raw=v)

    async def delete_post(self, account: Any, tokens: TokenSet, external_id: str) -> None:
        raise PublishError("unsupported", "TikTok's Content Posting API has no delete endpoint", code="platform_does_not_support_delete")

    async def find_recent_posts(self, account: Any, tokens: TokenSet, since: datetime) -> list[RemotePost]:
        body = await self.http.post_json(f"{API}/video/list/?fields={VIDEO_FIELDS}", headers=self._headers(tokens), json={"max_count": 20}, write=False,
                                         retries=3, account_id=account_attr(account, "id"), error_mapper=_tt_error)
        out = []
        for v in (body.get("data") or {}).get("videos") or []:
            ts = _ts(v.get("create_time"))
            if ts and ts < since:
                continue
            out.append(RemotePost(external_id=str(v["id"]), text=v.get("video_description") or v.get("title"), created_at=ts, url=v.get("share_url"), raw=v))
        return out

    # ---- metrics -----------------------------------------------------------------------------------------
    async def get_post_metrics(self, account: Any, tokens: TokenSet, external_id: str) -> dict[str, Any]:
        from app.analytics.normalize import normalize_post_metrics
        raw: dict[str, Any] = {"video": {}, "mode": self._mode(account)}
        try:
            body = await self.http.post_json(f"{API}/video/query/?fields={VIDEO_FIELDS}", headers=self._headers(tokens), json={"filters": {"video_ids": [external_id]}},
                                             write=False, retries=3, account_id=account_attr(account, "id"), error_mapper=_tt_error)
            vids = (body.get("data") or {}).get("videos") or []
            raw["video"] = vids[0] if vids else {}
        except PublishError as e:
            if e.category in ("auth", "rate_limited"):
                raise
            raw["error"] = {"category": e.category, "code": e.code}
        return normalize_post_metrics("tiktok", raw)

    async def get_account_metrics(self, account: Any, tokens: TokenSet) -> dict[str, Any]:
        from app.analytics.normalize import normalize_account_metrics
        body = await self.http.get_json(f"{API}/user/info/?fields={USER_FIELDS}", headers=self._headers(tokens), account_id=account_attr(account, "id"),
                                        error_mapper=_tt_error)
        return normalize_account_metrics("tiktok", {"user": (body.get("data") or {}).get("user") or {}})

    def rate_limits(self) -> list[dict[str, Any]]:
        return [{"endpoint": "post init", "per_user_per_min": 6}, {"endpoint": "creator_info", "per_user_per_min": 20},
                {"endpoint": "status/fetch", "per_user_per_min": 30}, {"endpoint": "user/info, video/list, video/query", "per_min": 600},
                {"scope": "direct posts per creator per day", "limit": 15}]


def _ts(v: Any) -> datetime | None:
    try:
        return datetime.fromtimestamp(int(v), tz=UTC) if v else None
    except (TypeError, ValueError):
        return None

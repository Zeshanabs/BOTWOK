"""X adapter (doc 27 §27.5, docs/platforms/linkedin-x-pinterest-gbp.md §2). VERIFIED_AT 2026-10-08.

OAuth 2.0 PKCE (``tweet.read tweet.write users.read media.write offline.access``), 2-hour access tokens refreshed via
``offline.access``. ``POST https://api.x.com/2/tweets`` for posts; threads are sequential self-replies with per-segment
ids kept in ``state["segment_external_ids"]`` so a retry resumes at the first missing segment. Media: one-shot
``POST /2/media/upload`` for images; ``initialize/append/finalize/status`` for video. Quote posts are Enterprise-only
→ validation error. A post containing a URL costs $0.20 instead of $0.015 → ``url_post_costs_0_20`` warning.
Owner-only metrics (``non_public_metrics``/``organic_metrics``) exist for 30 days after creation.
"""
from __future__ import annotations

import asyncio
import base64
from datetime import UTC, datetime, timedelta
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
    find_urls,
    heartbeat,
    issue,
    load_media_bytes,
    media_info,
    result,
    save_state,
)

VERIFIED_AT = "2026-10-08"
AUTH_URL = "https://x.com/i/oauth2/authorize"
TOKEN_URL = "https://api.x.com/2/oauth2/token"
REVOKE_URL = "https://api.x.com/2/oauth2/revoke"
API = "https://api.x.com/2"
SCOPES = ["tweet.read", "tweet.write", "users.read", "media.write", "offline.access"]
MAX_CHARS = 280
URL_WEIGHT = 23           # every URL is wrapped by t.co and counts as 23 characters
MAX_MEDIA = 4
COST_POST_USD = 0.015
COST_POST_WITH_URL_USD = 0.20
COST_DELETE_USD = 0.010
COST_POST_READ_USD = 0.005
COST_OWNED_READ_USD = 0.001
PRIVATE_METRICS_DAYS = 30
VIDEO_CHUNK = 4 * 1024 * 1024


def weighted_length(text: str) -> int:
    """280-char budget: URLs count 23; everything else by code point (X weights some CJK/emoji at 2 — approximation)."""
    n = len(text)
    for u in find_urls(text):
        n += URL_WEIGHT - len(u)
    return n


def _x_error(resp: httpx.Response) -> PublishError | None:
    try:
        body = resp.json()
    except ValueError:
        return None
    if not isinstance(body, dict):
        return None
    title = (body.get("title") or body.get("error") or "")
    detail = body.get("detail") or body.get("error_description") or ""
    msg = f"{title}: {detail}".strip(": ")
    if resp.status_code == 401 or body.get("error") in ("invalid_request", "invalid_grant", "invalid_client"):
        return PublishError("auth", f"x auth: {msg}", code=str(body.get("error") or title or 401), raw=body)
    if resp.status_code == 403:
        low = (title + " " + detail).lower()
        if "duplicate" in low:
            return PublishError("permanent", f"x duplicate content: {msg}", code="duplicate_content", raw=body)
        if "oauth" in low or "scope" in low or "unauthorized" in low or "not authorized" in low:
            return PublishError("auth", f"x permission: {msg}", code=str(title or 403), raw=body)
        return PublishError("permanent", f"x forbidden: {msg}", code=str(title or 403), raw=body)
    if resp.status_code == 400 and body.get("errors"):
        return PublishError("validation", f"x rejected: {body['errors'][0].get('message', msg)}", code="400", raw=body)
    return None


class XAdapter(BaseAdapter):
    platform = "x"
    verified_at = VERIFIED_AT
    VERIFIED_AT = VERIFIED_AT
    docs = ["https://docs.x.com/x-api/posts/create-post", "https://docs.x.com/x-api/media/introduction",
            "https://docs.x.com/resources/fundamentals/authentication/oauth-2-0/authorization-code"]

    def _basic(self) -> dict[str, str]:
        raw = f"{settings.x_client_id}:{settings.x_client_secret}".encode()
        return {"Authorization": "Basic " + base64.b64encode(raw).decode(), "Content-Type": "application/x-www-form-urlencoded"}

    def _headers(self, tokens: TokenSet, **extra: str) -> dict[str, str]:
        return {"Authorization": f"Bearer {tokens.access_token}", **extra}

    def capabilities(self, account: Any) -> Capabilities:
        return Capabilities(
            formats=["text", "image", "carousel", "video", "short_video", "poll", "link"],
            max_text=MAX_CHARS, max_media=MAX_MEDIA, native_schedule=False, can_delete=True, supports_alt_text=True,
            limits={"post_create_per_user_15min": 100, "post_create_per_app_24h": 10_000, "delete_per_user_15min": 50,
                    "media_upload_per_user_15min": 500, "image_max_bytes": 5 * 1024**2, "gif_max_bytes": 15 * 1024**2,
                    "video_max_bytes": 8 * 1024**3, "video_max_s": 1200, "poll_options": [2, 4], "poll_minutes": [5, 10080],
                    "cost_post_usd": COST_POST_USD, "cost_post_with_url_usd": COST_POST_WITH_URL_USD,
                    "private_metrics_days": PRIVATE_METRICS_DAYS},
            notes=["threads = self-reply chains (self-reply exemption from the summoned rule is a secondary source; verify in sandbox)",
                   "quote posts Enterprise-only", "likes/follows removed from self-serve 2026-04", "access tokens 2 h (refresh with offline.access)"],
        )

    # ---- OAuth -------------------------------------------------------------------------------------------
    def auth_url(self, state: str, redirect_uri: str, flavor: str = "default", code_challenge: str | None = None) -> str:
        q = {"response_type": "code", "client_id": settings.x_client_id, "redirect_uri": redirect_uri, "scope": " ".join(SCOPES),
             "state": state, "code_challenge": code_challenge or "", "code_challenge_method": "S256"}
        return f"{AUTH_URL}?{urlencode(q)}"

    async def exchange_code(self, code: str, redirect_uri: str, code_verifier: str | None = None) -> TokenSet:
        data = {"code": code, "grant_type": "authorization_code", "client_id": settings.x_client_id,
                "redirect_uri": redirect_uri, "code_verifier": code_verifier or ""}
        body = await self.http.post_json(TOKEN_URL, data=data, headers=self._basic(), error_mapper=_x_error)
        return self._tokens_from(body)

    def _tokens_from(self, body: dict[str, Any], previous: TokenSet | None = None) -> TokenSet:
        return TokenSet(access_token=body["access_token"], refresh_token=body.get("refresh_token") or (previous.refresh_token if previous else None),
                        expires_at=self.expires_in(body.get("expires_in", 7200)),
                        scopes=(body.get("scope") or "").split() or (previous.scopes if previous else []),
                        extra=dict(previous.extra) if previous else {})

    async def refresh(self, tokens: TokenSet) -> TokenSet:
        if not tokens.refresh_token:
            raise PublishError("unsupported", "no refresh token (offline.access not granted)", code="no_refresh")
        data = {"grant_type": "refresh_token", "refresh_token": tokens.refresh_token, "client_id": settings.x_client_id}
        body = await self.http.post_json(TOKEN_URL, data=data, headers=self._basic(), error_mapper=_x_error)
        return self._tokens_from(body, previous=tokens)   # refresh tokens rotate → always persist the new one

    async def revoke(self, tokens: TokenSet) -> None:
        try:
            await self.http.post_json(REVOKE_URL, data={"token": tokens.access_token, "token_type_hint": "access_token",
                                                        "client_id": settings.x_client_id}, headers=self._basic(), retries=1)
        except PublishError:
            return None

    async def list_connectable_accounts(self, tokens: TokenSet, flavor: str = "default") -> list[ConnectableAccount]:
        body = await self.http.get_json(f"{API}/users/me?user.fields=profile_image_url,username,public_metrics",
                                        headers=self._headers(tokens), error_mapper=_x_error)
        d = body["data"]
        return [ConnectableAccount(external_id=d["id"], display_name=d.get("name") or d["username"], handle=d.get("username"),
                                   avatar_url=d.get("profile_image_url"), account_type="user",
                                   extra={"public_metrics": d.get("public_metrics", {})})]

    async def probe(self, account: Any, tokens: TokenSet) -> dict[str, Any]:
        required = {"tweet.write", "tweet.read", "users.read", "media.write"}
        granted = set(tokens.scopes or account_attr(account, "scopes", []) or [])
        health: dict[str, Any] = {"token_valid": False, "scopes_missing": sorted(required - granted) if granted else [],
                                  "limits_remaining": None, "expires_at": tokens.expires_at.isoformat() if tokens.expires_at else None,
                                  "refreshable": bool(tokens.refresh_token)}
        try:
            resp = await self.http.request("GET", f"{API}/users/me?user.fields=public_metrics", headers=self._headers(tokens),
                                           account_id=account_attr(account, "id"), error_mapper=_x_error)
            health["token_valid"] = True
            rem = resp.headers.get("x-rate-limit-remaining")
            health["limits_remaining"] = {"users_me_15min": int(rem)} if rem else None
            health["followers"] = (resp.json().get("data", {}).get("public_metrics") or {}).get("followers_count")
        except PublishError as e:
            health["error"] = {"category": e.category, "code": e.code, "message": e.message}
            if e.category != "auth":
                raise
        return health

    # ---- validation --------------------------------------------------------------------------------------
    async def validate_content(self, account: Any, req: PublishRequest) -> ValidationResult:
        issues = []
        segments = self._segments(req)
        for i, seg in enumerate(segments):
            n = weighted_length(seg)
            if n > MAX_CHARS:
                issues.append(issue("x_text_too_long", f"segment {i + 1} is {n}/{MAX_CHARS} weighted chars (URLs count 23)",
                                    f"segments[{i}]" if req.segments else "text"))
            if not seg.strip() and not (i == 0 and req.media):
                issues.append(issue("x_empty_segment", f"segment {i + 1} is empty", f"segments[{i}]"))
        if any(find_urls(s) for s in segments):
            issues.append(issue("url_post_costs_0_20", "a post containing a URL costs $0.20 instead of $0.015 (pay-per-use)",
                                "text", severity="warning"))
        if req.metadata.get("quote_tweet_id") or req.metadata.get("quote_post_id"):
            issues.append(issue("quote_posts_unsupported", "quote posts require an Enterprise plan (removed from self-serve 2026-04)", "quote_tweet_id"))
        if req.metadata.get("reply_to_id") or req.metadata.get("in_reply_to_tweet_id"):
            issues.append(issue("x_reply_summoned_only", "replies to other accounts are allowed only when summoned (since 2026-02-23)",
                                "reply_to_id", severity="warning"))
        images, videos, _docs = self._media_kinds(req)
        if len(req.media) > MAX_MEDIA:
            issues.append(issue("x_too_many_media", f"at most {MAX_MEDIA} media per post", "media"))
        if videos and (len(videos) > 1 or images):
            issues.append(issue("x_video_alone", "a video cannot be combined with other media", "media"))
        if _docs:
            issues.append(issue("x_unsupported_media", "documents are not supported", "media"))
        for i, m in enumerate(req.media):
            info = media_info(req, i)
            size = info.get("bytes") or 0
            mime = (m.mime or "").lower()
            if m in images:
                limit = 15 * 1024**2 if mime == "image/gif" else 5 * 1024**2
                if size > limit:
                    issues.append(issue("x_image_too_large", f"image exceeds {limit // 1024**2} MB", f"media[{i}]"))
                if mime not in ("image/jpeg", "image/png", "image/gif", "image/webp"):
                    issues.append(issue("x_image_format", "images must be JPG, PNG, GIF or WEBP", f"media[{i}]"))
                if not (m.alt_text or info.get("alt_text")):
                    issues.append(issue("alt_text_missing", "image has no alt text", f"media[{i}]", severity="warning"))
            if m in videos:
                if size > 8 * 1024**3:
                    issues.append(issue("x_video_too_large", "video exceeds 8 GB (16 GB Premium)", f"media[{i}]"))
                if (info.get("duration_ms") or 0) > 1200 * 1000:
                    issues.append(issue("x_video_too_long", "video exceeds 20 minutes (125 min Premium)", f"media[{i}]"))
        poll = req.metadata.get("poll")
        if poll:
            opts = poll.get("options") or []
            if not 2 <= len(opts) <= 4 or any(not 1 <= len(str(o)) <= 25 for o in opts):
                issues.append(issue("x_poll_shape", "polls need 2–4 options of 1–25 characters", "poll"))
            dur = int(poll.get("duration_minutes") or 1440)
            if not 5 <= dur <= 10080:
                issues.append(issue("x_poll_duration", "poll duration must be 5–10080 minutes", "poll"))
            if req.media:
                issues.append(issue("x_poll_no_media", "polls cannot carry media", "media"))
        return result(issues)

    # ---- media -------------------------------------------------------------------------------------------
    async def _upload_media(self, tokens: TokenSet, req: PublishRequest, state: dict[str, Any], account_id: Any) -> list[str]:
        ids: list[str] = state.setdefault("media_ids", [])
        for i, m in enumerate(req.media[:MAX_MEDIA]):
            if i < len(ids):
                continue
            data = await load_media_bytes(m)
            mime = (m.mime or "application/octet-stream").lower()
            if mime.startswith("video/"):
                media_id = await self._upload_video(tokens, data, mime, state, account_id)
            else:
                category = "tweet_gif" if mime == "image/gif" else "tweet_image"
                body = await self.http.post_json(f"{API}/media/upload", headers=self._headers(tokens), timeout_s=120,
                                                 data={"media_category": category, "media_type": mime},
                                                 files={"media": ("media", data, mime)}, write=True, account_id=account_id,
                                                 error_mapper=_x_error)
                media_id = str((body.get("data") or body).get("id"))
            alt = m.alt_text
            if alt and not mime.startswith("video/"):
                try:
                    await self.http.post_json(f"{API}/media/metadata", headers=self._headers(tokens),
                                              json={"id": media_id, "metadata": {"alt_text": {"text": alt[:1000]}}}, error_mapper=_x_error)
                except PublishError:
                    pass   # alt text is best effort
            ids.append(media_id)
            await save_state(state)
            await heartbeat(state)
        return ids

    async def _upload_video(self, tokens: TokenSet, data: bytes, mime: str, state: dict[str, Any], account_id: Any) -> str:
        init = await self.http.post_json(f"{API}/media/upload/initialize", headers=self._headers(tokens),
                                         json={"media_type": mime, "total_bytes": len(data), "media_category": "tweet_video"},
                                         write=True, account_id=account_id, error_mapper=_x_error)
        media_id = str((init.get("data") or init).get("id"))
        for idx, start in enumerate(range(0, len(data), VIDEO_CHUNK)):
            chunk = data[start:start + VIDEO_CHUNK]
            await self.http.post_json(f"{API}/media/upload/{media_id}/append", headers=self._headers(tokens), timeout_s=300,
                                      data={"segment_index": str(idx)}, files={"media": ("chunk", chunk, "application/octet-stream")},
                                      write=True, account_id=account_id, error_mapper=_x_error)
            await heartbeat(state)
        fin = await self.http.post_json(f"{API}/media/upload/{media_id}/finalize", headers=self._headers(tokens), write=True,
                                        account_id=account_id, error_mapper=_x_error)
        info = (fin.get("data") or fin).get("processing_info") or {}
        deadline = asyncio.get_event_loop().time() + 600
        while info.get("state") in ("pending", "in_progress"):
            if asyncio.get_event_loop().time() > deadline:
                raise PublishError("transient", "video processing did not finish in 10 minutes", code="media_processing_timeout")
            await asyncio.sleep(max(1, int(info.get("check_after_secs") or 5)))
            st = await self.http.get_json(f"{API}/media/upload?command=STATUS&media_id={media_id}", headers=self._headers(tokens),
                                          account_id=account_id, error_mapper=_x_error)
            info = (st.get("data") or st).get("processing_info") or {}
            await heartbeat(state)
        if info.get("state") == "failed":
            err = info.get("error") or {}
            raise PublishError("permanent", f"video processing failed: {err.get('message', err)}", code="media_processing_failed", raw=info)
        return media_id

    # ---- publish -----------------------------------------------------------------------------------------
    async def publish(self, account: Any, tokens: TokenSet, req: PublishRequest, state: dict[str, Any]) -> PublishResult:
        account_id = account_attr(account, "id")
        segments = self._segments(req)
        done: list[str] = state.setdefault("segment_external_ids", [])
        media_ids = await self._upload_media(tokens, req, state, account_id) if req.media and len(done) == 0 else state.get("media_ids", [])
        handle = account_attr(account, "handle") or "i"
        for i, seg in enumerate(segments):
            if i < len(done):
                continue
            body: dict[str, Any] = {"text": seg}
            if i == 0:
                if media_ids:
                    body["media"] = {"media_ids": media_ids}
                if req.metadata.get("poll"):
                    poll = req.metadata["poll"]
                    body["poll"] = {"options": [str(o) for o in poll["options"][:4]], "duration_minutes": int(poll.get("duration_minutes") or 1440)}
                if req.metadata.get("reply_settings"):
                    body["reply_settings"] = req.metadata["reply_settings"]
            else:
                body["reply"] = {"in_reply_to_tweet_id": done[i - 1]}
            for flag in ("made_with_ai", "paid_partnership"):
                if req.metadata.get(flag) is not None:
                    body[flag] = bool(req.metadata[flag])
            await heartbeat(state)
            resp_body = await self.http.post_json(f"{API}/tweets", headers=self._headers(tokens), json=body, write=True,
                                                  account_id=account_id, error_mapper=_x_error)
            tweet_id = str((resp_body.get("data") or {}).get("id") or "")
            if not tweet_id:
                raise PublishError("ambiguous", "X returned no post id", code="no_post_id", raw=resp_body)
            done.append(tweet_id)
            state["segment_external_ids"] = done
            await save_state(state)
        first = done[0]
        cost = COST_POST_WITH_URL_USD if any(find_urls(s) for s in segments) else COST_POST_USD
        return PublishResult(external_id=first, external_url=f"https://x.com/{handle}/status/{first}", published_at=self.now(),
                             segments=[{"index": i, "external_id": tid, "url": f"https://x.com/{handle}/status/{tid}"} for i, tid in enumerate(done)],
                             raw={"cost_usd": round(cost * len(done), 4), "segments": len(done)})

    # ---- reads / delete ----------------------------------------------------------------------------------
    async def get_post(self, account: Any, tokens: TokenSet, external_id: str) -> RemotePost:
        body = await self.http.get_json(f"{API}/tweets/{external_id}?tweet.fields=created_at,text,public_metrics",
                                        headers=self._headers(tokens), account_id=account_attr(account, "id"), error_mapper=_x_error)
        d = body.get("data") or {}
        if not d:
            raise PublishError("permanent", "post not found", code="not_found", raw=body)
        return RemotePost(external_id=d["id"], text=d.get("text"), created_at=_iso(d.get("created_at")),
                          url=f"https://x.com/i/status/{d['id']}", raw=d)

    async def delete_post(self, account: Any, tokens: TokenSet, external_id: str) -> None:
        await self.http.request("DELETE", f"{API}/tweets/{external_id}", headers=self._headers(tokens),
                                account_id=account_attr(account, "id"), ok=(200, 204, 404), error_mapper=_x_error)

    async def find_recent_posts(self, account: Any, tokens: TokenSet, since: datetime) -> list[RemotePost]:
        uid = account_attr(account, "external_id")
        start = since.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
        body = await self.http.get_json(f"{API}/users/{uid}/tweets?max_results=20&tweet.fields=created_at,text&start_time={start}",
                                        headers=self._headers(tokens), account_id=account_attr(account, "id"), error_mapper=_x_error)
        return [RemotePost(external_id=d["id"], text=d.get("text"), created_at=_iso(d.get("created_at")),
                           url=f"https://x.com/i/status/{d['id']}", raw=d) for d in body.get("data", [])]

    # ---- metrics -----------------------------------------------------------------------------------------
    async def get_post_metrics(self, account: Any, tokens: TokenSet, external_id: str) -> dict[str, Any]:
        from app.analytics.normalize import normalize_post_metrics
        account_id = account_attr(account, "id")
        raw: dict[str, Any] = {"cost_usd": COST_OWNED_READ_USD}
        fields = "created_at,public_metrics,non_public_metrics,organic_metrics"
        try:
            body = await self.http.get_json(f"{API}/tweets/{external_id}?tweet.fields={fields}", headers=self._headers(tokens),
                                            account_id=account_id, error_mapper=_x_error)
        except PublishError as e:
            if e.category == "auth":
                raise
            # non-public metrics are rejected for posts older than 30 days → fall back to public metrics only
            body = await self.http.get_json(f"{API}/tweets/{external_id}?tweet.fields=created_at,public_metrics",
                                            headers=self._headers(tokens), account_id=account_id, error_mapper=_x_error)
            raw["private_metrics_window_closed"] = True
        d = body.get("data") or {}
        raw.update({k: d.get(k) for k in ("public_metrics", "non_public_metrics", "organic_metrics", "created_at")})
        created = _iso(d.get("created_at"))
        if created and self.now() - created > timedelta(days=PRIVATE_METRICS_DAYS):
            raw["private_metrics_window_closed"] = True
        return normalize_post_metrics("x", raw)

    async def get_account_metrics(self, account: Any, tokens: TokenSet) -> dict[str, Any]:
        from app.analytics.normalize import normalize_account_metrics
        body = await self.http.get_json(f"{API}/users/me?user.fields=public_metrics", headers=self._headers(tokens),
                                        account_id=account_attr(account, "id"), error_mapper=_x_error)
        return normalize_account_metrics("x", {"public_metrics": (body.get("data") or {}).get("public_metrics") or {},
                                               "cost_usd": COST_OWNED_READ_USD})

    async def get_public_profile(self, tokens: TokenSet, username: str) -> dict[str, Any]:
        body = await self.http.get_json(f"{API}/users/by/username/{username}?user.fields=public_metrics,description,created_at",
                                        headers=self._headers(tokens), error_mapper=_x_error)
        d = body.get("data") or {}
        return {"username": d.get("username"), "name": d.get("name"), "id": d.get("id"), "public_metrics": d.get("public_metrics"),
                "availability": "official_api", "cost_usd": 0.01}

    def rate_limits(self) -> list[dict[str, Any]]:
        return [{"endpoint": "POST /2/tweets", "per_user_15min": 100, "per_app_24h": 10_000},
                {"endpoint": "DELETE /2/tweets/:id", "per_user_15min": 50},
                {"endpoint": "POST /2/media/upload", "per_user_15min": 500, "per_app_24h": 50_000}]


def _iso(v: Any) -> datetime | None:
    if not v:
        return None
    try:
        return datetime.fromisoformat(str(v).replace("Z", "+00:00"))
    except ValueError:
        return None


"""Pinterest adapter (doc 27 §27.8, docs/platforms/linkedin-x-pinterest-gbp.md §3). VERIFIED_AT 2026-10-08.

OAuth 2.0 code flow (``boards:read boards:write pins:read pins:write user_accounts:read``), 30-day access tokens with
a continuous 60-day refresh token. ``POST /v5/pins`` with ``media_source`` image_url / multiple_image_urls (2–5) /
video (``POST /v5/media`` register → upload → poll → ``video_id``). No text-only pins, no scheduling; delete supported.
Pin analytics ``GET /v5/pins/{id}/analytics`` (≤ 90-day lookback) plus ``?pin_metrics=true`` lifetime metrics.
Trial access: pins are sandbox entities visible only to their creator.
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
    heartbeat,
    issue,
    load_media_bytes,
    media_info,
    result,
    save_state,
)

VERIFIED_AT = "2026-10-08"
AUTH_URL = "https://www.pinterest.com/oauth/"
API = "https://api.pinterest.com/v5"
TOKEN_URL = f"{API}/oauth/token"
SCOPES = ["boards:read", "boards:write", "pins:read", "pins:write", "user_accounts:read"]
TITLE_MAX, DESC_MAX, LINK_MAX, ALT_MAX = 100, 800, 2048, 500
CAROUSEL_RANGE = (2, 5)
PIN_METRICS = "IMPRESSION,PIN_CLICK,OUTBOUND_CLICK,SAVE,TOTAL_COMMENTS,TOTAL_REACTIONS,USER_FOLLOW,PROFILE_VISIT"


def _pin_error(resp: httpx.Response) -> PublishError | None:
    try:
        body = resp.json()
    except ValueError:
        return None
    if not isinstance(body, dict):
        return None
    code = body.get("code")
    msg = body.get("message") or body.get("error_description") or ""
    if resp.status_code == 401 or body.get("error") in ("invalid_grant", "invalid_token"):
        return PublishError("auth", f"pinterest auth: {msg}", code=str(code or body.get("error") or 401), raw=body)
    if resp.status_code == 403:
        low = msg.lower()
        if "scope" in low or "permission" in low or "authorized" in low:
            return PublishError("auth", f"pinterest permission: {msg}", code=str(code or 403), raw=body)
        return PublishError("permanent", f"pinterest forbidden: {msg}", code=str(code or 403), raw=body)
    if resp.status_code == 400:
        return PublishError("validation", f"pinterest rejected: {msg}", code=str(code or 400), raw=body)
    return None


class PinterestAdapter(BaseAdapter):
    platform = "pinterest"
    verified_at = VERIFIED_AT
    VERIFIED_AT = VERIFIED_AT
    docs = ["https://developers.pinterest.com/docs/getting-started/set-up-authentication-and-authorization/",
            "https://developers.pinterest.com/docs/key-concepts/access-tiers/", "https://developers.pinterest.com/docs/reference/rate-limits/"]

    def _basic(self) -> dict[str, str]:
        raw = f"{settings.pinterest_app_id}:{settings.pinterest_app_secret}".encode()
        return {"Authorization": "Basic " + base64.b64encode(raw).decode(), "Content-Type": "application/x-www-form-urlencoded"}

    def _headers(self, tokens: TokenSet, **extra: str) -> dict[str, str]:
        return {"Authorization": f"Bearer {tokens.access_token}", **extra}

    def capabilities(self, account: Any) -> Capabilities:
        return Capabilities(
            formats=["image", "carousel", "video", "link"], max_text=DESC_MAX, max_media=CAROUSEL_RANGE[1], native_schedule=False, can_delete=True,
            supports_alt_text=True,
            limits={"title_chars": TITLE_MAX, "description_chars": DESC_MAX, "link_chars": LINK_MAX, "alt_text_chars": ALT_MAX, "carousel": list(CAROUSEL_RANGE),
                    "trial_requests_per_day": 1000, "standard_org_write_per_min": 100, "analytics_lookback_days": 90, "access_token_days": 30,
                    "refresh_token_days": 60},
            notes=["pins need media (no text-only, no polls)", "board_id required", "Trial access: pins visible only to the creator (sandbox)",
                   "video specs unverified", "pin editing is beta"],
        )

    # ---- OAuth -------------------------------------------------------------------------------------------
    def auth_url(self, state: str, redirect_uri: str, flavor: str = "default", code_challenge: str | None = None) -> str:
        q = {"client_id": settings.pinterest_app_id, "redirect_uri": redirect_uri, "response_type": "code", "scope": ",".join(SCOPES), "state": state}
        return f"{AUTH_URL}?{urlencode(q)}"

    async def exchange_code(self, code: str, redirect_uri: str, code_verifier: str | None = None) -> TokenSet:
        data = {"grant_type": "authorization_code", "code": code, "redirect_uri": redirect_uri, "continuous_refresh": "true"}
        body = await self.http.post_json(TOKEN_URL, data=data, headers=self._basic(), error_mapper=_pin_error)
        return self._tokens_from(body)

    def _tokens_from(self, body: dict[str, Any], previous: TokenSet | None = None) -> TokenSet:
        return TokenSet(access_token=body["access_token"], refresh_token=body.get("refresh_token") or (previous.refresh_token if previous else None),
                        expires_at=self.expires_in(body.get("expires_in", 30 * 86400)),
                        refresh_expires_at=self.expires_in(body["refresh_token_expires_in"]) if body.get("refresh_token_expires_in") else (previous.refresh_expires_at if previous else None),
                        scopes=(body.get("scope") or "").replace(",", " ").split() or (previous.scopes if previous else []),
                        extra=dict(previous.extra) if previous else {})

    async def refresh(self, tokens: TokenSet) -> TokenSet:
        if not tokens.refresh_token:
            raise PublishError("unsupported", "no Pinterest refresh token stored", code="no_refresh")
        data = {"grant_type": "refresh_token", "refresh_token": tokens.refresh_token, "scope": ",".join(tokens.scopes or SCOPES)}
        body = await self.http.post_json(TOKEN_URL, data=data, headers=self._basic(), error_mapper=_pin_error)
        return self._tokens_from(body, previous=tokens)

    async def list_connectable_accounts(self, tokens: TokenSet, flavor: str = "default") -> list[ConnectableAccount]:
        me = await self.http.get_json(f"{API}/user_account", headers=self._headers(tokens), error_mapper=_pin_error)
        ext = str(me.get("id") or me.get("username"))
        return [ConnectableAccount(external_id=ext, display_name=me.get("business_name") or me.get("username") or ext, handle=me.get("username"),
                                   avatar_url=me.get("profile_image"), account_type=(me.get("account_type") or "").lower() or None,
                                   extra={"follower_count": me.get("follower_count"), "monthly_views": me.get("monthly_views")})]

    async def probe(self, account: Any, tokens: TokenSet) -> dict[str, Any]:
        required = {"pins:write", "boards:read"}
        granted = set(tokens.scopes or account_attr(account, "scopes", []) or [])
        health: dict[str, Any] = {"token_valid": False, "scopes_missing": sorted(required - granted) if granted else [], "limits_remaining": None,
                                  "expires_at": tokens.expires_at.isoformat() if tokens.expires_at else None, "refreshable": bool(tokens.refresh_token)}
        try:
            resp = await self.http.request("GET", f"{API}/user_account", headers=self._headers(tokens), account_id=account_attr(account, "id"), error_mapper=_pin_error)
            me = resp.json()
            health["token_valid"] = True
            health["followers"] = me.get("follower_count")
            health["account_type"] = me.get("account_type")
            rem = resp.headers.get("x-ratelimit-remaining")
            health["limits_remaining"] = {"requests": int(rem)} if rem else None
            if (me.get("account_type") or "").upper() == "PINNER":
                health["warning"] = "personal account: some analytics need a business account"
        except PublishError as e:
            health["error"] = {"category": e.category, "code": e.code, "message": e.message}
            if e.category != "auth":
                raise
        return health

    # ---- validation --------------------------------------------------------------------------------------
    async def validate_content(self, account: Any, req: PublishRequest) -> ValidationResult:
        issues = []
        md = req.metadata
        images, videos, docs = self._media_kinds(req)
        if not md.get("board_id") and not md.get("board_section_id"):
            issues.append(issue("pinterest_board_required", "a board_id (or board_section_id) is required", "board_id"))
        if not req.media:
            issues.append(issue("pinterest_media_required", "pins need an image, 2–5 images or a video", "media"))
        if docs:
            issues.append(issue("pinterest_unsupported_media", "documents are not supported", "media"))
        if videos and (len(videos) > 1 or images):
            issues.append(issue("pinterest_one_video", "a video pin carries exactly one video", "media"))
        if len(images) > 1 and not CAROUSEL_RANGE[0] <= len(images) <= CAROUSEL_RANGE[1]:
            issues.append(issue("pinterest_carousel_count", f"carousels need {CAROUSEL_RANGE[0]}–{CAROUSEL_RANGE[1]} images", "media"))
        title = md.get("title") or ""
        if len(title) > TITLE_MAX:
            issues.append(issue("pinterest_title_too_long", f"title is {len(title)}/{TITLE_MAX}", "title"))
        desc = md.get("description") if md.get("description") is not None else (req.text or "")
        if len(desc) > DESC_MAX:
            issues.append(issue("pinterest_description_too_long", f"description is {len(desc)}/{DESC_MAX}", "description"))
        if len(md.get("link") or "") > LINK_MAX:
            issues.append(issue("pinterest_link_too_long", f"link exceeds {LINK_MAX} characters", "link"))
        for i, m in enumerate(req.media):
            info = media_info(req, i)
            alt = m.alt_text or info.get("alt_text") or ""
            if len(alt) > ALT_MAX:
                issues.append(issue("pinterest_alt_text_too_long", f"alt text exceeds {ALT_MAX}", f"media[{i}]"))
            if m in images and not alt:
                issues.append(issue("alt_text_missing", "image has no alt text", f"media[{i}]", "warning"))
            if m in images and not m.url and not m.bytes_loader:
                issues.append(issue("pinterest_media_source", "image needs a public URL or bytes (base64)", f"media[{i}]"))
        if md.get("poll"):
            issues.append(issue("pinterest_no_polls", "Pinterest has no polls", "poll"))
        caps = account_attr(account, "capabilities", {}) or {}
        if caps.get("access_tier") == "trial":
            issues.append(issue("pinterest_trial_private", "Trial access: pins are visible only to their creator until Standard access is granted", "account", "warning"))
        return result(issues)

    # ---- publish -----------------------------------------------------------------------------------------
    async def publish(self, account: Any, tokens: TokenSet, req: PublishRequest, state: dict[str, Any]) -> PublishResult:
        if state.get("pin_id"):
            return self._result(state["pin_id"], state.get("published_at"))
        aid = account_attr(account, "id")
        md = req.metadata
        images, videos, _docs = self._media_kinds(req)
        body: dict[str, Any] = {"title": (md.get("title") or "")[:TITLE_MAX] or None,
                                "description": (md.get("description") if md.get("description") is not None else (req.text or ""))[:DESC_MAX],
                                "link": md.get("link"), "board_id": md.get("board_id"), "board_section_id": md.get("board_section_id"),
                                "alt_text": (req.media[0].alt_text if req.media else None)}
        if md.get("ai_disclosures"):
            body["ai_disclosures"] = md["ai_disclosures"]
        if videos:
            media_id = await self._upload_video(tokens, videos[0], state, aid)
            cover = md.get("cover_image_url") or (images[0].url if images else None)
            src: dict[str, Any] = {"source_type": "video_id", "media_id": media_id}
            if cover:
                src["cover_image_url"] = cover
            elif md.get("cover_image_key_frame_time") is not None:
                src["cover_image_key_frame_time"] = int(md["cover_image_key_frame_time"])
            else:
                src["cover_image_key_frame_time"] = 0
            body["media_source"] = src
        elif len(images) == 1:
            m = images[0]
            if m.url:
                body["media_source"] = {"source_type": "image_url", "url": m.url}
            else:
                data = await load_media_bytes(m)
                body["media_source"] = {"source_type": "image_base64", "content_type": m.mime or "image/jpeg", "data": base64.b64encode(data).decode()}
        else:
            items = []
            for m in images[:CAROUSEL_RANGE[1]]:
                if m.url:
                    items.append({"url": m.url, "title": body.get("title"), "description": body.get("description"), "link": body.get("link")})
                else:
                    data = await load_media_bytes(m)
                    items.append({"content_type": m.mime or "image/jpeg", "data": base64.b64encode(data).decode(), "title": body.get("title"),
                                  "description": body.get("description"), "link": body.get("link")})
            key = "multiple_image_urls" if all("url" in it for it in items) else "multiple_image_base64"
            body["media_source"] = {"source_type": key, "items": items}
        body = {k: v for k, v in body.items() if v is not None}
        await heartbeat(state)
        pin = await self.http.post_json(f"{API}/pins", headers=self._headers(tokens, **{"Content-Type": "application/json"}), json=body, write=True,
                                        account_id=aid, error_mapper=_pin_error)
        pin_id = str(pin.get("id") or "")
        if not pin_id:
            raise PublishError("ambiguous", "Pinterest returned no pin id", code="no_post_id", raw=pin)
        state["pin_id"] = pin_id
        state["published_at"] = self.now().isoformat()
        await save_state(state)
        return self._result(pin_id, state["published_at"])

    async def _upload_video(self, tokens: TokenSet, m, state: dict[str, Any], aid: Any) -> str:
        if state.get("media_id") and state.get("media_ready"):
            return state["media_id"]
        if not state.get("media_id"):
            reg = await self.http.post_json(f"{API}/media", headers=self._headers(tokens, **{"Content-Type": "application/json"}), json={"media_type": "video"},
                                            write=True, account_id=aid, error_mapper=_pin_error)
            state.update({"media_id": reg["media_id"], "upload_url": reg["upload_url"], "upload_parameters": reg.get("upload_parameters") or {}})
            await save_state(state)
            data = await load_media_bytes(m)
            await self.http.request("POST", state["upload_url"], data=state["upload_parameters"], files={"file": ("video", data, m.mime or "video/mp4")},
                                    timeout_s=600, write=True)
            await heartbeat(state)
        deadline = asyncio.get_event_loop().time() + 600
        while True:
            st = await self.http.get_json(f"{API}/media/{state['media_id']}", headers=self._headers(tokens), account_id=aid, error_mapper=_pin_error)
            status = (st.get("status") or "").lower()
            if status == "succeeded":
                state["media_ready"] = True
                await save_state(state)
                return state["media_id"]
            if status == "failed":
                raise PublishError("validation", "Pinterest could not process the video", code="media_failed", raw=st)
            if asyncio.get_event_loop().time() > deadline:
                raise PublishError("transient", "video still processing after 10 minutes", code="media_timeout", raw=st)
            await heartbeat(state)
            await asyncio.sleep(5)

    def _result(self, pin_id: str, published_at: str | None) -> PublishResult:
        at = datetime.fromisoformat(published_at) if published_at else self.now()
        return PublishResult(external_id=pin_id, external_url=f"https://www.pinterest.com/pin/{pin_id}/", published_at=at, raw={"id": pin_id})

    # ---- reads / delete ----------------------------------------------------------------------------------
    async def get_post(self, account: Any, tokens: TokenSet, external_id: str) -> RemotePost:
        body = await self.http.get_json(f"{API}/pins/{external_id}", headers=self._headers(tokens), account_id=account_attr(account, "id"), error_mapper=_pin_error)
        return RemotePost(external_id=str(body.get("id", external_id)), text=body.get("description") or body.get("title"), created_at=_iso(body.get("created_at")),
                          url=f"https://www.pinterest.com/pin/{external_id}/", raw=body)

    async def delete_post(self, account: Any, tokens: TokenSet, external_id: str) -> None:
        await self.http.request("DELETE", f"{API}/pins/{external_id}", headers=self._headers(tokens), account_id=account_attr(account, "id"),
                                ok=(200, 204, 404), error_mapper=_pin_error)

    async def find_recent_posts(self, account: Any, tokens: TokenSet, since: datetime) -> list[RemotePost]:
        body = await self.http.get_json(f"{API}/pins?page_size=25", headers=self._headers(tokens), account_id=account_attr(account, "id"), error_mapper=_pin_error)
        out = []
        for p in body.get("items", []):
            ts = _iso(p.get("created_at"))
            if ts and ts < since:
                continue
            out.append(RemotePost(external_id=str(p["id"]), text=p.get("description") or p.get("title"), created_at=ts,
                                  url=f"https://www.pinterest.com/pin/{p['id']}/", raw=p))
        return out

    # ---- metrics -----------------------------------------------------------------------------------------
    async def get_post_metrics(self, account: Any, tokens: TokenSet, external_id: str) -> dict[str, Any]:
        from app.analytics.normalize import normalize_post_metrics
        aid = account_attr(account, "id")
        raw: dict[str, Any] = {"lifetime": {}, "errors": {}}
        try:
            body = await self.http.get_json(f"{API}/pins/{external_id}?pin_metrics=true", headers=self._headers(tokens), account_id=aid, error_mapper=_pin_error)
            pm = body.get("pin_metrics") or {}
            lifetime = (pm.get("all_time") or pm.get("lifetime_metrics") or {})
            raw["lifetime"] = {k.upper(): v for k, v in lifetime.items()} if isinstance(lifetime, dict) else {}
            raw["pin"] = {k: body.get(k) for k in ("id", "created_at", "board_id", "title")}
        except PublishError as e:
            if e.category == "auth":
                raise
            raw["errors"]["pin_metrics"] = {"category": e.category, "code": e.code}
        if not raw["lifetime"]:
            end = self.now().date()
            start = end - timedelta(days=89)
            q = {"start_date": start.isoformat(), "end_date": end.isoformat(), "metric_types": PIN_METRICS}
            try:
                body = await self.http.get_json(f"{API}/pins/{external_id}/analytics?{urlencode(q)}", headers=self._headers(tokens), account_id=aid, error_mapper=_pin_error)
                lt = ((body.get("all") or {}).get("lifetime_metrics")) or {}
                raw["lifetime"] = {k.upper(): v for k, v in lt.items()}
                raw["window"] = "lifetime"
            except PublishError as e:
                if e.category == "auth":
                    raise
                raw["errors"]["analytics"] = {"category": e.category, "code": e.code}
        return normalize_post_metrics("pinterest", raw)

    async def get_account_metrics(self, account: Any, tokens: TokenSet) -> dict[str, Any]:
        from app.analytics.normalize import normalize_account_metrics
        aid = account_attr(account, "id")
        me = await self.http.get_json(f"{API}/user_account", headers=self._headers(tokens), account_id=aid, error_mapper=_pin_error)
        raw: dict[str, Any] = {k: me.get(k) for k in ("follower_count", "following_count", "monthly_views", "pin_count", "board_count")}
        end = self.now().date()
        start = end - timedelta(days=1)
        try:
            body = await self.http.get_json(f"{API}/user_account/analytics?{urlencode({'start_date': start.isoformat(), 'end_date': end.isoformat(), 'metric_types': 'IMPRESSION,ENGAGEMENT'})}",
                                            headers=self._headers(tokens), account_id=aid, error_mapper=_pin_error)
            summary = ((body.get("all") or {}).get("summary_metrics")) or {}
            raw["analytics"] = {k.upper(): v for k, v in summary.items()}
        except PublishError as e:
            if e.category == "auth":
                raise
            raw["analytics_error"] = {"category": e.category, "code": e.code}
        return normalize_account_metrics("pinterest", raw)

    async def list_boards(self, tokens: TokenSet) -> list[dict[str, Any]]:
        body = await self.http.get_json(f"{API}/boards?page_size=100", headers=self._headers(tokens), error_mapper=_pin_error)
        return [{"id": b.get("id"), "name": b.get("name"), "privacy": b.get("privacy")} for b in body.get("items", [])]

    def rate_limits(self) -> list[dict[str, Any]]:
        return [{"tier": "trial", "limit": 1000, "window": "day"}, {"tier": "standard", "category": "org_write", "limit": 100, "window": "minute"},
                {"tier": "standard", "category": "org_analytics", "limit": 60, "window": "minute"}]


def _iso(v: Any) -> datetime | None:
    if not v:
        return None
    try:
        return datetime.fromisoformat(str(v).replace("Z", "+00:00")).astimezone(UTC)
    except ValueError:
        return None

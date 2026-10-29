"""Google Business Profile adapter (doc 27 §27.9, docs/platforms/linkedin-x-pinterest-gbp.md §4). VERIFIED_AT 2026-10-08.

Google OAuth with ``https://www.googleapis.com/auth/business.manage`` (PKCE + offline refresh). Locations are listed
through Account Management + Business Information; posts through My Business v4 ``localPosts.create``
(STANDARD / EVENT / OFFER, CTA, media by **public URL** only, optional native ``scheduledTime``). Per-post insights were
discontinued in 2023 → ``get_post_metrics`` returns NULLs; location-level daily metrics come from the Performance API.
Access is gated (quota 0 QPM until Google approves the project).
"""
from __future__ import annotations

from datetime import UTC, datetime, timedelta
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
from app.integrations.social.base import BaseAdapter, account_attr, heartbeat, issue, result, save_state
from app.integrations.social.youtube import AUTH_URL, REVOKE_URL, TOKEN_URL, _g_error

VERIFIED_AT = "2026-10-08"
SCOPE = "https://www.googleapis.com/auth/business.manage"
ACCOUNTS_API = "https://mybusinessaccountmanagement.googleapis.com/v1"
INFO_API = "https://mybusinessbusinessinformation.googleapis.com/v1"
POSTS_API = "https://mybusiness.googleapis.com/v4"
PERF_API = "https://businessprofileperformance.googleapis.com/v1"
TOPIC_TYPES = {"STANDARD", "EVENT", "OFFER"}
CTA_TYPES = {"BOOK", "ORDER", "SHOP", "LEARN_MORE", "SIGN_UP", "CALL"}
SUMMARY_MAX = 1500   # not stated on the reference page (open question); conservative limit
DAILY_METRICS = ["BUSINESS_IMPRESSIONS_DESKTOP_MAPS", "BUSINESS_IMPRESSIONS_DESKTOP_SEARCH", "BUSINESS_IMPRESSIONS_MOBILE_MAPS",
                 "BUSINESS_IMPRESSIONS_MOBILE_SEARCH", "WEBSITE_CLICKS", "CALL_CLICKS", "BUSINESS_DIRECTION_REQUESTS"]


class GBPAdapter(BaseAdapter):
    platform = "gbp"
    verified_at = VERIFIED_AT
    VERIFIED_AT = VERIFIED_AT
    docs = ["https://developers.google.com/my-business/reference/rest/v4/accounts.locations.localPosts",
            "https://developers.google.com/my-business/content/posts-data",
            "https://developers.google.com/my-business/reference/performance/rest/v1/locations/fetchMultiDailyMetricsTimeSeries"]

    def _headers(self, tokens: TokenSet, **extra: str) -> dict[str, str]:
        return {"Authorization": f"Bearer {tokens.access_token}", **extra}

    def capabilities(self, account: Any) -> Capabilities:
        return Capabilities(
            formats=["text", "image", "video", "link"], max_text=SUMMARY_MAX, max_media=1, native_schedule=True, can_delete=True, supports_alt_text=False,
            limits={"qpm_after_approval": 300, "edits_per_profile_per_min": 10, "topic_types": sorted(TOPIC_TYPES), "cta_types": sorted(CTA_TYPES),
                    "media": "public URL only (sourceUrl)", "multi_media": "unverified → 1"},
            notes=["access gated: quota 0 QPM until approved; profile verified ≥ 60 days with a website", "no per-post insights since 2023",
                   "native scheduledTime and recurring posts (2026-04) available", "max summary length unverified (assumed 1,500)"],
        )

    # ---- OAuth -------------------------------------------------------------------------------------------
    def auth_url(self, state: str, redirect_uri: str, flavor: str = "default", code_challenge: str | None = None) -> str:
        q = {"client_id": settings.google_client_id, "redirect_uri": redirect_uri, "response_type": "code", "scope": SCOPE, "access_type": "offline",
             "prompt": "consent", "state": state}
        if code_challenge:
            q.update({"code_challenge": code_challenge, "code_challenge_method": "S256"})
        return f"{AUTH_URL}?{urlencode(q)}"

    async def exchange_code(self, code: str, redirect_uri: str, code_verifier: str | None = None) -> TokenSet:
        data = {"code": code, "client_id": settings.google_client_id, "client_secret": settings.google_client_secret, "redirect_uri": redirect_uri,
                "grant_type": "authorization_code"}
        if code_verifier:
            data["code_verifier"] = code_verifier
        body = await self.http.post_json(TOKEN_URL, data=data, error_mapper=_g_error)
        return TokenSet(access_token=body["access_token"], refresh_token=body.get("refresh_token"), expires_at=self.expires_in(body.get("expires_in", 3600)),
                        scopes=(body.get("scope") or "").split(), extra={})

    async def refresh(self, tokens: TokenSet) -> TokenSet:
        if not tokens.refresh_token:
            raise PublishError("unsupported", "no Google refresh token stored", code="no_refresh")
        data = {"refresh_token": tokens.refresh_token, "client_id": settings.google_client_id, "client_secret": settings.google_client_secret,
                "grant_type": "refresh_token"}
        body = await self.http.post_json(TOKEN_URL, data=data, error_mapper=_g_error)
        return TokenSet(access_token=body["access_token"], refresh_token=body.get("refresh_token") or tokens.refresh_token,
                        expires_at=self.expires_in(body.get("expires_in", 3600)), scopes=(body.get("scope") or "").split() or tokens.scopes, extra=dict(tokens.extra))

    async def revoke(self, tokens: TokenSet) -> None:
        try:
            await self.http.post_json(REVOKE_URL, params={"token": tokens.refresh_token or tokens.access_token}, retries=1)
        except PublishError:
            return None

    async def list_connectable_accounts(self, tokens: TokenSet, flavor: str = "default") -> list[ConnectableAccount]:
        accounts = await self.http.get_json(f"{ACCOUNTS_API}/accounts", headers=self._headers(tokens), error_mapper=_g_error)
        out = []
        for acc in accounts.get("accounts", []):
            name = acc.get("name")   # accounts/123
            locs = await self.http.get_json(f"{INFO_API}/{name}/locations?readMask=name,title,storefrontAddress,websiteUri&pageSize=100",
                                            headers=self._headers(tokens), error_mapper=_g_error)
            for loc in locs.get("locations", []):
                loc_name = loc.get("name")   # locations/456
                addr = loc.get("storefrontAddress") or {}
                out.append(ConnectableAccount(external_id=f"{name}/{loc_name}", display_name=loc.get("title") or loc_name, account_type="location",
                                              parent_external_id=name,
                                              extra={"location": loc_name, "account": name, "locality": addr.get("locality"), "website": loc.get("websiteUri")}))
        return out

    async def probe(self, account: Any, tokens: TokenSet) -> dict[str, Any]:
        granted = set(tokens.scopes or account_attr(account, "scopes", []) or [])
        health: dict[str, Any] = {"token_valid": False, "scopes_missing": [] if (not granted or SCOPE in granted) else [SCOPE], "limits_remaining": None,
                                  "expires_at": tokens.expires_at.isoformat() if tokens.expires_at else None, "refreshable": bool(tokens.refresh_token)}
        parent = account_attr(account, "external_id")
        try:
            await self.http.get_json(f"{POSTS_API}/{parent}/localPosts?pageSize=1", headers=self._headers(tokens), account_id=account_attr(account, "id"),
                                     error_mapper=_g_error)
            health["token_valid"] = True
        except PublishError as e:
            health["error"] = {"category": e.category, "code": e.code, "message": e.message}
            if e.category == "rate_limited":
                health["token_valid"] = True
                health["warning"] = "quota exhausted or project not yet approved (0 QPM)"
            elif e.category != "auth":
                raise
        return health

    # ---- validation --------------------------------------------------------------------------------------
    async def validate_content(self, account: Any, req: PublishRequest) -> ValidationResult:
        issues = []
        md = req.metadata
        topic = (md.get("topic_type") or "STANDARD").upper()
        if topic not in TOPIC_TYPES:
            issues.append(issue("gbp_topic_type", f"topic_type must be one of {sorted(TOPIC_TYPES)}", "topic_type"))
        summary = req.text or ""
        if not summary.strip() and topic == "STANDARD":
            issues.append(issue("gbp_summary_required", "STANDARD posts need a summary", "text"))
        if len(summary) > SUMMARY_MAX:
            issues.append(issue("gbp_summary_too_long", f"summary is {len(summary)}/{SUMMARY_MAX} (limit unverified)", "text"))
        if topic in ("EVENT", "OFFER"):
            ev = md.get("event") or {}
            if not ev.get("title") or not (ev.get("schedule") or {}).get("startDate"):
                issues.append(issue("gbp_event_fields", "EVENT/OFFER posts need event.title and event.schedule.startDate", "event"))
        cta = md.get("call_to_action") or {}
        if cta:
            if (cta.get("actionType") or "").upper() not in CTA_TYPES:
                issues.append(issue("gbp_cta_type", f"callToAction.actionType must be one of {sorted(CTA_TYPES)}", "call_to_action"))
            if (cta.get("actionType") or "").upper() != "CALL" and not cta.get("url"):
                issues.append(issue("gbp_cta_url", "callToAction needs a url", "call_to_action"))
        images, videos, docs = self._media_kinds(req)
        if docs:
            issues.append(issue("gbp_unsupported_media", "only photos/videos by public URL are supported", "media"))
        if len(req.media) > 1:
            issues.append(issue("gbp_multi_media_unverified", "the number of media items per post is unverified; use one", "media"))
        for i, m in enumerate(req.media):
            if not m.url:
                issues.append(issue("gbp_requires_public_media_url", "post media must be a publicly fetchable URL (sourceUrl)", f"media[{i}]"))
        if md.get("poll"):
            issues.append(issue("gbp_no_polls", "polls are not supported", "poll"))
        if md.get("scheduled_time"):
            try:
                datetime.fromisoformat(str(md["scheduled_time"]).replace("Z", "+00:00"))
            except ValueError:
                issues.append(issue("gbp_scheduled_time", "scheduled_time must be ISO 8601", "scheduled_time"))
        return result(issues)

    # ---- publish -----------------------------------------------------------------------------------------
    async def publish(self, account: Any, tokens: TokenSet, req: PublishRequest, state: dict[str, Any]) -> PublishResult:
        if state.get("post_name"):
            return self._result(state["post_name"], state.get("search_url"), state.get("published_at"))
        parent = account_attr(account, "external_id")
        md = req.metadata
        topic = (md.get("topic_type") or "STANDARD").upper()
        body: dict[str, Any] = {"languageCode": md.get("language") or "en", "summary": req.text or "", "topicType": topic}
        if md.get("call_to_action"):
            cta = md["call_to_action"]
            body["callToAction"] = {"actionType": (cta.get("actionType") or "LEARN_MORE").upper(), **({"url": cta["url"]} if cta.get("url") else {})}
        if md.get("event"):
            body["event"] = md["event"]
        if md.get("offer"):
            body["offer"] = md["offer"]
        if req.media:
            m = req.media[0]
            if not m.url:
                raise PublishError("validation", "gbp_requires_public_media_url", code="gbp_requires_public_media_url")
            body["media"] = [{"mediaFormat": "VIDEO" if (m.mime or "").startswith("video/") else "PHOTO", "sourceUrl": m.url}]
        if md.get("scheduled_time"):
            body["scheduledTime"] = md["scheduled_time"]
        await heartbeat(state)
        created = await self.http.post_json(f"{POSTS_API}/{parent}/localPosts", headers=self._headers(tokens, **{"Content-Type": "application/json"}), json=body,
                                            write=True, account_id=account_attr(account, "id"), error_mapper=_g_error)
        name = created.get("name")
        if not name:
            raise PublishError("ambiguous", "GBP returned no post name", code="no_post_id", raw=created)
        if created.get("state") == "REJECTED":
            raise PublishError("permanent", "post rejected by Google content policy", code="REJECTED", raw=created)
        state.update({"post_name": name, "search_url": created.get("searchUrl"), "published_at": self.now().isoformat(), "state": created.get("state")})
        await save_state(state)
        return self._result(name, created.get("searchUrl"), state["published_at"])

    def _result(self, name: str, url: str | None, published_at: str | None) -> PublishResult:
        at = datetime.fromisoformat(published_at) if published_at else self.now()
        return PublishResult(external_id=name, external_url=url, published_at=at, raw={"name": name})

    # ---- reads / delete ----------------------------------------------------------------------------------
    async def get_post(self, account: Any, tokens: TokenSet, external_id: str) -> RemotePost:
        body = await self.http.get_json(f"{POSTS_API}/{external_id}", headers=self._headers(tokens), account_id=account_attr(account, "id"), error_mapper=_g_error)
        return RemotePost(external_id=body.get("name", external_id), text=body.get("summary"), created_at=_iso(body.get("createTime")), url=body.get("searchUrl"), raw=body)

    async def delete_post(self, account: Any, tokens: TokenSet, external_id: str) -> None:
        await self.http.request("DELETE", f"{POSTS_API}/{external_id}", headers=self._headers(tokens), account_id=account_attr(account, "id"),
                                ok=(200, 204, 404), error_mapper=_g_error)

    async def find_recent_posts(self, account: Any, tokens: TokenSet, since: datetime) -> list[RemotePost]:
        parent = account_attr(account, "external_id")
        body = await self.http.get_json(f"{POSTS_API}/{parent}/localPosts?pageSize=20", headers=self._headers(tokens), account_id=account_attr(account, "id"),
                                        error_mapper=_g_error)
        out = []
        for p in body.get("localPosts", []):
            ts = _iso(p.get("createTime"))
            if ts and ts < since:
                continue
            out.append(RemotePost(external_id=p.get("name"), text=p.get("summary"), created_at=ts, url=p.get("searchUrl"), raw=p))
        return out

    # ---- metrics -----------------------------------------------------------------------------------------
    async def get_post_metrics(self, account: Any, tokens: TokenSet, external_id: str) -> dict[str, Any]:
        from app.analytics.normalize import normalize_post_metrics
        return normalize_post_metrics("gbp", {"note": "per-post insights discontinued 2023-02-20"})

    async def get_account_metrics(self, account: Any, tokens: TokenSet) -> dict[str, Any]:
        from app.analytics.normalize import normalize_account_metrics
        ext = account_attr(account, "external_id") or ""
        location = ext.split("/", 2)[-1] if ext.count("/") >= 3 else ext   # accounts/1/locations/2 → locations/2
        day = self.now().date() - timedelta(days=3)
        q: list[tuple[str, str]] = [("dailyMetrics", m) for m in DAILY_METRICS]
        q += [("dailyRange.start_date.year", str(day.year)), ("dailyRange.start_date.month", str(day.month)), ("dailyRange.start_date.day", str(day.day)),
              ("dailyRange.end_date.year", str(day.year)), ("dailyRange.end_date.month", str(day.month)), ("dailyRange.end_date.day", str(day.day))]
        raw: dict[str, Any] = {"daily": {}, "date": day.isoformat()}
        try:
            body = await self.http.get_json(f"{PERF_API}/{location}:fetchMultiDailyMetricsTimeSeries?{urlencode(q)}", headers=self._headers(tokens),
                                            account_id=account_attr(account, "id"), error_mapper=_g_error)
            for series in body.get("multiDailyMetricTimeSeries", []):
                for dm in series.get("dailyMetricTimeSeries", []):
                    pts = (dm.get("timeSeries") or {}).get("datedValues") or []
                    if pts:
                        raw["daily"][dm.get("dailyMetric")] = int(pts[-1].get("value") or 0)
        except PublishError as e:
            if e.category == "auth":
                raise
            raw["error"] = {"category": e.category, "code": e.code}
        return normalize_account_metrics("gbp", raw)

    def rate_limits(self) -> list[dict[str, Any]]:
        return [{"scope": "project", "limit": 300, "window": "minute (after approval; 0 before)"}, {"scope": "edits per profile", "limit": 10, "window": "minute"}]


def _iso(v: Any) -> datetime | None:
    if not v:
        return None
    try:
        return datetime.fromisoformat(str(v).replace("Z", "+00:00")).astimezone(UTC)
    except ValueError:
        return None

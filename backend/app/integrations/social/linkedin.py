"""LinkedIn adapter (doc 27 §27.4, docs/platforms/linkedin-x-pinterest-gbp.md §1). VERIFIED_AT 2026-10-08.

Flavors: ``member`` (OIDC + ``w_member_social``, self-serve) and ``organization`` (Community Management scopes,
requires LinkedIn approval). Posts API ``POST https://api.linkedin.com/rest/posts`` with the mandatory
``LinkedIn-Version`` header. Images/videos/documents are uploaded through ``initializeUpload`` → binary PUT →
URN. Members cannot list their own posts (``r_member_social`` closed) so ``find_recent_posts`` returns ``[]`` for
the member flavor and reconciliation relies on stored ids. Refresh tokens exist only for approved MDP partners.
"""
from __future__ import annotations

from datetime import UTC, datetime
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
LINKEDIN_VERSION = "202609"
AUTH_URL = "https://www.linkedin.com/oauth/v2/authorization"
TOKEN_URL = "https://www.linkedin.com/oauth/v2/accessToken"
API = "https://api.linkedin.com"
MEMBER_SCOPES = ["openid", "profile", "email", "w_member_social"]
ORG_SCOPES = MEMBER_SCOPES + ["w_organization_social", "r_organization_social", "rw_organization_admin"]
MAX_COMMENTARY = 3000          # FIELD_LENGTH_TOO_LONG threshold is not published; doc assumes 3,000
MAX_MULTI_IMAGE = 20
ORG_ROLES = {"ADMINISTRATOR", "CONTENT_ADMIN", "DIRECT_SPONSORED_CONTENT_POSTER"}
VIDEO_PART_BYTES = 4 * 1024 * 1024


def _li_error(resp: httpx.Response) -> PublishError | None:
    try:
        body = resp.json()
    except ValueError:
        return None
    if not isinstance(body, dict):
        return None
    code = body.get("code") or body.get("serviceErrorCode")
    msg = body.get("message") or ""
    if resp.status_code == 401 or code in ("EXPIRED_ACCESS_TOKEN", "REVOKED_ACCESS_TOKEN", "INVALID_ACCESS_TOKEN"):
        return PublishError("auth", f"linkedin auth: {msg}", code=str(code or 401), raw=body)
    if resp.status_code == 403 and (code in ("ACCESS_DENIED", "NOT_AUTHORIZED") or "permission" in msg.lower()
                                    or "scope" in msg.lower()):
        return PublishError("auth", f"linkedin permission: {msg}", code=str(code or 403), raw=body)
    if code in ("FIELD_LENGTH_TOO_LONG", "INVALID_PARAMETER", "DUPLICATE_POST") or (resp.status_code == 422):
        cat = "permanent" if code == "DUPLICATE_POST" else "validation"
        return PublishError(cat, f"linkedin rejected: {msg}", code=str(code), raw=body)
    return None


class LinkedInAdapter(BaseAdapter):
    platform = "linkedin"
    verified_at = VERIFIED_AT
    VERIFIED_AT = VERIFIED_AT
    docs = ["https://learn.microsoft.com/en-us/linkedin/marketing/community-management/shares/posts-api",
            "https://learn.microsoft.com/en-us/linkedin/marketing/versioning"]

    def __init__(self) -> None:
        super().__init__()
        self.http.base_headers = {"LinkedIn-Version": LINKEDIN_VERSION, "X-Restli-Protocol-Version": "2.0.0"}

    # ---- helpers -----------------------------------------------------------------------------------------
    @staticmethod
    def _flavor(account: Any) -> str:
        f = account_attr(account, "auth_flavor", "member") or "member"
        return "organization" if f in ("organization", "org") else "member"

    can_list_own_posts = False   # member flavor default; organizations can list (see can_list_posts)

    def can_list_posts(self, account: Any) -> bool:
        return self._flavor(account) == "organization"

    def _author(self, account: Any) -> str:
        ext = account_attr(account, "external_id")
        if self._flavor(account) == "organization":
            return ext if str(ext).startswith("urn:") else f"urn:li:organization:{ext}"
        return ext if str(ext).startswith("urn:") else f"urn:li:person:{ext}"

    def _headers(self, tokens: TokenSet, **extra: str) -> dict[str, str]:
        return {"Authorization": f"Bearer {tokens.access_token}", "Content-Type": "application/json", **extra}

    def capabilities(self, account: Any) -> Capabilities:
        flavor = self._flavor(account) if account is not None else "member"
        return Capabilities(
            formats=["text", "image", "carousel", "video", "document", "article", "poll", "link"],
            max_text=MAX_COMMENTARY, max_media=MAX_MULTI_IMAGE, native_schedule=False, can_delete=True,
            supports_alt_text=True,
            limits={"posts_per_member_per_day": 150, "app_per_day": 100_000, "multi_image": [2, MAX_MULTI_IMAGE],
                    "video_max_bytes": 5 * 1024**3, "document_max_bytes": 100 * 1024**2, "document_max_pages": 300,
                    "poll_options": [2, 4], "token_lifetime_days": 60},
            notes=[f"flavor={flavor}", "no native scheduling (lifecycleState=PUBLISHED only)",
                   "member: cannot list own posts (ids stored); refresh tokens only for MDP partners",
                   "organization: requires Community Management API approval", "article shares need title/description/thumbnail (no URL scraping)"],
        )

    # ---- OAuth -------------------------------------------------------------------------------------------
    def auth_url(self, state: str, redirect_uri: str, flavor: str = "member", code_challenge: str | None = None) -> str:
        scopes = ORG_SCOPES if flavor in ("organization", "org") else MEMBER_SCOPES
        q = {"response_type": "code", "client_id": settings.linkedin_client_id, "redirect_uri": redirect_uri,
             "state": state, "scope": " ".join(scopes)}
        return f"{AUTH_URL}?{urlencode(q)}"

    async def exchange_code(self, code: str, redirect_uri: str, code_verifier: str | None = None) -> TokenSet:
        data = {"grant_type": "authorization_code", "code": code, "redirect_uri": redirect_uri,
                "client_id": settings.linkedin_client_id, "client_secret": settings.linkedin_client_secret}
        body = await self.http.post_json(TOKEN_URL, data=data, headers={"Content-Type": "application/x-www-form-urlencoded"},
                                         error_mapper=_li_error)
        return self._tokens_from(body)

    def _tokens_from(self, body: dict[str, Any]) -> TokenSet:
        return TokenSet(access_token=body["access_token"], refresh_token=body.get("refresh_token"),
                        expires_at=self.expires_in(body.get("expires_in", 60 * 86400)),
                        refresh_expires_at=self.expires_in(body["refresh_token_expires_in"]) if body.get("refresh_token_expires_in") else None,
                        scopes=(body.get("scope") or "").replace(",", " ").split(), extra={})

    async def refresh(self, tokens: TokenSet) -> TokenSet:
        if not tokens.refresh_token:
            raise PublishError("unsupported", "LinkedIn issues refresh tokens only to approved MDP partners; reconnect every 60 days",
                               code="linkedin_refresh_requires_mdp_partner")
        data = {"grant_type": "refresh_token", "refresh_token": tokens.refresh_token,
                "client_id": settings.linkedin_client_id, "client_secret": settings.linkedin_client_secret}
        body = await self.http.post_json(TOKEN_URL, data=data, headers={"Content-Type": "application/x-www-form-urlencoded"},
                                         error_mapper=_li_error)
        ts = self._tokens_from(body)
        ts.refresh_token = ts.refresh_token or tokens.refresh_token
        ts.refresh_expires_at = ts.refresh_expires_at or tokens.refresh_expires_at   # fixed 365-day life, never reset
        ts.scopes = ts.scopes or tokens.scopes
        return ts

    def refresh_supported(self, tokens: TokenSet | None = None) -> bool:
        return bool(tokens and tokens.refresh_token)

    async def list_connectable_accounts(self, tokens: TokenSet, flavor: str = "member") -> list[ConnectableAccount]:
        out: list[ConnectableAccount] = []
        me = await self.http.get_json(f"{API}/v2/userinfo", headers=self._headers(tokens), error_mapper=_li_error)
        member = ConnectableAccount(external_id=me["sub"], display_name=me.get("name") or me.get("given_name") or "LinkedIn member",
                                    avatar_url=me.get("picture"), account_type="member", extra={"email": me.get("email")})
        if flavor not in ("organization", "org"):
            return [member]
        url = (f"{API}/rest/organizationAcls?q=roleAssignee&state=APPROVED"
               "&projection=(elements*(organization~(localizedName,vanityName),role,state))")
        body = await self.http.get_json(url, headers=self._headers(tokens), error_mapper=_li_error)
        for el in body.get("elements", []):
            if el.get("role") not in ORG_ROLES:
                continue
            org_urn = el.get("organization", "")
            org = el.get("organization~") or {}
            out.append(ConnectableAccount(external_id=org_urn.split(":")[-1], display_name=org.get("localizedName") or org_urn,
                                          handle=org.get("vanityName"), account_type="organization",
                                          parent_external_id=me["sub"], extra={"role": el.get("role"), "urn": org_urn}))
        return out

    async def probe(self, account: Any, tokens: TokenSet) -> dict[str, Any]:
        flavor = self._flavor(account)
        required = {"w_member_social"} if flavor == "member" else {"w_organization_social"}
        granted = set(tokens.scopes or account_attr(account, "scopes", []) or [])
        health: dict[str, Any] = {"token_valid": False, "scopes_missing": sorted(required - granted) if granted else [],
                                  "limits_remaining": None, "expires_at": tokens.expires_at.isoformat() if tokens.expires_at else None,
                                  "refreshable": self.refresh_supported(tokens), "flavor": flavor}
        try:
            await self.http.get_json(f"{API}/v2/userinfo", headers=self._headers(tokens), account_id=account_attr(account, "id"),
                                     error_mapper=_li_error)
            health["token_valid"] = True
        except PublishError as e:
            health["error"] = {"category": e.category, "code": e.code, "message": e.message}
            if e.category != "auth":
                raise
        health["can_list_own_posts"] = flavor == "organization"
        health["metrics"] = "org share statistics" if flavor == "organization" else (
            "memberCreatorPostAnalytics" if "r_member_postAnalytics" in granted else "none (r_member_postAnalytics not granted)")
        return health

    # ---- validation --------------------------------------------------------------------------------------
    async def validate_content(self, account: Any, req: PublishRequest) -> ValidationResult:
        issues = []
        text = req.text or ""
        if len(text) > MAX_COMMENTARY:
            issues.append(issue("linkedin_text_too_long", f"commentary is {len(text)} chars; LinkedIn rejects long text (assumed max {MAX_COMMENTARY})", "text"))
        images, videos, docs = self._media_kinds(req)
        fmt = req.metadata.get("format")
        if len(images) == 1 and (videos or docs):
            issues.append(issue("linkedin_mixed_media", "a post can carry images OR one video OR one document", "media"))
        if len(images) > MAX_MULTI_IMAGE:
            issues.append(issue("linkedin_too_many_images", f"multi-image posts allow 2–{MAX_MULTI_IMAGE} images", "media"))
        if len(videos) > 1:
            issues.append(issue("linkedin_one_video", "only one video per post", "media"))
        if len(docs) > 1:
            issues.append(issue("linkedin_one_document", "only one document per post", "media"))
        for i, m in enumerate(req.media):
            info = media_info(req, req.media.index(m))
            size = info.get("bytes") or 0
            if m in videos and size > 5 * 1024**3:
                issues.append(issue("linkedin_video_too_large", "video exceeds 5 GB", f"media[{i}]"))
            if m in docs and size > 100 * 1024**2:
                issues.append(issue("linkedin_document_too_large", "document exceeds 100 MB", f"media[{i}]"))
            if m in images and (m.mime or "").lower() not in ("image/jpeg", "image/png", "image/gif"):
                issues.append(issue("linkedin_image_format", "images must be JPG, PNG or GIF", f"media[{i}]"))
            if m in images and not (m.alt_text or info.get("alt_text")):
                issues.append(issue("alt_text_missing", "image has no alt text", f"media[{i}]", severity="warning"))
        poll = req.metadata.get("poll")
        if poll or fmt == "poll":
            opts = (poll or {}).get("options") or []
            if not 2 <= len(opts) <= 4:
                issues.append(issue("linkedin_poll_options", "polls need 2–4 options", "poll"))
            if (poll or {}).get("duration", "THREE_DAYS") not in ("ONE_DAY", "THREE_DAYS", "SEVEN_DAYS", "FOURTEEN_DAYS"):
                issues.append(issue("linkedin_poll_duration", "duration must be ONE_DAY|THREE_DAYS|SEVEN_DAYS|FOURTEEN_DAYS", "poll"))
            if req.media:
                issues.append(issue("linkedin_poll_no_media", "polls cannot carry media", "media"))
        article = req.metadata.get("article") or (fmt in ("article", "link") and req.metadata.get("link") and {"source": req.metadata["link"]})
        if article and not article.get("title"):
            issues.append(issue("linkedin_article_title", "article shares need title/description/thumbnail (LinkedIn does not scrape URLs)", "article"))
        if not text and not req.media and not poll and not article:
            issues.append(issue("empty_post", "post needs text, media, a poll or an article", "text"))
        if req.segments and len(req.segments) > 1:
            issues.append(issue("linkedin_no_threads", "LinkedIn has no thread concept; extra segments are ignored", "segments", "warning"))
        return result(issues)

    # ---- uploads -----------------------------------------------------------------------------------------
    async def _upload_image(self, author: str, tokens: TokenSet, m, state: dict[str, Any], key: str) -> str:
        urns: dict[str, str] = state.setdefault("image_urns", {})
        if key in urns:
            return urns[key]
        init = await self.http.post_json(f"{API}/rest/images?action=initializeUpload", headers=self._headers(tokens),
                                         json={"initializeUploadRequest": {"owner": author}}, error_mapper=_li_error)
        value = init["value"]
        data = await load_media_bytes(m)
        await self.http.request("PUT", value["uploadUrl"], content=data, timeout_s=300,
                                headers={"Authorization": f"Bearer {tokens.access_token}", "Content-Type": "application/octet-stream"},
                                error_mapper=_li_error)
        urns[key] = value["image"]
        await save_state(state)
        await heartbeat(state)
        return value["image"]

    async def _upload_document(self, author: str, tokens: TokenSet, m, state: dict[str, Any]) -> str:
        if state.get("document_urn"):
            return state["document_urn"]
        init = await self.http.post_json(f"{API}/rest/documents?action=initializeUpload", headers=self._headers(tokens),
                                         json={"initializeUploadRequest": {"owner": author}}, error_mapper=_li_error)
        value = init["value"]
        data = await load_media_bytes(m)
        await self.http.request("PUT", value["uploadUrl"], content=data, timeout_s=300,
                                headers={"Authorization": f"Bearer {tokens.access_token}", "Content-Type": "application/octet-stream"},
                                error_mapper=_li_error)
        state["document_urn"] = value["document"]
        await save_state(state)
        return value["document"]

    async def _upload_video(self, author: str, tokens: TokenSet, m, state: dict[str, Any]) -> str:
        if state.get("video_urn") and state.get("video_finalized"):
            return state["video_urn"]
        data = await load_media_bytes(m)
        init = await self.http.post_json(f"{API}/rest/videos?action=initializeUpload", headers=self._headers(tokens),
                                         json={"initializeUploadRequest": {"owner": author, "fileSizeBytes": len(data),
                                                                           "uploadCaptions": False, "uploadThumbnail": False}},
                                         error_mapper=_li_error)
        value = init["value"]
        state["video_urn"] = value["video"]
        etags: list[str] = []
        for part in value.get("uploadInstructions", []):
            first, last = int(part["firstByte"]), int(part["lastByte"])
            resp = await self.http.request("PUT", part["uploadUrl"], content=data[first:last + 1], timeout_s=300,
                                           headers={"Authorization": f"Bearer {tokens.access_token}", "Content-Type": "application/octet-stream"},
                                           error_mapper=_li_error)
            etags.append(resp.headers.get("etag") or resp.headers.get("ETag") or "")
            await heartbeat(state)
        await self.http.post_json(f"{API}/rest/videos?action=finalizeUpload", headers=self._headers(tokens),
                                  json={"finalizeUploadRequest": {"video": value["video"], "uploadToken": value.get("uploadToken", ""),
                                                                  "uploadedPartIds": etags}}, error_mapper=_li_error)
        state["video_finalized"] = True
        await save_state(state)
        # processing: poll until AVAILABLE (or give up and let the post call tell us)
        for _ in range(40):
            v = await self.http.get_json(f"{API}/rest/videos/{quote(value['video'], safe='')}", headers=self._headers(tokens),
                                         error_mapper=_li_error)
            status = v.get("status")
            if status == "AVAILABLE":
                break
            if status in ("PROCESSING_FAILED", "FAILED"):
                raise PublishError("validation", "LinkedIn could not process the video", code="video_processing_failed", raw=v)
            await heartbeat(state)
            await _sleep(3)
        return value["video"]

    # ---- publish -----------------------------------------------------------------------------------------
    async def publish(self, account: Any, tokens: TokenSet, req: PublishRequest, state: dict[str, Any]) -> PublishResult:
        if state.get("post_urn"):
            return self._result(state["post_urn"], state.get("published_at"))
        author = self._author(account)
        images, videos, docs = self._media_kinds(req)
        body: dict[str, Any] = {
            "author": author, "commentary": req.text or "", "visibility": "PUBLIC",
            "distribution": {"feedDistribution": "MAIN_FEED", "targetEntities": [], "thirdPartyDistributionChannels": []},
            "lifecycleState": "PUBLISHED", "isReshareDisabledByAuthor": False,
        }
        poll = req.metadata.get("poll")
        article = req.metadata.get("article")
        if videos:
            urn = await self._upload_video(author, tokens, videos[0], state)
            body["content"] = {"media": {"id": urn, "title": req.metadata.get("title") or (req.text or "")[:200] or "Video"}}
        elif docs:
            urn = await self._upload_document(author, tokens, docs[0], state)
            body["content"] = {"media": {"id": urn, "title": req.metadata.get("title") or "Document"}}
        elif len(images) == 1:
            urn = await self._upload_image(author, tokens, images[0], state, "0")
            media: dict[str, Any] = {"id": urn}
            if images[0].alt_text:
                media["altText"] = images[0].alt_text
            body["content"] = {"media": media}
        elif len(images) >= 2:
            items = []
            for i, m in enumerate(images[:MAX_MULTI_IMAGE]):
                urn = await self._upload_image(author, tokens, m, state, str(i))
                items.append({"id": urn, **({"altText": m.alt_text} if m.alt_text else {})})
            body["content"] = {"multiImage": {"images": items}}
        elif poll:
            body["content"] = {"poll": {"question": (poll.get("question") or req.text or "")[:140],
                                        "options": [{"text": o} for o in poll.get("options", [])[:4]],
                                        "settings": {"duration": poll.get("duration", "THREE_DAYS")}}}
        elif article:
            art = {"source": article.get("source") or article.get("url") or req.metadata.get("link"), "title": article.get("title")}
            if article.get("description"):
                art["description"] = article["description"]
            thumb = article.get("thumbnail_media")
            if thumb is not None:
                art["thumbnail"] = await self._upload_image(author, tokens, thumb, state, "thumb")
            body["content"] = {"article": art}
        await heartbeat(state)
        resp = await self.http.request("POST", f"{API}/rest/posts", headers=self._headers(tokens), json=body, write=True,
                                       account_id=account_attr(account, "id"), error_mapper=_li_error)
        urn = resp.headers.get("x-restli-id") or resp.headers.get("X-RestLi-Id")
        if not urn:
            try:
                urn = resp.json().get("id")
            except ValueError:
                urn = None
        if not urn:
            raise PublishError("ambiguous", "LinkedIn returned no post id (x-restli-id header missing)", code="no_post_id")
        state["post_urn"] = urn
        state["published_at"] = self.now().isoformat()
        await save_state(state)
        return self._result(urn, state["published_at"])

    def _result(self, urn: str, published_at: str | None) -> PublishResult:
        at = datetime.fromisoformat(published_at) if published_at else self.now()
        return PublishResult(external_id=urn, external_url=f"https://www.linkedin.com/feed/update/{urn}/", published_at=at,
                            raw={"urn": urn})

    # ---- reads / delete ----------------------------------------------------------------------------------
    async def get_post(self, account: Any, tokens: TokenSet, external_id: str) -> RemotePost:
        body = await self.http.get_json(f"{API}/rest/posts/{quote(external_id, safe='')}", headers=self._headers(tokens),
                                        error_mapper=_li_error)
        return RemotePost(external_id=body.get("id", external_id), text=body.get("commentary"),
                          created_at=_ms(body.get("createdAt")), url=f"https://www.linkedin.com/feed/update/{external_id}/", raw=body)

    async def delete_post(self, account: Any, tokens: TokenSet, external_id: str) -> None:
        await self.http.request("DELETE", f"{API}/rest/posts/{quote(external_id, safe='')}", headers=self._headers(tokens),
                                ok=(200, 204, 404), error_mapper=_li_error)

    async def find_recent_posts(self, account: Any, tokens: TokenSet, since: datetime) -> list[RemotePost]:
        if self._flavor(account) != "organization":
            return []   # member posts cannot be listed (r_member_social closed) → rely on stored ids
        author = quote(self._author(account), safe="")
        body = await self.http.get_json(f"{API}/rest/posts?author={author}&q=author&count=20&sortBy=LAST_MODIFIED",
                                        headers=self._headers(tokens), error_mapper=_li_error)
        out = []
        for el in body.get("elements", []):
            created = _ms(el.get("createdAt"))
            if created and created < since:
                continue
            out.append(RemotePost(external_id=el.get("id"), text=el.get("commentary"), created_at=created,
                                  url=f"https://www.linkedin.com/feed/update/{el.get('id')}/", raw=el))
        return out

    # ---- metrics -----------------------------------------------------------------------------------------
    async def get_post_metrics(self, account: Any, tokens: TokenSet, external_id: str) -> dict[str, Any]:
        from app.analytics.normalize import normalize_post_metrics
        flavor = self._flavor(account)
        raw: dict[str, Any] = {"flavor": flavor}
        if flavor == "organization":
            org = self._author(account)
            key = "ugcPosts" if ":ugcPost:" in external_id else "shares"
            url = (f"{API}/rest/organizationalEntityShareStatistics?q=organizationalEntity"
                   f"&organizationalEntity={quote(org, safe='')}&{key}=List({quote(external_id, safe='')})")
            try:
                body = await self.http.get_json(url, headers=self._headers(tokens), error_mapper=_li_error)
                els = body.get("elements") or []
                raw["org_stats"] = (els[0].get("totalShareStatistics") if els else {}) or {}
            except PublishError as e:
                if e.category == "auth":
                    raise
                raw["error"] = {"category": e.category, "code": e.code}
        else:
            granted = set(tokens.scopes or account_attr(account, "scopes", []) or [])
            if "r_member_postAnalytics" in granted:
                stats: dict[str, Any] = {}
                entity = f"(share:{quote(external_id, safe='')})" if ":share:" in external_id else f"(ugcPost:{quote(external_id, safe='')})"
                for metric in ("IMPRESSION", "MEMBERS_REACHED", "RESHARE", "REACTION", "COMMENT", "POST_SAVE", "LINK_CLICKS",
                               "FOLLOWER_GAINED_FROM_CONTENT", "PROFILE_VIEW_FROM_CONTENT"):
                    url = (f"{API}/rest/memberCreatorPostAnalytics?q=entity&entity={entity}&aggregation=TOTAL&metricType={metric}")
                    try:
                        body = await self.http.get_json(url, headers=self._headers(tokens), error_mapper=_li_error)
                        els = body.get("elements") or []
                        stats[metric] = els[0].get("count") if els else None
                    except PublishError as e:
                        if e.category == "auth":
                            raise
                        stats[metric] = None
                raw["member_stats"] = stats
            else:
                raw["member_stats"] = None
        return normalize_post_metrics("linkedin", raw, flavor=flavor)

    async def get_account_metrics(self, account: Any, tokens: TokenSet) -> dict[str, Any]:
        from app.analytics.normalize import normalize_account_metrics
        raw: dict[str, Any] = {}
        if self._flavor(account) == "organization":
            org = self._author(account)
            try:
                body = await self.http.get_json(f"{API}/rest/networkSizes/{quote(org, safe='')}?edgeType=COMPANY_FOLLOWED_BY_MEMBER",
                                                headers=self._headers(tokens), error_mapper=_li_error)
                raw["followers"] = body.get("firstDegreeSize")
            except PublishError as e:
                if e.category == "auth":
                    raise
                raw["error"] = {"category": e.category, "code": e.code}
        return normalize_account_metrics("linkedin", raw, flavor=self._flavor(account))

    async def get_public_profile(self, tokens: TokenSet, organization_id: str) -> dict[str, Any]:
        """Any organization's follower count (networkSizes) + basic lookup; other orgs' posts are not readable."""
        org = organization_id if organization_id.startswith("urn:") else f"urn:li:organization:{organization_id}"
        sizes = await self.http.get_json(f"{API}/rest/networkSizes/{quote(org, safe='')}?edgeType=COMPANY_FOLLOWED_BY_MEMBER",
                                         headers=self._headers(tokens), error_mapper=_li_error)
        info = await self.http.get_json(f"{API}/rest/organizations/{org.split(':')[-1]}", headers=self._headers(tokens),
                                        error_mapper=_li_error)
        return {"followers": sizes.get("firstDegreeSize"), "name": info.get("localizedName"), "vanity": info.get("vanityName"),
                "website": info.get("website"), "availability": "official_api", "posts": "not_available"}

    def rate_limits(self) -> list[dict[str, Any]]:
        return [{"scope": "member", "limit": 150, "window_s": 86400}, {"scope": "app", "limit": 100_000, "window_s": 86400}]


def _ms(v: Any) -> datetime | None:
    try:
        return datetime.fromtimestamp(int(v) / 1000, tz=UTC) if v else None
    except (TypeError, ValueError):
        return None


async def _sleep(s: float) -> None:
    import asyncio
    await asyncio.sleep(s)


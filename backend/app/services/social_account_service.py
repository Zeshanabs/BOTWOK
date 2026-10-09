"""SocialAccountService — OAuth connect flows, account health, token refresh orchestration (doc 19 §19.4, doc 27).

Flow: ``connect_start`` (oauth_states row: random state, PKCE verifier where used, 10-min TTL) → platform →
``handle_callback`` (exchange code, list connectable accounts; exactly one → create; several → selection token in
Redis for 10 min) → ``select_account`` (social_accounts row + TokenVault + probe + SOCIAL_ACCOUNT_CONNECTED + audit).
``token_monitor`` scans tokens expiring within 7 days: refresh where the platform supports it, otherwise
SOCIAL_ACCOUNT_TOKEN_EXPIRING + a reconnect notification.
"""
from __future__ import annotations

import json
import secrets
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.core.errors import ProblemError, conflict, forbidden, not_found
from app.core.events import emit
from app.core.logging import get_logger
from app.core.ports.social_adapter import ConnectableAccount, PublishError, TokenSet
from app.integrations.social.base import oauth_state, pkce_pair, pkce_pair_hex
from app.integrations.social.registry import PLATFORM_NOTES, get_adapter
from app.models.brand import Brand
from app.models.enums import AccountStatus, Platform, ScheduleStatus
from app.models.identity import User, Workspace
from app.models.scheduling import ScheduledPost
from app.models.social import OAuthState, OAuthToken, SocialAccount
from app.services.publishing_service import _audit, _notify
from app.services.token_vault import TokenVault
from app.workers.queue import cancel_pending

log = get_logger("social")

STATE_TTL = timedelta(minutes=10)
SELECTION_TTL_S = 600
EXPIRING_WINDOW = timedelta(days=7)
PKCE_PLATFORMS = {"x": "s256", "tiktok": "hex", "youtube": "s256", "gbp": "s256"}
DEFAULT_FLAVOR = {"linkedin": "member", "instagram": "facebook_login", "tiktok": "inbox_upload"}
LIVE = (ScheduleStatus.scheduled, ScheduleStatus.queued, ScheduleStatus.publishing, ScheduleStatus.paused)


def _now() -> datetime:
    return datetime.now(UTC)


def redirect_uri(platform: str) -> str:
    return f"{settings.public_base_url.rstrip('/')}/api/v1/social/callback/{platform}"


def _platform(value: str) -> Platform:
    try:
        return Platform(value)
    except ValueError as e:
        raise not_found(f"Platform {value!r}") from e


def _flavor(platform: str, flavor: str | None) -> str:
    allowed = PLATFORM_NOTES.get(platform, {}).get("flavors") or ["default"]
    f = flavor or DEFAULT_FLAVOR.get(platform) or allowed[0]
    if f not in allowed:
        raise ProblemError(422, "validation_error", "Validation failed", f"flavor must be one of {allowed}")
    return f


class SocialAccountService:
    vault = TokenVault()

    # ---- connect ---------------------------------------------------------------------------------------
    @classmethod
    async def connect_start(cls, db: AsyncSession, member: Any, platform: str, brand_id: UUID, flavor: str | None = None) -> dict[str, Any]:
        if not member.has("admin"):
            raise forbidden("Connecting social accounts requires admin")
        plat = _platform(platform)
        brand = await db.get(Brand, brand_id)
        if brand is None or brand.workspace_id != member.workspace_id:
            raise not_found("Brand")
        flavor = _flavor(platform, flavor)
        adapter = get_adapter(platform)
        state = oauth_state()
        verifier = challenge = None
        mode = PKCE_PLATFORMS.get(platform)
        if mode == "hex":
            verifier, challenge = pkce_pair_hex()
        elif mode == "s256":
            verifier, challenge = pkce_pair()
        elif platform == "instagram" and flavor == "instagram_login":
            verifier = "flavor:instagram_login"   # no PKCE on Meta; carries the flavor to exchange_code
        uri = redirect_uri(platform)
        db.add(OAuthState(state=state, workspace_id=member.workspace_id, brand_id=brand_id, user_id=member.user.id, platform=plat, auth_flavor=flavor,
                          code_verifier=verifier, redirect_uri=uri, expires_at=_now() + STATE_TTL))
        await db.flush()
        url = adapter.auth_url(state, uri, flavor, challenge)
        await _audit(db, member, "social.connect_start", "oauth_state", state[:8], after={"platform": platform, "flavor": flavor}, workspace_id=member.workspace_id)
        return {"auth_url": url, "state": state, "platform": platform, "flavor": flavor, "redirect_uri": uri, "expires_at": (_now() + STATE_TTL).isoformat()}

    @classmethod
    async def handle_callback(cls, db: AsyncSession, platform: str, code: str, state: str) -> dict[str, Any]:
        """Public endpoint: validates the single-use state, exchanges the code, lists connectable accounts."""
        _platform(platform)
        row = await db.get(OAuthState, state)
        if row is None or row.platform.value != platform or row.consumed_at is not None or row.expires_at < _now():
            raise ProblemError(400, "invalid_state", "Invalid or expired OAuth state")
        row.consumed_at = _now()
        adapter = get_adapter(platform)
        try:
            tokens = await adapter.exchange_code(code, row.redirect_uri, row.code_verifier)
            accounts = await adapter.list_connectable_accounts(tokens, row.auth_flavor)
        except PublishError as e:
            raise ProblemError(502, "platform_error", "Platform error", f"{e.category}: {e.message}", [{"code": e.code or e.category, "message": e.message}]) from e
        if not accounts:
            raise ProblemError(422, "no_connectable_accounts", "No connectable accounts",
                               f"The {platform} login succeeded but no {_what(platform, row.auth_flavor)} is available to this user.")
        ws = await db.get(Workspace, row.workspace_id)
        member = _Member(await db.get(User, row.user_id), row.workspace_id)
        if len(accounts) == 1:
            account = await cls._create_account(db, member, row, tokens, accounts[0])
            return {"status": "connected", "account_id": str(account.id), "workspace_slug": ws.slug if ws else None, "platform": platform}
        token = secrets.token_urlsafe(24)
        payload = {"workspace_id": str(row.workspace_id), "brand_id": str(row.brand_id), "user_id": str(row.user_id), "platform": platform,
                   "flavor": row.auth_flavor, "tokens": _tokens_to_json(tokens), "accounts": [_acc_to_json(a) for a in accounts]}
        await cls._stash(token, payload)
        return {"status": "select", "selection_token": token, "workspace_slug": ws.slug if ws else None, "platform": platform,
                "accounts": [{k: v for k, v in _acc_to_json(a).items() if k != "extra"} | {"parent_external_id": a.parent_external_id} for a in accounts]}

    @classmethod
    async def select_account(cls, db: AsyncSession, member: Any, platform: str, selection_token: str, external_id: str) -> SocialAccount:
        if not member.has("admin"):
            raise forbidden("Connecting social accounts requires admin")
        payload = await cls._unstash(selection_token)
        if not payload or payload.get("platform") != platform or payload.get("workspace_id") != str(member.workspace_id):
            raise ProblemError(400, "invalid_selection_token", "Selection token invalid or expired")
        chosen = next((a for a in payload["accounts"] if a["external_id"] == external_id), None)
        if chosen is None:
            raise not_found("Connectable account")
        tokens = _tokens_from_json(payload["tokens"])
        row = OAuthState(state=selection_token, workspace_id=UUID(payload["workspace_id"]), brand_id=UUID(payload["brand_id"]), user_id=UUID(payload["user_id"]),
                         platform=_platform(platform), auth_flavor=payload["flavor"], redirect_uri=redirect_uri(platform), expires_at=_now())
        account = await cls._create_account(db, member, row, tokens, _acc_from_json(chosen))
        await cls._forget(selection_token)
        return account

    @classmethod
    async def _create_account(cls, db: AsyncSession, member: Any, state: OAuthState, tokens: TokenSet, ca: ConnectableAccount) -> SocialAccount:
        existing = (await db.execute(select(SocialAccount).where(SocialAccount.workspace_id == state.workspace_id, SocialAccount.platform == state.platform,
                                                                 SocialAccount.external_id == ca.external_id, SocialAccount.auth_flavor == state.auth_flavor))).scalars().first()
        account = existing or SocialAccount(workspace_id=state.workspace_id, brand_id=state.brand_id, platform=state.platform, auth_flavor=state.auth_flavor,
                                            external_id=ca.external_id, display_name=ca.display_name, connected_by=state.user_id)
        account.brand_id = state.brand_id
        account.display_name = ca.display_name
        account.handle = ca.handle
        account.avatar_url = ca.avatar_url
        account.account_type = ca.account_type
        account.parent_external_id = ca.parent_external_id
        account.scopes = list(tokens.scopes or [])
        account.status = AccountStatus.active
        account.disconnected_at = None
        account.connected_by = state.user_id
        db.add(account)
        await db.flush()
        ts = TokenSet(access_token=tokens.access_token, refresh_token=tokens.refresh_token, expires_at=tokens.expires_at, refresh_expires_at=tokens.refresh_expires_at,
                      scopes=tokens.scopes, extra={**tokens.extra, **{k: v for k, v in ca.extra.items() if k in ("page_token", "page_id", "open_id", "flavor")}})
        await cls.vault.store_tokenset(db, account, ts)
        await cls._probe_into(db, account)
        await emit(db, "SOCIAL_ACCOUNT_CONNECTED", {"account_id": str(account.id), "platform": account.platform.value, "flavor": account.auth_flavor,
                                                    "display_name": account.display_name, "brand_id": str(account.brand_id),
                                                    "expires_at": tokens.expires_at.isoformat() if tokens.expires_at else None},
                   workspace_id=account.workspace_id, actor={"type": "user", "id": str(state.user_id)})
        await _audit(db, member, "social.connect", "social_account", account.id,
                     after={"platform": account.platform.value, "external_id": account.external_id, "flavor": account.auth_flavor}, workspace_id=account.workspace_id)
        return account

    # ---- reads -----------------------------------------------------------------------------------------
    @classmethod
    async def list(cls, db: AsyncSession, workspace_id: UUID, brand_id: UUID | None = None, include_disconnected: bool = False) -> list[SocialAccount]:
        q = select(SocialAccount).where(SocialAccount.workspace_id == workspace_id)
        if brand_id:
            q = q.where(SocialAccount.brand_id == brand_id)
        if not include_disconnected:
            q = q.where(SocialAccount.status != AccountStatus.disconnected)
        return list((await db.execute(q.order_by(SocialAccount.platform, SocialAccount.display_name))).scalars().unique())

    @classmethod
    async def get(cls, db: AsyncSession, workspace_id: UUID, account_id: UUID) -> SocialAccount:
        a = await db.get(SocialAccount, account_id)
        if a is None or a.workspace_id != workspace_id:
            raise not_found("Social account")
        return a

    @classmethod
    async def get_tokens_for_publish(cls, db: AsyncSession, account: SocialAccount) -> TokenSet:
        if account.status != AccountStatus.active:
            raise PublishError("auth", f"account is {account.status.value}", code="account_" + account.status.value)
        return await cls.vault.get_tokens(db, account)

    # ---- health / refresh ------------------------------------------------------------------------------
    @classmethod
    async def _probe_into(cls, db: AsyncSession, account: SocialAccount) -> dict[str, Any]:
        adapter = get_adapter(account.platform.value)
        caps = adapter.capabilities(account)
        account.capabilities = {**(account.capabilities or {}), "formats": caps.formats, "max_text": caps.max_text, "max_media": caps.max_media,
                                "native_schedule": caps.native_schedule, "can_delete": caps.can_delete, "supports_alt_text": caps.supports_alt_text,
                                "limits": caps.limits, "notes": caps.notes, "verified_at": adapter.verified_at}
        try:
            tokens = await cls.vault.get_tokens(db, account)
            health = await adapter.probe(account, tokens)
        except LookupError:
            health = {"token_valid": False, "error": {"category": "auth", "code": "no_token", "message": "no live token"}}
        except PublishError as e:
            health = {"token_valid": e.category != "auth", "error": {"category": e.category, "code": e.code, "message": e.message}}
        health["checked_at"] = _now().isoformat()
        account.health = health
        account.last_probe_at = _now()
        if health.get("token_valid") is False and (health.get("error") or {}).get("category") == "auth" and account.status == AccountStatus.active:
            account.status = AccountStatus.revoked if (health.get("error") or {}).get("code") == "revoked" else AccountStatus.expired
        return health

    @classmethod
    async def test(cls, db: AsyncSession, member: Any, account_id: UUID) -> dict[str, Any]:
        account = await cls.get(db, member.workspace_id, account_id)
        health = await cls._probe_into(db, account)
        return {"account_id": str(account.id), "status": account.status.value, "token_valid": health.get("token_valid"),
                "scopes_missing": health.get("scopes_missing", []), "capabilities": account.capabilities, "limits_remaining": health.get("limits_remaining"),
                "health": health}

    @classmethod
    async def refresh(cls, db: AsyncSession, member: Any, account_id: UUID) -> SocialAccount:
        if not member.has("admin"):
            raise forbidden("Requires admin")
        account = await cls.get(db, member.workspace_id, account_id)
        ok = await cls._refresh_account(db, account, notify_on_failure=True)
        await _audit(db, member, "social.refresh", "social_account", account.id, after={"ok": ok, "status": account.status.value}, workspace_id=account.workspace_id)
        return account

    @classmethod
    async def _refresh_account(cls, db: AsyncSession, account: SocialAccount, *, notify_on_failure: bool) -> bool:
        adapter = get_adapter(account.platform.value)
        try:
            tokens = await cls.vault.get_tokens(db, account)
        except LookupError:
            tokens = None
        if tokens is None or not adapter.refresh_supported(tokens):
            await cls._mark_expiring(db, account, tokens, reason="refresh_unsupported", notify=notify_on_failure)
            return False
        try:
            new_tokens = await adapter.refresh(tokens)
        except PublishError as e:
            if e.category == "auth":
                account.status = AccountStatus.revoked if e.code == "revoked" else AccountStatus.expired
                await emit(db, "SOCIAL_ACCOUNT_EXPIRED", {"account_id": str(account.id), "platform": account.platform.value, "reason": e.message[:300]},
                           workspace_id=account.workspace_id)
                await cls._pause_posts(db, account, "account token expired")
                if notify_on_failure:
                    await _notify(db, account.workspace_id, "social.reconnect", f"Reconnect {account.display_name}",
                                  f"Refreshing the {account.platform.value} token failed: {e.message[:200]}", "/settings/social", severity="warning")
                return False
            log.warning("social.refresh_failed", account_id=str(account.id), category=e.category, error=e.message)
            account.health = {**(account.health or {}), "last_refresh_error": {"category": e.category, "message": e.message[:300], "at": _now().isoformat()}}
            return False
        await cls.vault.store_tokenset(db, account, new_tokens)
        if new_tokens.scopes:
            account.scopes = list(new_tokens.scopes)
        account.status = AccountStatus.active
        await cls._probe_into(db, account)
        return True

    @classmethod
    async def _mark_expiring(cls, db: AsyncSession, account: SocialAccount, tokens: TokenSet | None, *, reason: str, notify: bool) -> None:
        exp = tokens.expires_at if tokens else None
        await emit(db, "SOCIAL_ACCOUNT_TOKEN_EXPIRING", {"account_id": str(account.id), "platform": account.platform.value,
                                                         "expires_at": exp.isoformat() if exp else None, "reason": reason}, workspace_id=account.workspace_id)
        account.health = {**(account.health or {}), "expiring": True, "expires_at": exp.isoformat() if exp else None}
        if notify:
            when = exp.strftime("%Y-%m-%d") if exp else "soon"
            await _notify(db, account.workspace_id, "social.token_expiring", f"{account.display_name} needs reconnecting by {when}",
                          f"The {account.platform.value} token cannot be refreshed automatically; reconnect it to keep publishing.", "/settings/social",
                          severity="warning")

    @classmethod
    async def _pause_posts(cls, db: AsyncSession, account: SocialAccount, reason: str) -> int:
        rows = (await db.execute(select(ScheduledPost).where(ScheduledPost.social_account_id == account.id,
                                                             ScheduledPost.status.in_((ScheduleStatus.scheduled, ScheduleStatus.queued))))).scalars().unique().all()
        for sp in rows:
            await cancel_pending(db, f"publish:{sp.id}")
            sp.status = ScheduleStatus.paused
            sp.last_error = reason
            await emit(db, "POST_PAUSED", {"scheduled_post_id": str(sp.id), "reason": "account_" + account.status.value, "brand_id": str(sp.brand_id)},
                       workspace_id=sp.workspace_id)
        return len(rows)

    @classmethod
    async def token_monitor(cls, db: AsyncSession, *, window: timedelta = EXPIRING_WINDOW) -> int:
        """Hourly: tokens expiring within 7 days → refresh (where supported) or SOCIAL_ACCOUNT_TOKEN_EXPIRING + notification."""
        horizon = _now() + window
        rows = (await db.execute(select(OAuthToken.social_account_id).where(OAuthToken.token_kind == "access", OAuthToken.revoked_at.is_(None),
                                                                         OAuthToken.expires_at.is_not(None), OAuthToken.expires_at <= horizon))).scalars().all()
        handled = 0
        for account_id in set(rows):
            account = await db.get(SocialAccount, account_id)
            if account is None or account.status in (AccountStatus.disconnected, AccountStatus.revoked):
                continue
            already = (account.health or {}).get("expiring_notified_at")
            if already and datetime.fromisoformat(already) > _now() - timedelta(days=1):
                continue
            ok = await cls._refresh_account(db, account, notify_on_failure=True)
            if not ok:
                account.health = {**(account.health or {}), "expiring_notified_at": _now().isoformat()}
            handled += 1
        # tokens that already expired → expired status + pause posts
        expired = (await db.execute(select(OAuthToken.social_account_id).where(OAuthToken.token_kind == "access", OAuthToken.revoked_at.is_(None),
                                                                            OAuthToken.expires_at.is_not(None), OAuthToken.expires_at < _now()))).scalars().all()
        for account_id in set(expired):
            account = await db.get(SocialAccount, account_id)
            if account is None or account.status != AccountStatus.active:
                continue
            adapter = get_adapter(account.platform.value)
            try:
                tokens = await cls.vault.get_tokens(db, account)
            except LookupError:
                tokens = None
            if tokens and adapter.refresh_supported(tokens) and await cls._refresh_account(db, account, notify_on_failure=True):
                continue
            account.status = AccountStatus.expired
            await emit(db, "SOCIAL_ACCOUNT_EXPIRED", {"account_id": str(account.id), "platform": account.platform.value, "reason": "token expired"},
                       workspace_id=account.workspace_id)
            await cls._pause_posts(db, account, "account token expired")
            await _notify(db, account.workspace_id, "social.reconnect", f"Reconnect {account.display_name}",
                          f"The {account.platform.value} token has expired; scheduled posts are paused until you reconnect.", "/settings/social", severity="warning")
            handled += 1
        return handled

    # ---- disconnect ------------------------------------------------------------------------------------
    @classmethod
    async def disconnect(cls, db: AsyncSession, member: Any, account_id: UUID, *, force: bool = False) -> SocialAccount:
        if not member.has("admin"):
            raise forbidden("Requires admin")
        account = await cls.get(db, member.workspace_id, account_id)
        live = (await db.execute(select(ScheduledPost).where(ScheduledPost.social_account_id == account.id, ScheduledPost.status.in_(LIVE)))).scalars().unique().all()
        if live and not force:
            raise conflict("live_scheduled_posts", f"{len(live)} scheduled posts use this account; pass force=true to cancel them")
        for sp in live:
            if sp.status == ScheduleStatus.publishing:
                continue
            await cancel_pending(db, f"publish:{sp.id}")
            sp.status = ScheduleStatus.cancelled
            await emit(db, "POST_CANCELLED", {"scheduled_post_id": str(sp.id), "reason": "account_disconnected", "brand_id": str(sp.brand_id)},
                       workspace_id=sp.workspace_id, actor={"type": "user", "id": str(member.user.id)})
        adapter = get_adapter(account.platform.value)
        try:
            tokens = await cls.vault.get_tokens(db, account)
            await adapter.revoke(tokens)
        except (LookupError, PublishError):
            pass
        await cls.vault.revoke_all(db, account.id)
        account.status = AccountStatus.disconnected
        account.disconnected_at = _now()
        await emit(db, "SOCIAL_ACCOUNT_REVOKED", {"account_id": str(account.id), "platform": account.platform.value, "reason": "disconnected by user"},
                   workspace_id=account.workspace_id, actor={"type": "user", "id": str(member.user.id)})
        await _audit(db, member, "social.disconnect", "social_account", account.id, after={"cancelled_posts": len(live)}, workspace_id=account.workspace_id)
        return account

    @classmethod
    async def mark_revoked(cls, db: AsyncSession, *, platform: str, external_ids: list[str] | None = None, user_external_id: str | None = None,
                           reason: str = "deauthorized") -> int:
        """Webhook path (Meta deauthorize / data deletion): mark matching accounts revoked and pause their posts."""
        q = select(SocialAccount).where(SocialAccount.platform == _platform(platform), SocialAccount.status != AccountStatus.disconnected)
        rows = (await db.execute(q)).scalars().unique().all()
        n = 0
        for account in rows:
            match = False
            if external_ids and (account.external_id in external_ids or (account.parent_external_id in external_ids)):
                match = True
            if user_external_id and not match:
                live = await cls.vault.live_tokens(db, account.id)
                access = live.get("access")
                if access is not None and str((access.meta or {}).get("user_id")) == str(user_external_id):
                    match = True
                if account.parent_external_id == user_external_id:
                    match = True
            if not match:
                continue
            account.status = AccountStatus.revoked
            await cls.vault.revoke_all(db, account.id)
            await emit(db, "SOCIAL_ACCOUNT_REVOKED", {"account_id": str(account.id), "platform": platform, "reason": reason}, workspace_id=account.workspace_id)
            await cls._pause_posts(db, account, f"account access revoked ({reason})")
            await _notify(db, account.workspace_id, "social.reconnect", f"{account.display_name} access was revoked", f"Reason: {reason}. Reconnect to resume.",
                          "/settings/social", severity="error")
            n += 1
        return n

    # ---- selection stash (Redis, 10 min) -------------------------------------------------------------
    @staticmethod
    async def _stash(token: str, payload: dict[str, Any]) -> None:
        from app.core.redis import get_redis
        await get_redis().set(f"social:select:{token}", json.dumps(payload, default=str), ex=SELECTION_TTL_S)

    @staticmethod
    async def _unstash(token: str) -> dict[str, Any] | None:
        from app.core.redis import get_redis
        raw = await get_redis().get(f"social:select:{token}")
        return json.loads(raw) if raw else None

    @staticmethod
    async def _forget(token: str) -> None:
        from app.core.redis import get_redis
        await get_redis().delete(f"social:select:{token}")


class _Member:
    """Minimal member shape for callback-time service calls (the user is resolved from the OAuth state)."""

    def __init__(self, user: User | None, workspace_id: UUID) -> None:
        self.user = user
        self.workspace_id = workspace_id
        self.role = None

    def has(self, role: str) -> bool:
        return True


def _what(platform: str, flavor: str) -> str:
    return {"facebook": "Facebook Page", "instagram": "Instagram professional account" + (" linked to a Page" if flavor == "facebook_login" else ""),
            "linkedin": "organization with an admin role" if flavor == "organization" else "member profile", "youtube": "YouTube channel",
            "gbp": "verified business location", "pinterest": "Pinterest account"}.get(platform, "account")


def _tokens_to_json(t: TokenSet) -> dict[str, Any]:
    return {"access_token": t.access_token, "refresh_token": t.refresh_token, "expires_at": t.expires_at.isoformat() if t.expires_at else None,
            "refresh_expires_at": t.refresh_expires_at.isoformat() if t.refresh_expires_at else None, "scopes": t.scopes, "extra": t.extra}


def _tokens_from_json(d: dict[str, Any]) -> TokenSet:
    return TokenSet(access_token=d["access_token"], refresh_token=d.get("refresh_token"),
                    expires_at=datetime.fromisoformat(d["expires_at"]) if d.get("expires_at") else None,
                    refresh_expires_at=datetime.fromisoformat(d["refresh_expires_at"]) if d.get("refresh_expires_at") else None,
                    scopes=list(d.get("scopes") or []), extra=dict(d.get("extra") or {}))


def _acc_to_json(a: ConnectableAccount) -> dict[str, Any]:
    return {"external_id": a.external_id, "display_name": a.display_name, "handle": a.handle, "avatar_url": a.avatar_url, "account_type": a.account_type,
            "parent_external_id": a.parent_external_id, "extra": a.extra}


def _acc_from_json(d: dict[str, Any]) -> ConnectableAccount:
    return ConnectableAccount(external_id=d["external_id"], display_name=d.get("display_name") or d["external_id"], handle=d.get("handle"),
                              avatar_url=d.get("avatar_url"), account_type=d.get("account_type"), parent_external_id=d.get("parent_external_id"),
                              extra=dict(d.get("extra") or {}))


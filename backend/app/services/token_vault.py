"""TokenVault: envelope-encrypted OAuth tokens (doc 19 §19.4).

Tokens are sealed with AES-256-GCM (``app.core.crypto``) using ``aad = f"{social_account_id}:{kind}"`` so a
ciphertext can never be replayed for another account or token kind. One live row per (account, kind): storing a
new token revokes the previous live one (``revoked_at``) and links it via ``rotated_from``.
Plaintext only exists in memory for the duration of a call; it is never logged or returned by the API.
"""
from __future__ import annotations

from datetime import UTC, datetime
from typing import Any
from uuid import UUID

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.crypto import seal, unseal
from app.core.ports.social_adapter import TokenSet
from app.models.social import OAuthToken, SocialAccount

KIND_ACCESS = "access"
KIND_REFRESH = "refresh"
KIND_PAGE = "page"
KIND_LONG_LIVED_USER = "long_lived_user"


def _aad(account_id: UUID, kind: str) -> str:
    return f"{account_id}:{kind}"


class TokenVault:
    """All reads/writes of ``oauth_tokens`` go through here."""

    async def store(self, db: AsyncSession, workspace_id: UUID, social_account_id: UUID, kind: str, token: str,
                    expires_at: datetime | None = None, refresh_expires_at: datetime | None = None,
                    meta: dict[str, Any] | None = None) -> OAuthToken:
        """Seal ``token`` and make it the live token of ``kind``; the previous live token is revoked and linked."""
        now = datetime.now(UTC)
        previous = (await db.execute(
            select(OAuthToken).where(OAuthToken.social_account_id == social_account_id, OAuthToken.token_kind == kind,
                                     OAuthToken.revoked_at.is_(None)))).scalars().all()
        rotated_from: UUID | None = None
        for p in previous:
            p.revoked_at = now
            rotated_from = p.id
        if previous:
            await db.flush()  # free the (account, kind, revoked_at=NULL) uniqueness slot before inserting
        sealed = seal(token, aad=_aad(social_account_id, kind))
        row = OAuthToken(workspace_id=workspace_id, social_account_id=social_account_id, token_kind=kind,
                         ciphertext=sealed.ciphertext, nonce=sealed.nonce, key_version=sealed.key_version,
                         expires_at=expires_at, refresh_expires_at=refresh_expires_at, rotated_from=rotated_from,
                         meta=meta or {})
        db.add(row)
        await db.flush()
        return row

    async def store_tokenset(self, db: AsyncSession, account: SocialAccount, tokens: TokenSet) -> None:
        """Persist every token carried by a ``TokenSet`` (access, refresh, page token from ``extra``)."""
        meta = {k: v for k, v in tokens.extra.items() if k not in ("page_token", "refresh_token") and _jsonable(v)}
        await self.store(db, account.workspace_id, account.id, KIND_ACCESS, tokens.access_token,
                         expires_at=tokens.expires_at, refresh_expires_at=tokens.refresh_expires_at,
                         meta={**meta, "scopes": tokens.scopes})
        if tokens.refresh_token:
            await self.store(db, account.workspace_id, account.id, KIND_REFRESH, tokens.refresh_token,
                             expires_at=tokens.refresh_expires_at, meta={})
        page_token = tokens.extra.get("page_token")
        if page_token:
            await self.store(db, account.workspace_id, account.id, KIND_PAGE, page_token, expires_at=None,
                             meta={"page_id": tokens.extra.get("page_id") or account.parent_external_id or account.external_id})

    async def live_tokens(self, db: AsyncSession, social_account_id: UUID) -> dict[str, OAuthToken]:
        rows = (await db.execute(
            select(OAuthToken).where(OAuthToken.social_account_id == social_account_id, OAuthToken.revoked_at.is_(None))
            .order_by(OAuthToken.issued_at.desc()))).scalars().all()
        out: dict[str, OAuthToken] = {}
        for r in rows:
            out.setdefault(r.token_kind, r)
        return out

    async def get_tokens(self, db: AsyncSession, account: SocialAccount) -> TokenSet:
        """Unseal the live tokens of an account into a ``TokenSet`` (page tokens land in ``extra['page_token']``)."""
        live = await self.live_tokens(db, account.id)
        access = live.get(KIND_ACCESS)
        if access is None:
            raise LookupError(f"no live access token for account {account.id}")
        ts = TokenSet(
            access_token=unseal(access.ciphertext, access.nonce, access.key_version, aad=_aad(account.id, KIND_ACCESS)),
            expires_at=access.expires_at, refresh_expires_at=access.refresh_expires_at,
            scopes=list(account.scopes or access.meta.get("scopes") or []),
            extra={k: v for k, v in (access.meta or {}).items() if k != "scopes"},
        )
        refresh = live.get(KIND_REFRESH)
        if refresh is not None:
            ts.refresh_token = unseal(refresh.ciphertext, refresh.nonce, refresh.key_version, aad=_aad(account.id, KIND_REFRESH))
            ts.refresh_expires_at = ts.refresh_expires_at or refresh.expires_at
        page = live.get(KIND_PAGE)
        if page is not None:
            ts.extra["page_token"] = unseal(page.ciphertext, page.nonce, page.key_version, aad=_aad(account.id, KIND_PAGE))
            ts.extra["page_id"] = (page.meta or {}).get("page_id")
        return ts

    async def access_expires_at(self, db: AsyncSession, social_account_id: UUID) -> datetime | None:
        live = await self.live_tokens(db, social_account_id)
        tok = live.get(KIND_ACCESS)
        return tok.expires_at if tok else None

    async def revoke_all(self, db: AsyncSession, social_account_id: UUID) -> int:
        res = await db.execute(update(OAuthToken).where(OAuthToken.social_account_id == social_account_id,
                                                        OAuthToken.revoked_at.is_(None))
                               .values(revoked_at=datetime.now(UTC)))
        return res.rowcount or 0


def _jsonable(v: Any) -> bool:
    return isinstance(v, (str, int, float, bool, list, dict)) or v is None


token_vault = TokenVault()

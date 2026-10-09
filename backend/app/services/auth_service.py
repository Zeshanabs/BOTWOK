"""AuthService: signup, login (argon2 + lockout), access/refresh tokens with rotation + family reuse detection,
logout, me, password reset."""
from __future__ import annotations

import asyncio
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import UUID

from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.core.errors import ProblemError, conflict
from app.core.ids import new_id
from app.core.logging import get_logger
from app.core.redis import get_redis
from app.core.security import (
    create_access_token,
    hash_password,
    hash_token,
    new_opaque_token,
    verify_password,
)
from app.models.enums import MemberRole
from app.models.identity import RefreshSession, User, Workspace, WorkspaceMember
from app.services.audit_service import audit, safe_ip
from app.services.workspace_service import WorkspaceService

log = get_logger("auth")

LOCKOUT_MAX_FAILURES = 10
LOCKOUT_WINDOW_S = 15 * 60
RESET_TTL_S = 30 * 60
REFRESH_COOKIE = "botwok_refresh"
ACCESS_COOKIE = "botwok_access"
REFRESH_COOKIE_PATH = "/api/v1/auth"
_DUMMY_HASH: str | None = None


# ---------------------------------------------------------------- pure helpers (unit-tested)
def lockout_key(email: str) -> str:
    return f"auth:fail:{email.strip().lower()}"


def reset_key(token_hash: str) -> str:
    return f"auth:reset:{token_hash}"


def is_locked_out(failures: Any, max_failures: int = LOCKOUT_MAX_FAILURES) -> bool:
    return int(failures or 0) >= max_failures


async def register_failure(redis: Any, email: str, window_s: int = LOCKOUT_WINDOW_S) -> int:
    """INCR the failure counter; the window starts at the first failure (fixed window)."""
    key = lockout_key(email)
    n = int(await redis.incr(key))
    if n == 1 or int(await redis.ttl(key)) < 0:
        await redis.expire(key, window_s)
    return n


def derive_workspace_name(email: str, full_name: str | None, workspace_name: str | None) -> str:
    if workspace_name and workspace_name.strip():
        return workspace_name.strip()
    if full_name and full_name.strip():
        return f"{full_name.strip().split()[0]}'s Workspace"
    local = email.split("@", 1)[0]
    pretty = " ".join(p for p in local.replace(".", " ").replace("_", " ").replace("-", " ").split() if p).title() or "My"
    return f"{pretty}'s Workspace"


def default_full_name(email: str) -> str:
    local = email.split("@", 1)[0]
    return " ".join(p for p in local.replace(".", " ").replace("_", " ").replace("-", " ").split() if p).title() or local


async def _hash_pw(password: str) -> str:
    return await asyncio.to_thread(hash_password, password)


async def _verify_pw(password: str, password_hash: str | None) -> bool:
    global _DUMMY_HASH
    if not password_hash:  # equalize timing for unknown users
        if _DUMMY_HASH is None:
            _DUMMY_HASH = await _hash_pw("botwok-dummy-password")
        await asyncio.to_thread(verify_password, password, _DUMMY_HASH)
        return False
    return await asyncio.to_thread(verify_password, password, password_hash)


@dataclass
class IssuedSession:
    user: User
    access_token: str
    refresh_token: str
    expires_in: int
    workspace: Workspace | None
    role: MemberRole | None


class AuthService:
    # ------------------------------------------------------------ tokens
    @staticmethod
    async def _pick_membership(db: AsyncSession, user_id: UUID, workspace_id: UUID | None) -> tuple[Workspace | None, MemberRole | None]:
        q = (select(Workspace, WorkspaceMember.role).join(WorkspaceMember, WorkspaceMember.workspace_id == Workspace.id)
             .where(WorkspaceMember.user_id == user_id))
        if workspace_id:
            row = (await db.execute(q.where(Workspace.id == workspace_id))).first()
            if row:
                return row[0], row[1]
        row = (await db.execute(q.order_by(WorkspaceMember.joined_at, Workspace.created_at).limit(1))).first()
        return (row[0], row[1]) if row else (None, None)

    @classmethod
    async def issue_session(cls, db: AsyncSession, user: User, *, workspace_id: UUID | None = None, family_id: UUID | None = None,
                            user_agent: str | None = None, ip: str | None = None) -> IssuedSession:
        ws, role = await cls._pick_membership(db, user.id, workspace_id)
        access = create_access_token(user.id, ws.id if ws else None, role.value if role else None)
        refresh, refresh_hash = new_opaque_token()
        db.add(RefreshSession(user_id=user.id, token_hash=refresh_hash, family_id=family_id or new_id(),
                              user_agent=(user_agent or "")[:500] or None, ip=safe_ip(ip),
                              expires_at=datetime.now(UTC) + timedelta(days=settings.refresh_token_days)))
        await db.flush()
        return IssuedSession(user, access, refresh, settings.access_token_minutes * 60, ws, role)

    # ------------------------------------------------------------ signup / login
    @classmethod
    async def signup(cls, db: AsyncSession, *, email: str, password: str, full_name: str | None = None,
                     workspace_name: str | None = None, invitation_token: str | None = None,
                     user_agent: str | None = None, ip: str | None = None, request: Any = None) -> IssuedSession:
        email = email.strip().lower()
        if (await db.execute(select(User.id).where(User.email == email))).scalar_one_or_none():
            raise conflict("email_taken", "An account with this email already exists")
        invitation = None
        if invitation_token:
            invitation = await WorkspaceService.find_invitation(db, invitation_token)
            if (not invitation or invitation.accepted_at or invitation.expires_at <= datetime.now(UTC)
                    or invitation.email.lower() != email):
                raise ProblemError(400, "invalid_invitation", "Invalid invitation", "The invitation is invalid, expired, or for another email")
        if settings.signup_mode == "invite_only" and invitation is None:
            users = (await db.execute(select(func.count()).select_from(User))).scalar_one()
            if users > 0:  # the very first user bootstraps the install
                raise ProblemError(403, "signup_closed", "Signup is invite-only", "Ask a workspace admin for an invitation")

        user = User(email=email, password_hash=await _hash_pw(password), full_name=(full_name or "").strip() or default_full_name(email),
                    preferences={})
        db.add(user)
        await db.flush()
        if invitation is not None:
            ws, _role = await WorkspaceService.accept_invitation(db, user, invitation_token or "", request=request)
        else:
            ws = await WorkspaceService.create(db, user, derive_workspace_name(email, full_name, workspace_name))
        await audit(db, user, "auth.signup", "user", user.id, after={"email": email, "via_invitation": invitation is not None},
                    request=request, workspace_id=ws.id)
        return await cls.issue_session(db, user, workspace_id=ws.id, user_agent=user_agent, ip=ip)

    @classmethod
    async def login(cls, db: AsyncSession, *, email: str, password: str, workspace_id: UUID | None = None,
                    user_agent: str | None = None, ip: str | None = None, request: Any = None) -> IssuedSession:
        email = email.strip().lower()
        redis = get_redis()
        try:
            failures = await redis.get(lockout_key(email))
        except Exception as e:  # Redis down → fail open on lockout, log loudly
            log.warning("auth.lockout_unavailable", error=str(e))
            redis, failures = None, 0
        if is_locked_out(failures):
            raise ProblemError(423, "locked", "Account temporarily locked",
                               "Too many failed login attempts. Try again in 15 minutes or reset your password.")
        user = (await db.execute(select(User).where(User.email == email))).scalar_one_or_none()
        ok = await _verify_pw(password, user.password_hash if user else None)
        if not ok or not user or not user.is_active:
            n = 0
            if redis is not None:
                try:
                    n = await register_failure(redis, email)
                except Exception as e:
                    log.warning("auth.lockout_unavailable", error=str(e))
            ws_id = None
            if user:
                ws, _ = await cls._pick_membership(db, user.id, None)
                ws_id = ws.id if ws else None
            await audit(db, user if user else {"type": "system", "id": "anonymous"}, "auth.login_failed", "user",
                        user.id if user else None, meta={"email": email, "failures": n, "locked": is_locked_out(n)},
                        request=request, workspace_id=ws_id)
            await db.commit()  # keep the audit row even though we raise
            raise ProblemError(401, "invalid_credentials", "Invalid email or password")
        if redis is not None:
            try:
                await redis.delete(lockout_key(email))
            except Exception:
                pass
        user.last_login_at = datetime.now(UTC)
        issued = await cls.issue_session(db, user, workspace_id=workspace_id, user_agent=user_agent, ip=ip)
        await audit(db, user, "auth.login", "user", user.id, request=request,
                    workspace_id=issued.workspace.id if issued.workspace else None)
        return issued

    # ------------------------------------------------------------ refresh / logout
    @staticmethod
    async def revoke_family(db: AsyncSession, family_id: UUID) -> int:
        res = await db.execute(update(RefreshSession).where(RefreshSession.family_id == family_id, RefreshSession.revoked_at.is_(None))
                               .values(revoked_at=datetime.now(UTC)))
        return int(getattr(res, "rowcount", 0) or 0)

    @classmethod
    async def refresh(cls, db: AsyncSession, refresh_token: str | None, *, workspace_id: UUID | None = None,
                      user_agent: str | None = None, ip: str | None = None, request: Any = None) -> IssuedSession:
        if not refresh_token:
            raise ProblemError(401, "unauthorized", "Refresh token missing")
        sess = (await db.execute(select(RefreshSession).where(RefreshSession.token_hash == hash_token(refresh_token))
                                 .with_for_update())).scalar_one_or_none()
        if not sess:
            raise ProblemError(401, "unauthorized", "Invalid refresh token")
        now = datetime.now(UTC)
        if sess.revoked_at is not None:
            # Reuse of a rotated/revoked token → assume theft: revoke the whole family.
            n = await cls.revoke_family(db, sess.family_id)
            user = await db.get(User, sess.user_id)
            await audit(db, user or {"type": "system", "id": "auth"}, "auth.refresh_reuse_detected", "refresh_family", sess.family_id,
                        meta={"revoked_sessions": n}, request=request)
            await db.commit()
            raise ProblemError(401, "session_revoked", "Session revoked", "Refresh token reuse detected; please sign in again")
        if sess.expires_at <= now:
            raise ProblemError(401, "session_expired", "Session expired")
        user = await db.get(User, sess.user_id)
        if not user or not user.is_active:
            raise ProblemError(401, "unauthorized", "User not found")
        sess.revoked_at = now  # rotate
        await db.flush()
        return await cls.issue_session(db, user, workspace_id=workspace_id, family_id=sess.family_id,
                                       user_agent=user_agent, ip=ip)

    @classmethod
    async def logout(cls, db: AsyncSession, refresh_token: str | None, request: Any = None) -> bool:
        if not refresh_token:
            return False
        sess = (await db.execute(select(RefreshSession).where(RefreshSession.token_hash == hash_token(refresh_token)))).scalar_one_or_none()
        if not sess:
            return False
        await cls.revoke_family(db, sess.family_id)
        user = await db.get(User, sess.user_id)
        await audit(db, user or {"type": "system", "id": "auth"}, "auth.logout", "user", sess.user_id, request=request)
        return True

    @staticmethod
    async def revoke_all_sessions(db: AsyncSession, user_id: UUID) -> int:
        res = await db.execute(update(RefreshSession).where(RefreshSession.user_id == user_id, RefreshSession.revoked_at.is_(None))
                               .values(revoked_at=datetime.now(UTC)))
        return int(getattr(res, "rowcount", 0) or 0)

    # ------------------------------------------------------------ me
    @staticmethod
    async def me(db: AsyncSession, user: User) -> dict[str, Any]:
        rows = await WorkspaceService.list_for_user(db, user.id)
        return {"user": user, "memberships": [{"workspace": w, "role": r} for w, r in rows]}

    # ------------------------------------------------------------ password reset
    @classmethod
    async def request_password_reset(cls, db: AsyncSession, email: str, request: Any = None) -> str | None:
        """Always succeeds from the caller's view (no enumeration). Returns the token (for tests) or None."""
        email = email.strip().lower()
        user = (await db.execute(select(User).where(User.email == email))).scalar_one_or_none()
        if not user or not user.is_active:
            return None
        token, token_hash = new_opaque_token()
        try:
            await get_redis().set(reset_key(token_hash), str(user.id), ex=RESET_TTL_S)
        except Exception as e:
            raise ProblemError(503, "unavailable", "Password reset temporarily unavailable") from e
        await audit(db, user, "auth.password_reset_requested", "user", user.id, request=request)
        from app.services.notification_service import NotificationService
        link = f"{settings.public_base_url.rstrip('/')}/reset-password?token={token}"
        await NotificationService.send_email(
            user.email, "Reset your Botwok password",
            f"Hi {user.full_name},\n\nUse this link to reset your password (valid for 30 minutes):\n{link}\n\n"
            "If you didn't request this, you can ignore this email.")
        return token

    @classmethod
    async def confirm_password_reset(cls, db: AsyncSession, token: str, new_password: str, request: Any = None) -> User:
        try:
            user_id = await get_redis().getdel(reset_key(hash_token(token)))
        except Exception as e:
            raise ProblemError(503, "unavailable", "Password reset temporarily unavailable") from e
        if not user_id:
            raise ProblemError(400, "invalid_token", "Invalid or expired reset token")
        user = await db.get(User, UUID(str(user_id)))
        if not user or not user.is_active:
            raise ProblemError(400, "invalid_token", "Invalid or expired reset token")
        user.password_hash = await _hash_pw(new_password)
        n = await cls.revoke_all_sessions(db, user.id)
        try:
            await get_redis().delete(lockout_key(user.email))
        except Exception:
            pass
        await audit(db, user, "auth.password_reset", "user", user.id, meta={"revoked_sessions": n}, request=request)
        return user

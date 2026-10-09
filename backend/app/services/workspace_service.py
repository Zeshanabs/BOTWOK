"""WorkspaceService: workspaces, members/roles, invitations, API keys, usage budgets, workspace settings."""
from __future__ import annotations

import re
import secrets
import unicodedata
import zoneinfo
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import UUID

from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.core.errors import ProblemError, conflict, forbidden, not_found, validation
from app.core.security import hash_token, new_opaque_token
from app.models.enums import ROLE_RANK, MemberRole
from app.models.identity import ApiKey, Invitation, User, Workspace, WorkspaceMember
from app.models.platform import UsageBudget, UsageLedger
from app.services.audit_service import audit
from app.services.notification_service import channel_aad, seal_secret

INVITATION_TTL = timedelta(days=7)
API_KEY_PREFIX = "bw_live_"
_API_KEY_RE = re.compile(r"^bw_live_([0-9a-f]{8})_([A-Za-z0-9_\-]{20,})$")
_SCOPE_RE = re.compile(r"^[a-z][a-z_]*:(read|write)$")
FORBIDDEN_SCOPE_DOMAINS = {"members", "workspace", "api_keys", "admin", "billing"}
DEFAULT_BUDGETS: list[tuple[str, str, float]] = [("ai_cost", "month", 50.0), ("ai_cost", "day", 10.0)]
RESERVED_SLUGS = {"api", "new", "admin", "login", "signup", "settings", "w"}


# ---------------------------------------------------------------- pure helpers (unit-tested)
def slugify(name: str, max_len: int = 48) -> str:
    s = unicodedata.normalize("NFKD", name or "").encode("ascii", "ignore").decode().lower()
    s = re.sub(r"[^a-z0-9]+", "-", s).strip("-")
    s = re.sub(r"-{2,}", "-", s)[:max_len].strip("-")
    if not s:
        return "workspace"
    if len(s) < 2 or s in RESERVED_SLUGS:
        s = f"{s}-workspace"
    return s


def new_api_key() -> tuple[str, str, str]:
    """→ (full_key, prefix, sha256_hash). Format: ``bw_live_<8 hex prefix>_<secret>``."""
    prefix = secrets.token_hex(4)
    full = f"{API_KEY_PREFIX}{prefix}_{secrets.token_urlsafe(32)}"
    return full, prefix, hash_token(full)


def parse_api_key(raw: str) -> str | None:
    """Return the prefix if `raw` has the API-key format, else None."""
    m = _API_KEY_RE.match((raw or "").strip())
    return m.group(1) if m else None


def validate_scopes(scopes: list[str]) -> list[str]:
    out = []
    for s in dict.fromkeys(x.strip() for x in scopes):
        if not _SCOPE_RE.match(s) or s.split(":")[0] in FORBIDDEN_SCOPE_DOMAINS:
            raise validation(f"Invalid scope '{s}'", [{"code": "invalid_scope", "field": "scopes", "message": s}])
        out.append(s)
    return out


def role_rank(role: MemberRole | str) -> int:
    return ROLE_RANK[role.value if isinstance(role, MemberRole) else role]


def mask_url(url: str | None) -> str | None:
    if not url:
        return None
    from urllib.parse import urlparse
    p = urlparse(url)
    return f"{p.scheme}://{p.hostname}/…{url[-4:]}"


def _actor_role(member: Any) -> MemberRole:
    return member.role if isinstance(member.role, MemberRole) else MemberRole(member.role)


@dataclass
class MemberRow:
    user_id: UUID
    email: str
    full_name: str
    role: MemberRole
    joined_at: datetime | None
    invited_by: UUID | None


class WorkspaceService:
    # ------------------------------------------------------------ workspaces
    @staticmethod
    async def unique_slug(db: AsyncSession, base: str, exclude_id: UUID | None = None) -> str:
        base = slugify(base)
        q = select(Workspace.slug).where((Workspace.slug == base) | Workspace.slug.like(f"{base}-%"))
        if exclude_id:
            q = q.where(Workspace.id != exclude_id)
        taken = {s.lower() for s in (await db.execute(q)).scalars()}
        if base not in taken:
            return base
        i = 2
        while f"{base}-{i}" in taken:
            i += 1
        return f"{base}-{i}"

    @classmethod
    async def create(cls, db: AsyncSession, user: User, name: str, slug: str | None = None, *,
                     with_default_budgets: bool = True) -> Workspace:
        name = name.strip()
        if not name:
            raise validation("Workspace name is required")
        ws = Workspace(name=name, slug=await cls.unique_slug(db, slug or name), created_by=user.id, settings={"timezone": "UTC"})
        db.add(ws)
        await db.flush()
        db.add(WorkspaceMember(workspace_id=ws.id, user_id=user.id, role=MemberRole.owner))
        if with_default_budgets:
            for kind, period, limit in DEFAULT_BUDGETS:
                db.add(UsageBudget(workspace_id=ws.id, kind=kind, period=period, limit_value=limit, hard=True))
        await db.flush()
        await audit(db, user, "workspace.create", "workspace", ws.id, after={"name": ws.name, "slug": ws.slug},
                    workspace_id=ws.id)
        return ws

    @staticmethod
    async def resolve(db: AsyncSession, ws_ref: str) -> Workspace | None:
        """Find a workspace by UUID or slug."""
        try:
            return await db.get(Workspace, UUID(str(ws_ref)))
        except ValueError:
            return (await db.execute(select(Workspace).where(Workspace.slug == ws_ref))).scalar_one_or_none()

    @staticmethod
    async def membership(db: AsyncSession, workspace_id: UUID, user_id: UUID) -> WorkspaceMember | None:
        return (await db.execute(select(WorkspaceMember).where(WorkspaceMember.workspace_id == workspace_id,
                                                               WorkspaceMember.user_id == user_id))).scalar_one_or_none()

    @staticmethod
    async def list_for_user(db: AsyncSession, user_id: UUID) -> list[tuple[Workspace, MemberRole]]:
        rows = (await db.execute(select(Workspace, WorkspaceMember.role).join(WorkspaceMember, WorkspaceMember.workspace_id == Workspace.id)
                                 .where(WorkspaceMember.user_id == user_id).order_by(WorkspaceMember.joined_at, Workspace.created_at))).all()
        return [(w, r) for w, r in rows]

    @staticmethod
    async def get(db: AsyncSession, workspace_id: UUID) -> Workspace:
        ws = await db.get(Workspace, workspace_id)
        if not ws:
            raise not_found("Workspace")
        return ws

    @classmethod
    async def update(cls, db: AsyncSession, member: Any, *, name: str | None = None, slug: str | None = None,
                     request: Any = None) -> Workspace:
        if not member.has("admin"):
            raise forbidden("Requires role admin or higher")
        ws = await cls.get(db, member.workspace_id)
        before = {"name": ws.name, "slug": ws.slug}
        if name is not None and name.strip():
            ws.name = name.strip()
        if slug is not None and slugify(slug) != ws.slug:
            wanted = slugify(slug)
            exists = (await db.execute(select(Workspace.id).where(Workspace.slug == wanted, Workspace.id != ws.id))).scalar_one_or_none()
            if exists:
                raise conflict("slug_taken", f"Slug '{wanted}' is already in use")
            ws.slug = wanted
        await audit(db, member, "workspace.update", "workspace", ws.id, before=before,
                    after={"name": ws.name, "slug": ws.slug}, request=request)
        return ws

    @classmethod
    async def delete(cls, db: AsyncSession, member: Any, request: Any = None) -> None:
        if _actor_role(member) != MemberRole.owner:
            raise forbidden("Only an owner can delete the workspace")
        ws = await cls.get(db, member.workspace_id)
        await audit(db, member, "workspace.delete", "workspace", ws.id, before={"name": ws.name, "slug": ws.slug},
                    request=request)
        await db.flush()
        await db.execute(delete(Workspace).where(Workspace.id == ws.id))  # DB-level ON DELETE CASCADE
        db.expunge(ws)

    # ------------------------------------------------------------ settings
    @staticmethod
    def settings_view(ws: Workspace) -> dict[str, Any]:
        s = ws.settings or {}
        nc = s.get("notification_channels") or {}
        policy = s.get("approval_policy") or {}
        return {
            "workspace_id": ws.id, "name": ws.name, "slug": ws.slug, "timezone": s.get("timezone") or "UTC",
            "notification_channels": {
                "in_app": nc.get("in_app", True), "email": bool(nc.get("email", False)),
                "slack_configured": bool(nc.get("slack_webhook")), "slack_webhook_hint": nc.get("slack_hint"),
                "webhook_configured": bool(nc.get("webhook")), "webhook_url_hint": nc.get("webhook_hint"),
            },
            "approval_policy": policy, "retention_days": s.get("retention_days"),
        }

    @classmethod
    async def update_settings(cls, db: AsyncSession, member: Any, patch: Any, request: Any = None) -> Workspace:
        """Partial merge of workspace.settings (timezone, notification channels, approval policy, retention)."""
        if not member.has("admin"):
            raise forbidden("Requires role admin or higher")
        ws = await cls.get(db, member.workspace_id)
        before = cls.settings_view(ws)
        s = dict(ws.settings or {})
        if patch.name:
            ws.name = patch.name.strip()
        if patch.timezone is not None:
            try:
                zoneinfo.ZoneInfo(patch.timezone)
            except (zoneinfo.ZoneInfoNotFoundError, ValueError) as e:
                raise validation(f"Unknown timezone '{patch.timezone}'",
                                 [{"code": "invalid_timezone", "field": "timezone", "message": patch.timezone}]) from e
            s["timezone"] = patch.timezone
        if patch.retention_days is not None:
            s["retention_days"] = patch.retention_days
        if patch.approval_policy is not None:
            s["approval_policy"] = patch.approval_policy.model_dump(mode="json")
        if patch.notification_channels is not None:
            nc = dict(s.get("notification_channels") or {})
            upd = patch.notification_channels
            for flag in ("in_app", "email"):
                if getattr(upd, flag) is not None:
                    nc[flag] = getattr(upd, flag)
            for field, key, hint in (("slack_webhook_url", "slack_webhook", "slack_hint"), ("webhook_url", "webhook", "webhook_hint")):
                val = getattr(upd, field)
                if val is None:
                    continue
                val = val.strip()
                if not val:
                    nc.pop(key, None)
                    nc.pop(hint, None)
                    continue
                if not (val.startswith("https://") or (settings.is_local and val.startswith("http://"))):
                    raise validation(f"{field} must be an https URL", [{"code": "invalid_url", "field": field, "message": "https required"}])
                nc[key] = seal_secret(val, channel_aad(ws.id, "slack" if key == "slack_webhook" else "webhook"))
                nc[hint] = mask_url(val)
            s["notification_channels"] = nc
        ws.settings = s
        await audit(db, member, "settings.update", "workspace", ws.id, before=before, after=cls.settings_view(ws), request=request)
        return ws

    # ------------------------------------------------------------ members
    @staticmethod
    async def list_members(db: AsyncSession, workspace_id: UUID) -> list[MemberRow]:
        rows = (await db.execute(select(WorkspaceMember, User).join(User, User.id == WorkspaceMember.user_id)
                                 .where(WorkspaceMember.workspace_id == workspace_id).order_by(WorkspaceMember.joined_at))).all()
        return [MemberRow(user_id=u.id, email=u.email, full_name=u.full_name, role=m.role, joined_at=m.joined_at,
                          invited_by=m.invited_by) for m, u in rows]

    @staticmethod
    async def _owner_count(db: AsyncSession, workspace_id: UUID) -> int:
        return int((await db.execute(select(func.count()).select_from(WorkspaceMember).where(
            WorkspaceMember.workspace_id == workspace_id, WorkspaceMember.role == MemberRole.owner))).scalar_one())

    @staticmethod
    def _check_can_grant(member: Any, role: MemberRole) -> None:
        if not member.has("admin"):
            raise forbidden("Requires role admin or higher")
        if role == MemberRole.owner and _actor_role(member) != MemberRole.owner:
            raise forbidden("Only an owner can grant the owner role")

    @classmethod
    async def add_member(cls, db: AsyncSession, member: Any, email: str, role: MemberRole, request: Any = None) -> MemberRow:
        cls._check_can_grant(member, role)
        user = (await db.execute(select(User).where(User.email == email))).scalar_one_or_none()
        if not user:
            raise ProblemError(404, "user_not_found", "User not found", "No account with this email; send an invitation instead")
        if await cls.membership(db, member.workspace_id, user.id):
            raise conflict("already_member", "User is already a member of this workspace")
        m = WorkspaceMember(workspace_id=member.workspace_id, user_id=user.id, role=role, invited_by=member.user.id)
        db.add(m)
        await db.flush()
        await audit(db, member, "member.add", "user", user.id, after={"role": role.value, "email": user.email}, request=request)
        return MemberRow(user.id, user.email, user.full_name, role, m.joined_at, m.invited_by)

    @classmethod
    async def change_role(cls, db: AsyncSession, member: Any, user_id: UUID, role: MemberRole, request: Any = None) -> MemberRow:
        cls._check_can_grant(member, role)
        m = await cls.membership(db, member.workspace_id, user_id)
        if not m:
            raise not_found("Member")
        old = m.role
        u = await db.get(User, user_id)
        if u is None:
            raise not_found("Member")
        if old == role:
            return MemberRow(user_id, u.email, u.full_name, role, m.joined_at, m.invited_by)
        if old == MemberRole.owner:
            if _actor_role(member) != MemberRole.owner:
                raise forbidden("Only an owner can change another owner's role")
            if await cls._owner_count(db, member.workspace_id) <= 1:
                raise conflict("last_owner", "A workspace must keep at least one owner")
        if role_rank(old) > role_rank(_actor_role(member)):
            raise forbidden("Cannot change the role of a member with a higher role")
        m.role = role
        await db.flush()
        await audit(db, member, "member.role_change", "user", user_id, before={"role": old.value}, after={"role": role.value},
                    request=request)
        return MemberRow(user_id, u.email, u.full_name, role, m.joined_at, m.invited_by)

    @classmethod
    async def remove_member(cls, db: AsyncSession, member: Any, user_id: UUID, request: Any = None) -> None:
        is_self = user_id == member.user.id
        if not is_self and not member.has("admin"):
            raise forbidden("Requires role admin or higher")
        m = await cls.membership(db, member.workspace_id, user_id)
        if not m:
            raise not_found("Member")
        if m.role == MemberRole.owner:
            if not is_self and _actor_role(member) != MemberRole.owner:
                raise forbidden("An owner cannot be removed by a non-owner")
            if await cls._owner_count(db, member.workspace_id) <= 1:
                raise conflict("last_owner", "The last owner cannot be removed")
        elif not is_self and role_rank(m.role) > role_rank(_actor_role(member)):
            raise forbidden("Cannot remove a member with a higher role")
        await audit(db, member, "member.remove", "user", user_id, before={"role": m.role.value}, request=request)
        await db.delete(m)
        await db.flush()

    # ------------------------------------------------------------ invitations
    @staticmethod
    def invitation_status(inv: Invitation) -> str:
        if inv.accepted_at:
            return "accepted"
        return "expired" if inv.expires_at <= datetime.now(UTC) else "pending"

    @classmethod
    async def create_invitation(cls, db: AsyncSession, member: Any, email: str, role: MemberRole,
                                request: Any = None, *, send_email: bool = True) -> tuple[Invitation, str]:
        """→ (invitation, plaintext token). Only the token hash is stored."""
        cls._check_can_grant(member, role)
        existing_user = (await db.execute(select(User).where(User.email == email))).scalar_one_or_none()
        if existing_user and await cls.membership(db, member.workspace_id, existing_user.id):
            raise conflict("already_member", "User is already a member of this workspace")
        await db.execute(delete(Invitation).where(Invitation.workspace_id == member.workspace_id, Invitation.email == email,
                                                  Invitation.accepted_at.is_(None)))
        token, token_hash = new_opaque_token()
        inv = Invitation(workspace_id=member.workspace_id, email=email, role=role, token_hash=token_hash,
                         expires_at=datetime.now(UTC) + INVITATION_TTL, invited_by=member.user.id)
        db.add(inv)
        await db.flush()
        await audit(db, member, "invitation.create", "invitation", inv.id, after={"email": email, "role": role.value}, request=request)
        if send_email:
            from app.services.notification_service import send_email as _send
            ws = await cls.get(db, member.workspace_id)
            await _send(email, f"You're invited to {ws.name} on Botwok",
                        f"{member.user.full_name} invited you to join '{ws.name}' as {role.value}.\n\n"
                        f"Accept the invitation: {cls.accept_url(token)}\n\nThis link expires in 7 days.")
        return inv, token

    @staticmethod
    def accept_url(token: str) -> str:
        return f"{settings.public_base_url.rstrip('/')}/invite/{token}"

    @staticmethod
    async def list_invitations(db: AsyncSession, workspace_id: UUID, include_accepted: bool = False) -> list[Invitation]:
        q = select(Invitation).where(Invitation.workspace_id == workspace_id)
        if not include_accepted:
            q = q.where(Invitation.accepted_at.is_(None))
        return list((await db.execute(q.order_by(Invitation.created_at.desc()))).scalars())

    @classmethod
    async def revoke_invitation(cls, db: AsyncSession, member: Any, invitation_id: UUID, request: Any = None) -> None:
        if not member.has("admin"):
            raise forbidden("Requires role admin or higher")
        inv = (await db.execute(select(Invitation).where(Invitation.id == invitation_id,
                                                         Invitation.workspace_id == member.workspace_id))).scalar_one_or_none()
        if not inv:
            raise not_found("Invitation")
        await audit(db, member, "invitation.revoke", "invitation", inv.id, before={"email": inv.email, "role": inv.role.value},
                    request=request)
        await db.delete(inv)
        await db.flush()

    @staticmethod
    async def find_invitation(db: AsyncSession, token: str) -> Invitation | None:
        return (await db.execute(select(Invitation).where(Invitation.token_hash == hash_token(token)))).scalar_one_or_none()

    @classmethod
    async def accept_invitation(cls, db: AsyncSession, user: User, token: str, request: Any = None) -> tuple[Workspace, MemberRole]:
        inv = await cls.find_invitation(db, token)
        if not inv:
            raise not_found("Invitation")
        if inv.accepted_at:
            raise conflict("invitation_used", "This invitation has already been accepted")
        if inv.expires_at <= datetime.now(UTC):
            raise ProblemError(410, "invitation_expired", "Invitation expired")
        if inv.email.lower() != user.email.lower():
            raise forbidden("This invitation was sent to a different email address")
        m = await cls.membership(db, inv.workspace_id, user.id)
        if m is None:
            m = WorkspaceMember(workspace_id=inv.workspace_id, user_id=user.id, role=inv.role, invited_by=inv.invited_by)
            db.add(m)
        inv.accepted_at = datetime.now(UTC)
        await db.flush()
        await audit(db, user, "invitation.accept", "invitation", inv.id, after={"role": m.role.value},
                    request=request, workspace_id=inv.workspace_id)
        ws = await cls.get(db, inv.workspace_id)
        return ws, m.role

    # ------------------------------------------------------------ API keys
    @staticmethod
    async def create_api_key(db: AsyncSession, member: Any, name: str, scopes: list[str], expires_at: datetime | None = None,
                             request: Any = None) -> tuple[ApiKey, str]:
        if not member.has("admin"):
            raise forbidden("Requires role admin or higher")
        if expires_at is not None and expires_at.tzinfo is None:
            expires_at = expires_at.replace(tzinfo=UTC)
        if expires_at is not None and expires_at <= datetime.now(UTC):
            raise validation("expires_at must be in the future")
        full, prefix, key_hash = new_api_key()
        key = ApiKey(workspace_id=member.workspace_id, name=name.strip(), key_prefix=prefix, key_hash=key_hash,
                     scopes=validate_scopes(scopes), created_by=member.user.id, expires_at=expires_at)
        db.add(key)
        await db.flush()
        await audit(db, member, "api_key.create", "api_key", key.id, after={"name": key.name, "prefix": prefix, "scopes": key.scopes},
                    request=request)
        return key, full

    @staticmethod
    async def list_api_keys(db: AsyncSession, workspace_id: UUID) -> list[ApiKey]:
        return list((await db.execute(select(ApiKey).where(ApiKey.workspace_id == workspace_id)
                                      .order_by(ApiKey.created_at.desc()))).scalars())

    @staticmethod
    async def revoke_api_key(db: AsyncSession, member: Any, key_id: UUID, request: Any = None) -> ApiKey:
        if not member.has("admin"):
            raise forbidden("Requires role admin or higher")
        key = (await db.execute(select(ApiKey).where(ApiKey.id == key_id, ApiKey.workspace_id == member.workspace_id))).scalar_one_or_none()
        if not key:
            raise not_found("API key")
        if key.revoked_at is None:
            key.revoked_at = datetime.now(UTC)
            await audit(db, member, "api_key.revoke", "api_key", key.id, before={"name": key.name, "prefix": key.key_prefix},
                        request=request)
        return key

    @staticmethod
    async def authenticate_api_key(db: AsyncSession, raw_key: str) -> ApiKey | None:
        """Validate an `X-API-Key` value → active ApiKey (and touch last_used_at), else None."""
        if not parse_api_key(raw_key):
            return None
        key = (await db.execute(select(ApiKey).where(ApiKey.key_hash == hash_token(raw_key.strip())))).scalar_one_or_none()
        now = datetime.now(UTC)
        if not key or key.revoked_at is not None or (key.expires_at is not None and key.expires_at <= now):
            return None
        if key.last_used_at is None or (now - key.last_used_at) > timedelta(minutes=1):
            key.last_used_at = now
        return key

    # ------------------------------------------------------------ budgets
    @staticmethod
    def _period_start(period: str, now: datetime | None = None) -> datetime:
        now = now or datetime.now(UTC)
        day = now.replace(hour=0, minute=0, second=0, microsecond=0)
        return day.replace(day=1) if period == "month" else day

    @classmethod
    async def _usage(cls, db: AsyncSession, workspace_id: UUID, kind: str, period: str) -> float:
        since = cls._period_start(period)
        q = select(func.coalesce(func.sum(UsageLedger.cost_usd if kind.endswith("_cost") else UsageLedger.quantity), 0)).where(
            UsageLedger.workspace_id == workspace_id, UsageLedger.occurred_at >= since)
        if kind.endswith("_cost"):
            q = q.where(UsageLedger.kind.startswith(kind.removesuffix("_cost")))
        else:
            q = q.where(UsageLedger.kind == kind)
        return float((await db.execute(q)).scalar_one() or 0)

    @classmethod
    async def list_budgets(cls, db: AsyncSession, workspace_id: UUID, with_usage: bool = True) -> list[dict[str, Any]]:
        rows = list((await db.execute(select(UsageBudget).where(UsageBudget.workspace_id == workspace_id)
                                      .order_by(UsageBudget.kind, UsageBudget.period))).scalars())
        out = []
        for b in rows:
            used = await cls._usage(db, workspace_id, b.kind, b.period) if with_usage else None
            out.append({"id": b.id, "kind": b.kind, "period": b.period, "limit_value": float(b.limit_value), "hard": b.hard, "used": used})
        return out

    @classmethod
    async def update_budgets(cls, db: AsyncSession, member: Any, items: list[Any], request: Any = None) -> list[dict[str, Any]]:
        """Upsert by (kind, period); ``limit_value=None`` deletes."""
        if not member.has("admin"):
            raise forbidden("Requires role admin or higher")
        before = await cls.list_budgets(db, member.workspace_id, with_usage=False)
        for it in items:
            row = (await db.execute(select(UsageBudget).where(UsageBudget.workspace_id == member.workspace_id,
                                                              UsageBudget.kind == it.kind, UsageBudget.period == it.period))).scalar_one_or_none()
            if it.limit_value is None:
                if row:
                    await db.delete(row)
                continue
            if row:
                row.limit_value = it.limit_value
                row.hard = it.hard
            else:
                db.add(UsageBudget(workspace_id=member.workspace_id, kind=it.kind, period=it.period, limit_value=it.limit_value, hard=it.hard))
        await db.flush()
        after = await cls.list_budgets(db, member.workspace_id, with_usage=False)
        await audit(db, member, "budgets.update", "workspace", member.workspace_id,
                    before={"budgets": [{k: v for k, v in b.items() if k != "id"} for b in before]},
                    after={"budgets": [{k: v for k, v in b.items() if k != "id"} for b in after]}, request=request)
        return await cls.list_budgets(db, member.workspace_id)

    @staticmethod
    async def ensure_default_budgets(db: AsyncSession, workspace_id: UUID) -> int:
        n = 0
        for kind, period, limit in DEFAULT_BUDGETS:
            exists = (await db.execute(select(UsageBudget.id).where(UsageBudget.workspace_id == workspace_id, UsageBudget.kind == kind,
                                                                    UsageBudget.period == period))).scalar_one_or_none()
            if not exists:
                db.add(UsageBudget(workspace_id=workspace_id, kind=kind, period=period, limit_value=limit, hard=True))
                n += 1
        return n

"""Identity module schemas: auth, workspaces, members, invitations, API keys, notifications, audit, settings, budgets."""
from __future__ import annotations

import ipaddress
import re
from datetime import datetime
from typing import Annotated, Any, Literal
from uuid import UUID

from pydantic import AfterValidator, BaseModel, BeforeValidator, ConfigDict, Field

from app.models.enums import MemberRole

_EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$|^[^@\s]+@localhost$")


def normalize_email(value: str) -> str:
    """Lenient email check (accepts special-use domains such as `.local` that local-first installs use)."""
    v = (value or "").strip().lower()
    if len(v) > 254 or not _EMAIL_RE.match(v):
        raise ValueError("value is not a valid email address")
    return v


def _num(v: Any) -> Any:
    return float(v) if v is not None else v


def _ip_str(v: Any) -> Any:
    if v is None or isinstance(v, str):
        return v
    if isinstance(v, ipaddress.IPv4Interface | ipaddress.IPv6Interface):
        return str(v.ip)
    return str(v)


Email = Annotated[str, AfterValidator(normalize_email)]
Password = Annotated[str, Field(min_length=8, max_length=256)]
FloatNum = Annotated[float, BeforeValidator(_num)]

BudgetKind = Literal["ai_tokens", "ai_cost", "media_cost", "search_calls", "platform_reads"]
BudgetPeriod = Literal["day", "month"]


class _Out(BaseModel):
    model_config = ConfigDict(from_attributes=True)


# ---------------------------------------------------------------- auth
class SignupRequest(BaseModel):
    email: Email
    password: Password
    full_name: str | None = Field(default=None, max_length=200)
    workspace_name: str | None = Field(default=None, max_length=120)
    invitation_token: str | None = Field(default=None, max_length=200)


class LoginRequest(BaseModel):
    email: Email
    password: str = Field(min_length=1, max_length=256)
    workspace_id: UUID | None = None


class RefreshRequest(BaseModel):
    """Optional body for non-browser clients; browsers use the `botwok_refresh` cookie."""
    refresh_token: str | None = None
    workspace_id: UUID | None = None


class PasswordResetRequest(BaseModel):
    email: Email


class PasswordResetConfirm(BaseModel):
    token: str = Field(min_length=10, max_length=200)
    new_password: Password


class UserOut(_Out):
    id: UUID
    email: str
    full_name: str
    avatar_asset_id: UUID | None = None
    preferences: dict[str, Any] = Field(default_factory=dict)
    is_active: bool = True
    last_login_at: datetime | None = None
    created_at: datetime | None = None


class WorkspaceOut(_Out):
    id: UUID
    name: str
    slug: str
    plan: str = "local"
    created_by: UUID | None = None
    created_at: datetime | None = None
    role: MemberRole | None = None


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    expires_in: int
    user: UserOut
    workspace: WorkspaceOut | None = None
    role: MemberRole | None = None


class MembershipOut(BaseModel):
    workspace: WorkspaceOut
    role: MemberRole


class MeOut(BaseModel):
    user: UserOut
    memberships: list[MembershipOut]


# ---------------------------------------------------------------- workspaces
class WorkspaceCreate(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    slug: str | None = Field(default=None, max_length=48)


class WorkspaceUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=120)
    slug: str | None = Field(default=None, min_length=2, max_length=48)


class MemberOut(BaseModel):
    user_id: UUID
    email: str
    full_name: str
    role: MemberRole
    joined_at: datetime | None = None
    invited_by: UUID | None = None


class MemberAdd(BaseModel):
    email: Email
    role: MemberRole = MemberRole.editor


class MemberRoleUpdate(BaseModel):
    role: MemberRole


class InvitationCreate(BaseModel):
    email: Email
    role: MemberRole = MemberRole.editor


class InvitationOut(_Out):
    id: UUID
    workspace_id: UUID
    email: str
    role: MemberRole
    expires_at: datetime
    accepted_at: datetime | None = None
    invited_by: UUID
    created_at: datetime | None = None
    status: Literal["pending", "accepted", "expired"] = "pending"
    token: str | None = Field(default=None, description="Shown once, at creation")
    accept_url: str | None = None


class InvitationAcceptOut(BaseModel):
    workspace: WorkspaceOut
    role: MemberRole


# ---------------------------------------------------------------- api keys
class ApiKeyCreate(BaseModel):
    name: str = Field(min_length=1, max_length=100)
    scopes: list[str] = Field(default_factory=list, max_length=50)
    expires_at: datetime | None = None


class ApiKeyOut(_Out):
    id: UUID
    name: str
    key_prefix: str
    scopes: list[str] = Field(default_factory=list)
    created_by: UUID
    last_used_at: datetime | None = None
    expires_at: datetime | None = None
    revoked_at: datetime | None = None
    created_at: datetime | None = None


class ApiKeyCreated(ApiKeyOut):
    secret: str = Field(description="Full API key; shown once and never retrievable again")


# ---------------------------------------------------------------- notifications
class NotificationOut(_Out):
    id: UUID
    workspace_id: UUID
    user_id: UUID | None = None
    kind: str
    title: str
    body: str | None = None
    link: str | None = None
    severity: str = "info"
    payload: dict[str, Any] = Field(default_factory=dict)
    channels: list[str] = Field(default_factory=list)
    delivered: dict[str, Any] = Field(default_factory=dict)
    read_at: datetime | None = None
    created_at: datetime | None = None


class NotificationPage(BaseModel):
    items: list[NotificationOut]
    next_cursor: str | None = None
    unread_count: int = 0


# ---------------------------------------------------------------- audit
class AuditLogOut(_Out):
    id: int
    workspace_id: UUID | None = None
    actor_type: str
    actor_id: str
    action: str
    target_type: str | None = None
    target_id: str | None = None
    before: dict[str, Any] | None = None
    after: dict[str, Any] | None = None
    meta: dict[str, Any] | None = None
    ip: Annotated[str | None, BeforeValidator(_ip_str)] = None
    user_agent: str | None = None
    request_id: str | None = None
    created_at: datetime | None = None


# ---------------------------------------------------------------- workspace settings
class NotificationChannelsUpdate(BaseModel):
    in_app: bool | None = None
    email: bool | None = None
    slack_webhook_url: str | None = Field(default=None, max_length=500, description='"" clears')
    webhook_url: str | None = Field(default=None, max_length=500, description='"" clears')


class ApprovalPolicy(BaseModel):
    require_approval: bool = True
    min_approvals: int = Field(default=1, ge=1, le=5)
    approver_roles: list[MemberRole] = Field(
        default_factory=lambda: [MemberRole.approver, MemberRole.admin, MemberRole.owner])
    auto_publish_after_approval: bool = False


class WorkspaceSettingsUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=120)
    timezone: str | None = Field(default=None, max_length=64)
    notification_channels: NotificationChannelsUpdate | None = None
    approval_policy: ApprovalPolicy | None = None
    retention_days: int | None = Field(default=None, ge=1, le=3650)


class NotificationChannelsOut(BaseModel):
    in_app: bool = True
    email: bool = False
    slack_configured: bool = False
    slack_webhook_hint: str | None = None
    webhook_configured: bool = False
    webhook_url_hint: str | None = None


class WorkspaceSettingsOut(BaseModel):
    workspace_id: UUID
    name: str
    slug: str
    timezone: str = "UTC"
    notification_channels: NotificationChannelsOut
    approval_policy: ApprovalPolicy
    retention_days: int | None = None


# ---------------------------------------------------------------- budgets
class BudgetOut(_Out):
    id: UUID
    kind: str
    period: str
    limit_value: FloatNum
    hard: bool = True
    used: FloatNum | None = None


class BudgetUpdate(BaseModel):
    kind: BudgetKind
    period: BudgetPeriod
    limit_value: float | None = Field(default=None, ge=0, description="null deletes the budget")
    hard: bool = True


class BudgetsUpdate(BaseModel):
    budgets: list[BudgetUpdate] = Field(max_length=20)


# ---------------------------------------------------------------- misc
class ExportAccepted(BaseModel):
    id: UUID
    status: str = "queued"
    status_url: str


# ---------------------------------------------------------------- admin
class HealthCheck(BaseModel):
    ok: bool
    latency_ms: int | None = None
    detail: str | None = None
    info: dict[str, Any] = Field(default_factory=dict)


class HealthOut(BaseModel):
    status: Literal["ok", "degraded", "down"]
    checks: dict[str, HealthCheck]


class EventOut(_Out):
    id: int
    event_id: UUID
    workspace_id: UUID | None = None
    name: str
    payload: dict[str, Any] = Field(default_factory=dict)
    actor: dict[str, Any] | None = None
    occurred_at: datetime
    published_at: datetime | None = None
    attempts: int = 0


class JobOut(BaseModel):
    id: int
    task_name: str
    status: str
    queue_name: str
    attempts: int = 0
    scheduled_at: datetime | None = None


class JobsPage(BaseModel):
    items: list[JobOut]
    available: bool = True
    detail: str | None = None


class CostKindOut(BaseModel):
    kind: str
    quantity: float
    cost_usd: float


class CostsOut(BaseModel):
    period: str
    start: datetime
    end: datetime
    total_cost_usd: float
    by_kind: list[CostKindOut]

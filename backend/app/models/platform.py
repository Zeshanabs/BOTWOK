from __future__ import annotations

from datetime import date, datetime
from typing import Any
from uuid import UUID

from sqlalchemy import BigInteger, Boolean, DateTime, ForeignKey, Integer, LargeBinary, Numeric, Text
from sqlalchemy import text as sa_text
from sqlalchemy.dialects.postgresql import ARRAY, INET, JSONB
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.models._types import ApprovalStatusT, AutomationStatusT, MemberRoleT, PlatformT
from app.models.base import Base, IdMixin, TimestampMixin, WorkspaceMixin
from app.models.enums import ApprovalStatus, AutomationStatus, MemberRole, Platform

J = lambda: mapped_column(JSONB, default=dict, server_default=sa_text("'{}'::jsonb"))  # noqa: E731


class AutomationWorkflow(Base, IdMixin, TimestampMixin, WorkspaceMixin):
    __tablename__ = "automation_workflows"
    brand_id: Mapped[UUID | None] = mapped_column(PG_UUID(as_uuid=True), ForeignKey("brands.id", ondelete="CASCADE"))
    name: Mapped[str] = mapped_column(Text, nullable=False)
    description: Mapped[str | None] = mapped_column(Text)
    status: Mapped[str] = mapped_column(Text, default="draft", server_default="draft")
    version: Mapped[int] = mapped_column(Integer, default=1, server_default="1")
    trigger_summary: Mapped[str | None] = mapped_column(Text)
    autonomous_actions_enabled: Mapped[bool] = mapped_column(Boolean, default=False, server_default=sa_text("false"))
    settings: Mapped[dict[str, Any]] = J()
    last_run_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    next_run_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_by: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), ForeignKey("users.id"), nullable=False)


class WorkflowNode(Base, IdMixin, WorkspaceMixin):
    __tablename__ = "workflow_nodes"
    workflow_id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), ForeignKey("automation_workflows.id", ondelete="CASCADE"), nullable=False)
    key: Mapped[str] = mapped_column(Text, nullable=False)
    type: Mapped[str] = mapped_column(Text, nullable=False)
    label: Mapped[str | None] = mapped_column(Text)
    config: Mapped[dict[str, Any]] = J()
    position: Mapped[dict[str, Any]] = mapped_column(JSONB, default=lambda: {"x": 0, "y": 0}, server_default=sa_text("'{\"x\":0,\"y\":0}'::jsonb"))


class WorkflowEdge(Base, IdMixin, WorkspaceMixin):
    __tablename__ = "workflow_edges"
    workflow_id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), ForeignKey("automation_workflows.id", ondelete="CASCADE"), nullable=False)
    from_node_key: Mapped[str] = mapped_column(Text, nullable=False)
    to_node_key: Mapped[str] = mapped_column(Text, nullable=False)
    branch: Mapped[str | None] = mapped_column(Text)
    condition: Mapped[dict[str, Any] | None] = mapped_column(JSONB)


class AutomationRun(Base, IdMixin, WorkspaceMixin):
    __tablename__ = "automation_runs"
    workflow_id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), ForeignKey("automation_workflows.id", ondelete="CASCADE"), nullable=False)
    workflow_version: Mapped[int] = mapped_column(Integer, nullable=False)
    trigger_type: Mapped[str] = mapped_column(Text, nullable=False)
    trigger_payload: Mapped[dict[str, Any]] = J()
    status: Mapped[AutomationStatus] = mapped_column(AutomationStatusT, default=AutomationStatus.running)
    context: Mapped[dict[str, Any]] = J()
    current_node_key: Mapped[str | None] = mapped_column(Text)
    waiting_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    approval_id: Mapped[UUID | None] = mapped_column(PG_UUID(as_uuid=True))
    cost_usd: Mapped[float] = mapped_column(Numeric(12, 6), default=0, server_default="0")
    error: Mapped[str | None] = mapped_column(Text)
    dry_run: Mapped[bool] = mapped_column(Boolean, default=False, server_default=sa_text("false"))
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=sa_text("now()"))
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class AutomationRunStep(Base, IdMixin, WorkspaceMixin):
    __tablename__ = "automation_run_steps"
    run_id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), ForeignKey("automation_runs.id", ondelete="CASCADE"), nullable=False)
    node_key: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[str] = mapped_column(Text, default="pending", server_default="pending")
    input: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    output: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    ai_run_id: Mapped[UUID | None] = mapped_column(PG_UUID(as_uuid=True), ForeignKey("ai_runs.id", ondelete="SET NULL"))
    attempts: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    error: Mapped[str | None] = mapped_column(Text)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class Approval(Base, IdMixin, WorkspaceMixin):
    __tablename__ = "approvals"
    brand_id: Mapped[UUID | None] = mapped_column(PG_UUID(as_uuid=True), ForeignKey("brands.id", ondelete="CASCADE"))
    kind: Mapped[str] = mapped_column(Text, nullable=False)
    target_type: Mapped[str] = mapped_column(Text, nullable=False)
    target_id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), nullable=False)
    payload: Mapped[dict[str, Any]] = J()
    status: Mapped[ApprovalStatus] = mapped_column(ApprovalStatusT, default=ApprovalStatus.pending)
    requested_by: Mapped[str] = mapped_column(Text, nullable=False)
    required_roles: Mapped[list[MemberRole]] = mapped_column(ARRAY(MemberRoleT), default=lambda: [MemberRole.approver, MemberRole.admin, MemberRole.owner],
                                                           server_default=sa_text("'{approver,admin,owner}'"))
    decided_by: Mapped[UUID | None] = mapped_column(PG_UUID(as_uuid=True), ForeignKey("users.id"))
    decided_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    decision_comment: Mapped[str | None] = mapped_column(Text)
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=sa_text("now()"))


class Notification(Base, IdMixin, WorkspaceMixin):
    __tablename__ = "notifications"
    user_id: Mapped[UUID | None] = mapped_column(PG_UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"))
    kind: Mapped[str] = mapped_column(Text, nullable=False)
    title: Mapped[str] = mapped_column(Text, nullable=False)
    body: Mapped[str | None] = mapped_column(Text)
    link: Mapped[str | None] = mapped_column(Text)
    severity: Mapped[str] = mapped_column(Text, default="info", server_default="info")
    payload: Mapped[dict[str, Any]] = J()
    channels: Mapped[list[str]] = mapped_column(ARRAY(Text), default=lambda: ["in_app"], server_default=sa_text("'{in_app}'"))
    delivered: Mapped[dict[str, Any]] = J()
    read_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=sa_text("now()"))


class AuditLog(Base):
    __tablename__ = "audit_logs"
    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    workspace_id: Mapped[UUID | None] = mapped_column(PG_UUID(as_uuid=True), ForeignKey("workspaces.id", ondelete="SET NULL"))
    actor_type: Mapped[str] = mapped_column(Text, nullable=False)
    actor_id: Mapped[str] = mapped_column(Text, nullable=False)
    action: Mapped[str] = mapped_column(Text, nullable=False)
    target_type: Mapped[str | None] = mapped_column(Text)
    target_id: Mapped[str | None] = mapped_column(Text)
    before: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    after: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    meta: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    ip: Mapped[str | None] = mapped_column(INET)
    user_agent: Mapped[str | None] = mapped_column(Text)
    request_id: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=sa_text("now()"))


class EventOutbox(Base):
    __tablename__ = "events_outbox"
    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    event_id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), server_default=sa_text("gen_random_uuid()"))
    workspace_id: Mapped[UUID | None] = mapped_column(PG_UUID(as_uuid=True))
    name: Mapped[str] = mapped_column(Text, nullable=False)
    payload: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    actor: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    occurred_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=sa_text("now()"))
    published_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    attempts: Mapped[int] = mapped_column(Integer, default=0, server_default="0")


class UsageBudget(Base, IdMixin, WorkspaceMixin):
    __tablename__ = "usage_budgets"
    kind: Mapped[str] = mapped_column(Text, nullable=False)
    period: Mapped[str] = mapped_column(Text, nullable=False)
    limit_value: Mapped[float] = mapped_column(Numeric(14, 4), nullable=False)
    hard: Mapped[bool] = mapped_column(Boolean, default=True, server_default=sa_text("true"))


class UsageLedger(Base):
    __tablename__ = "usage_ledger"
    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    workspace_id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), ForeignKey("workspaces.id", ondelete="CASCADE"), nullable=False)
    kind: Mapped[str] = mapped_column(Text, nullable=False)
    provider: Mapped[str | None] = mapped_column(Text)
    model: Mapped[str | None] = mapped_column(Text)
    platform: Mapped[Platform | None] = mapped_column(PlatformT)
    quantity: Mapped[float] = mapped_column(Numeric(14, 4), nullable=False)
    cost_usd: Mapped[float] = mapped_column(Numeric(12, 6), default=0, server_default="0")
    ref_type: Mapped[str | None] = mapped_column(Text)
    ref_id: Mapped[UUID | None] = mapped_column(PG_UUID(as_uuid=True))
    occurred_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=sa_text("now()"))


class Report(Base, IdMixin, WorkspaceMixin):
    __tablename__ = "reports"
    brand_id: Mapped[UUID | None] = mapped_column(PG_UUID(as_uuid=True), ForeignKey("brands.id", ondelete="CASCADE"))
    kind: Mapped[str] = mapped_column(Text, nullable=False)
    title: Mapped[str] = mapped_column(Text, nullable=False)
    period_start: Mapped[date | None]
    period_end: Mapped[date | None]
    content: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    rendered_object_key: Mapped[str | None] = mapped_column(Text)
    recipients: Mapped[list[Any]] = mapped_column(JSONB, default=list, server_default=sa_text("'[]'::jsonb"))
    ai_run_id: Mapped[UUID | None] = mapped_column(PG_UUID(as_uuid=True))
    automation_run_id: Mapped[UUID | None] = mapped_column(PG_UUID(as_uuid=True))
    created_by: Mapped[UUID | None] = mapped_column(PG_UUID(as_uuid=True), ForeignKey("users.id"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=sa_text("now()"))


class Webhook(Base, IdMixin, WorkspaceMixin):
    __tablename__ = "webhooks"
    direction: Mapped[str] = mapped_column(Text, nullable=False)
    name: Mapped[str] = mapped_column(Text, nullable=False)
    url: Mapped[str | None] = mapped_column(Text)
    secret_ciphertext: Mapped[bytes | None] = mapped_column(LargeBinary)
    secret_nonce: Mapped[bytes | None] = mapped_column(LargeBinary)
    key_version: Mapped[int | None] = mapped_column(Integer)
    events: Mapped[list[str]] = mapped_column(ARRAY(Text), default=list, server_default=sa_text("'{}'"))
    status: Mapped[str] = mapped_column(Text, default="active", server_default="active")
    created_by: Mapped[UUID | None] = mapped_column(PG_UUID(as_uuid=True), ForeignKey("users.id"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=sa_text("now()"))

from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import UUID

from pgvector.sqlalchemy import Vector
from sqlalchemy import BigInteger, Boolean, DateTime, ForeignKey, Integer, LargeBinary, Numeric, Text
from sqlalchemy import text as sa_text
from sqlalchemy.dialects.postgresql import ARRAY, JSONB
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.config import settings
from app.models._types import RunStatusT, TaskStatusT
from app.models.base import Base, IdMixin, TimestampMixin, WorkspaceMixin
from app.models.enums import RunStatus, TaskStatus

J = lambda: mapped_column(JSONB, default=dict, server_default=sa_text("'{}'::jsonb"))  # noqa: E731


class AIAgent(Base):
    __tablename__ = "ai_agents"
    id: Mapped[str] = mapped_column(Text, primary_key=True)
    name: Mapped[str] = mapped_column(Text, nullable=False)
    description: Mapped[str | None] = mapped_column(Text)
    tier: Mapped[str] = mapped_column(Text, nullable=False)
    tools: Mapped[list[str]] = mapped_column(ARRAY(Text), default=list, server_default=sa_text("'{}'"))
    actions: Mapped[dict[str, Any]] = J()
    limits: Mapped[dict[str, Any]] = J()
    enabled: Mapped[bool] = mapped_column(Boolean, default=True, server_default=sa_text("true"))
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=sa_text("now()"), onupdate=sa_text("now()"))


class PromptTemplate(Base, IdMixin):
    __tablename__ = "prompt_templates"
    workspace_id: Mapped[UUID | None] = mapped_column(PG_UUID(as_uuid=True), ForeignKey("workspaces.id", ondelete="CASCADE"))
    agent_id: Mapped[str] = mapped_column(Text, ForeignKey("ai_agents.id"), nullable=False)
    action: Mapped[str | None] = mapped_column(Text)
    version: Mapped[int] = mapped_column(Integer, nullable=False)
    body: Mapped[str] = mapped_column(Text, nullable=False)
    variables: Mapped[list[str]] = mapped_column(ARRAY(Text), default=list, server_default=sa_text("'{}'"))
    model_hints: Mapped[dict[str, Any]] = J()
    is_active: Mapped[bool] = mapped_column(Boolean, default=False, server_default=sa_text("false"))
    created_by: Mapped[UUID | None] = mapped_column(PG_UUID(as_uuid=True), ForeignKey("users.id"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=sa_text("now()"))


class AISettings(Base):
    __tablename__ = "ai_settings"
    workspace_id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), ForeignKey("workspaces.id", ondelete="CASCADE"), primary_key=True)
    routing: Mapped[dict[str, Any]] = J()
    providers: Mapped[dict[str, Any]] = J()
    media: Mapped[dict[str, Any]] = J()
    search: Mapped[dict[str, Any]] = J()
    safety: Mapped[dict[str, Any]] = J()
    budgets: Mapped[dict[str, Any]] = J()
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=sa_text("now()"), onupdate=sa_text("now()"))


class ProviderSecret(Base, IdMixin, WorkspaceMixin):
    __tablename__ = "provider_secrets"
    provider: Mapped[str] = mapped_column(Text, nullable=False)
    ciphertext: Mapped[bytes] = mapped_column(LargeBinary, nullable=False)
    nonce: Mapped[bytes] = mapped_column(LargeBinary, nullable=False)
    key_version: Mapped[int] = mapped_column(Integer, nullable=False)
    last4: Mapped[str | None] = mapped_column(Text)
    status: Mapped[str] = mapped_column(Text, default="active", server_default="active")
    last_verified_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_by: Mapped[UUID | None] = mapped_column(PG_UUID(as_uuid=True), ForeignKey("users.id"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=sa_text("now()"))


class AIConversation(Base, IdMixin, TimestampMixin, WorkspaceMixin):
    __tablename__ = "ai_conversations"
    brand_id: Mapped[UUID | None] = mapped_column(PG_UUID(as_uuid=True), ForeignKey("brands.id", ondelete="SET NULL"))
    user_id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), ForeignKey("users.id"), nullable=False)
    title: Mapped[str | None] = mapped_column(Text)
    summary: Mapped[str | None] = mapped_column(Text)
    summary_embedding: Mapped[list[float] | None] = mapped_column(Vector(settings.embedding_dims))
    embedding_model: Mapped[str | None] = mapped_column(Text)
    context_ref: Mapped[dict[str, Any] | None] = mapped_column(JSONB)


class AIMessage(Base, IdMixin, WorkspaceMixin):
    __tablename__ = "ai_messages"
    conversation_id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), ForeignKey("ai_conversations.id", ondelete="CASCADE"), nullable=False)
    role: Mapped[str] = mapped_column(Text, nullable=False)
    content: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    run_id: Mapped[UUID | None] = mapped_column(PG_UUID(as_uuid=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=sa_text("now()"))


class AIRun(Base, IdMixin, TimestampMixin, WorkspaceMixin):
    __tablename__ = "ai_runs"
    brand_id: Mapped[UUID | None] = mapped_column(PG_UUID(as_uuid=True), ForeignKey("brands.id", ondelete="SET NULL"))
    user_id: Mapped[UUID | None] = mapped_column(PG_UUID(as_uuid=True), ForeignKey("users.id"))
    conversation_id: Mapped[UUID | None] = mapped_column(PG_UUID(as_uuid=True), ForeignKey("ai_conversations.id", ondelete="SET NULL"))
    mode: Mapped[str] = mapped_column(Text, nullable=False)
    input: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    intent: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    plan: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    result: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    status: Mapped[RunStatus] = mapped_column(RunStatusT, default=RunStatus.queued)
    cancel_requested: Mapped[bool] = mapped_column(Boolean, default=False, server_default=sa_text("false"))
    tokens_in: Mapped[int] = mapped_column(BigInteger, default=0, server_default="0")
    tokens_out: Mapped[int] = mapped_column(BigInteger, default=0, server_default="0")
    cached_tokens: Mapped[int] = mapped_column(BigInteger, default=0, server_default="0")
    cost_usd: Mapped[float] = mapped_column(Numeric(12, 6), default=0, server_default="0")
    budget: Mapped[dict[str, Any]] = J()
    error: Mapped[str | None] = mapped_column(Text)
    reasoning_summary: Mapped[str | None] = mapped_column(Text)
    automation_run_id: Mapped[UUID | None] = mapped_column(PG_UUID(as_uuid=True))
    queued_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=sa_text("now()"))
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    tasks: Mapped[list[AITask]] = relationship(lazy="selectin", cascade="all, delete-orphan", order_by="AITask.task_key")


class AITask(Base, IdMixin, WorkspaceMixin):
    __tablename__ = "ai_tasks"
    run_id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), ForeignKey("ai_runs.id", ondelete="CASCADE"), nullable=False)
    task_key: Mapped[str] = mapped_column(Text, nullable=False)
    parent_key: Mapped[str | None] = mapped_column(Text)
    agent_id: Mapped[str] = mapped_column(Text, ForeignKey("ai_agents.id"), nullable=False)
    action: Mapped[str] = mapped_column(Text, nullable=False)
    label: Mapped[str] = mapped_column(Text, nullable=False)
    inputs: Mapped[dict[str, Any]] = J()
    depends_on: Mapped[list[str]] = mapped_column(ARRAY(Text), default=list, server_default=sa_text("'{}'"))
    requires_approval: Mapped[bool] = mapped_column(Boolean, default=False, server_default=sa_text("false"))
    status: Mapped[TaskStatus] = mapped_column(TaskStatusT, default=TaskStatus.pending)
    output: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    error: Mapped[str | None] = mapped_column(Text)
    tokens_in: Mapped[int] = mapped_column(BigInteger, default=0, server_default="0")
    tokens_out: Mapped[int] = mapped_column(BigInteger, default=0, server_default="0")
    cost_usd: Mapped[float] = mapped_column(Numeric(12, 6), default=0, server_default="0")
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    heartbeat_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class AIToolCall(Base, IdMixin, WorkspaceMixin):
    __tablename__ = "ai_tool_calls"
    run_id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), ForeignKey("ai_runs.id", ondelete="CASCADE"), nullable=False)
    task_id: Mapped[UUID | None] = mapped_column(PG_UUID(as_uuid=True), ForeignKey("ai_tasks.id", ondelete="CASCADE"))
    call_index: Mapped[int] = mapped_column(Integer, nullable=False)
    tool_name: Mapped[str] = mapped_column(Text, nullable=False)
    side_effect: Mapped[str] = mapped_column(Text, nullable=False)
    args: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    result: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    result_object_key: Mapped[str | None] = mapped_column(Text)
    status: Mapped[str] = mapped_column(Text, default="running", server_default="running")
    error: Mapped[str | None] = mapped_column(Text)
    duration_ms: Mapped[int | None] = mapped_column(Integer)
    approval_id: Mapped[UUID | None] = mapped_column(PG_UUID(as_uuid=True))
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=sa_text("now()"))
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class AICall(Base, IdMixin, WorkspaceMixin):
    __tablename__ = "ai_calls"
    run_id: Mapped[UUID | None] = mapped_column(PG_UUID(as_uuid=True), ForeignKey("ai_runs.id", ondelete="CASCADE"))
    task_id: Mapped[UUID | None] = mapped_column(PG_UUID(as_uuid=True), ForeignKey("ai_tasks.id", ondelete="CASCADE"))
    agent_id: Mapped[str | None] = mapped_column(Text)
    provider: Mapped[str] = mapped_column(Text, nullable=False)
    model: Mapped[str] = mapped_column(Text, nullable=False)
    prompt_version: Mapped[int | None] = mapped_column(Integer)
    prompt_hash: Mapped[str | None] = mapped_column(Text)
    tokens_in: Mapped[int] = mapped_column(Integer, nullable=False)
    tokens_out: Mapped[int] = mapped_column(Integer, nullable=False)
    cached_tokens: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    cost_usd: Mapped[float] = mapped_column(Numeric(12, 6), nullable=False)
    latency_ms: Mapped[int | None] = mapped_column(Integer)
    finish_reason: Mapped[str | None] = mapped_column(Text)
    temperature: Mapped[float | None] = mapped_column(Numeric(3, 2))
    request_object_key: Mapped[str | None] = mapped_column(Text)
    response_object_key: Mapped[str | None] = mapped_column(Text)
    error: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=sa_text("now()"))


class Memory(Base, IdMixin, WorkspaceMixin):
    __tablename__ = "memories"
    brand_id: Mapped[UUID | None] = mapped_column(PG_UUID(as_uuid=True), ForeignKey("brands.id", ondelete="CASCADE"))
    user_id: Mapped[UUID | None] = mapped_column(PG_UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"))
    kind: Mapped[str] = mapped_column(Text, nullable=False)
    text: Mapped[str] = mapped_column(Text, nullable=False)
    embedding: Mapped[list[float] | None] = mapped_column(Vector(settings.embedding_dims))
    embedding_model: Mapped[str | None] = mapped_column(Text)
    importance: Mapped[float] = mapped_column(Numeric(4, 3), default=0.5, server_default="0.5")
    source_ref: Mapped[dict[str, Any]] = J()
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_used_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    use_count: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=sa_text("now()"))

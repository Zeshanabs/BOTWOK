from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import UUID

from sqlalchemy import Boolean, DateTime, ForeignKey, Text
from sqlalchemy import text as sa_text
from sqlalchemy.dialects.postgresql import ARRAY, CITEXT, INET, JSONB
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models._types import MemberRoleT
from app.models.base import Base, IdMixin, TimestampMixin
from app.models.enums import MemberRole


class User(Base, IdMixin, TimestampMixin):
    __tablename__ = "users"
    email: Mapped[str] = mapped_column(CITEXT, unique=True, nullable=False)
    password_hash: Mapped[str | None] = mapped_column(Text)
    full_name: Mapped[str] = mapped_column(Text, nullable=False)
    avatar_asset_id: Mapped[UUID | None] = mapped_column(PG_UUID(as_uuid=True))
    preferences: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict, server_default=sa_text("'{}'::jsonb"))
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, server_default=sa_text("true"))
    last_login_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    memberships: Mapped[list[WorkspaceMember]] = relationship(back_populates="user", lazy="selectin",
                                                              foreign_keys="WorkspaceMember.user_id")


class Workspace(Base, IdMixin, TimestampMixin):
    __tablename__ = "workspaces"
    name: Mapped[str] = mapped_column(Text, nullable=False)
    slug: Mapped[str] = mapped_column(CITEXT, unique=True, nullable=False)
    settings: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict, server_default=sa_text("'{}'::jsonb"))
    plan: Mapped[str] = mapped_column(Text, default="local", server_default="local")
    created_by: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), ForeignKey("users.id"), nullable=False)
    members: Mapped[list[WorkspaceMember]] = relationship(back_populates="workspace", lazy="selectin")


class WorkspaceMember(Base):
    __tablename__ = "workspace_members"
    workspace_id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), ForeignKey("workspaces.id", ondelete="CASCADE"), primary_key=True)
    user_id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), primary_key=True)
    role: Mapped[MemberRole] = mapped_column(MemberRoleT, nullable=False, default=MemberRole.editor)
    invited_by: Mapped[UUID | None] = mapped_column(PG_UUID(as_uuid=True), ForeignKey("users.id"))
    joined_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=sa_text("now()"))
    user: Mapped[User] = relationship(back_populates="memberships", lazy="joined", foreign_keys=[user_id])
    workspace: Mapped[Workspace] = relationship(back_populates="members", lazy="joined")


class Invitation(Base, IdMixin):
    __tablename__ = "invitations"
    workspace_id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), ForeignKey("workspaces.id", ondelete="CASCADE"), nullable=False)
    email: Mapped[str] = mapped_column(CITEXT, nullable=False)
    role: Mapped[MemberRole] = mapped_column(MemberRoleT, nullable=False)
    token_hash: Mapped[str] = mapped_column(Text, unique=True, nullable=False)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    accepted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    invited_by: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), ForeignKey("users.id"), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=sa_text("now()"))


class RefreshSession(Base, IdMixin):
    __tablename__ = "refresh_sessions"
    user_id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    token_hash: Mapped[str] = mapped_column(Text, unique=True, nullable=False)
    family_id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), nullable=False)
    user_agent: Mapped[str | None] = mapped_column(Text)
    ip: Mapped[str | None] = mapped_column(INET)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=sa_text("now()"))


class ApiKey(Base, IdMixin):
    __tablename__ = "api_keys"
    workspace_id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), ForeignKey("workspaces.id", ondelete="CASCADE"), nullable=False)
    name: Mapped[str] = mapped_column(Text, nullable=False)
    key_prefix: Mapped[str] = mapped_column(Text, nullable=False)
    key_hash: Mapped[str] = mapped_column(Text, unique=True, nullable=False)
    scopes: Mapped[list[str]] = mapped_column(ARRAY(Text), default=list, server_default=sa_text("'{}'"))
    created_by: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), ForeignKey("users.id"), nullable=False)
    last_used_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=sa_text("now()"))

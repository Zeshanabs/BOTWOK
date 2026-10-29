from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import UUID

from sqlalchemy import DateTime, ForeignKey, Integer, LargeBinary, Text
from sqlalchemy import text as sa_text
from sqlalchemy.dialects.postgresql import ARRAY, JSONB
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models._types import AccountStatusT, PlatformT
from app.models.base import Base, IdMixin, TimestampMixin, WorkspaceMixin
from app.models.enums import AccountStatus, Platform


class SocialAccount(Base, IdMixin, TimestampMixin, WorkspaceMixin):
    __tablename__ = "social_accounts"
    brand_id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), ForeignKey("brands.id", ondelete="CASCADE"), nullable=False)
    platform: Mapped[Platform] = mapped_column(PlatformT, nullable=False)
    auth_flavor: Mapped[str] = mapped_column(Text, default="default", server_default="default")
    external_id: Mapped[str] = mapped_column(Text, nullable=False)
    parent_external_id: Mapped[str | None] = mapped_column(Text)
    display_name: Mapped[str] = mapped_column(Text, nullable=False)
    handle: Mapped[str | None] = mapped_column(Text)
    avatar_url: Mapped[str | None] = mapped_column(Text)
    account_type: Mapped[str | None] = mapped_column(Text)
    status: Mapped[AccountStatus] = mapped_column(AccountStatusT, default=AccountStatus.active)
    scopes: Mapped[list[str]] = mapped_column(ARRAY(Text), default=list, server_default=sa_text("'{}'"))
    capabilities: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict, server_default=sa_text("'{}'::jsonb"))
    health: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict, server_default=sa_text("'{}'::jsonb"))
    last_probe_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    connected_by: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), ForeignKey("users.id"), nullable=False)
    disconnected_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    tokens: Mapped[list[OAuthToken]] = relationship(lazy="selectin", cascade="all, delete-orphan")


class OAuthToken(Base, IdMixin, WorkspaceMixin):
    __tablename__ = "oauth_tokens"
    social_account_id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), ForeignKey("social_accounts.id", ondelete="CASCADE"), nullable=False)
    token_kind: Mapped[str] = mapped_column(Text, nullable=False)
    ciphertext: Mapped[bytes] = mapped_column(LargeBinary, nullable=False)
    nonce: Mapped[bytes] = mapped_column(LargeBinary, nullable=False)
    key_version: Mapped[int] = mapped_column(Integer, nullable=False)
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    refresh_expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    issued_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=sa_text("now()"))
    rotated_from: Mapped[UUID | None] = mapped_column(PG_UUID(as_uuid=True), ForeignKey("oauth_tokens.id"))
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    meta: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict, server_default=sa_text("'{}'::jsonb"))


class OAuthState(Base):
    __tablename__ = "oauth_states"
    state: Mapped[str] = mapped_column(Text, primary_key=True)
    workspace_id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), ForeignKey("workspaces.id", ondelete="CASCADE"), nullable=False)
    brand_id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), ForeignKey("brands.id", ondelete="CASCADE"), nullable=False)
    user_id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), ForeignKey("users.id"), nullable=False)
    platform: Mapped[Platform] = mapped_column(PlatformT, nullable=False)
    auth_flavor: Mapped[str] = mapped_column(Text, nullable=False)
    code_verifier: Mapped[str | None] = mapped_column(Text)
    redirect_uri: Mapped[str] = mapped_column(Text, nullable=False)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    consumed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=sa_text("now()"))

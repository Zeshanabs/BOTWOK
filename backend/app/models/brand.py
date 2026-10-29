from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import UUID

from sqlalchemy import DateTime, ForeignKey, Integer, Numeric, Text
from sqlalchemy import text as sa_text
from sqlalchemy.dialects.postgresql import ARRAY, CITEXT, JSONB
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, IdMixin, TimestampMixin, WorkspaceMixin

J = lambda: mapped_column(JSONB, default=dict, server_default=sa_text("'{}'::jsonb"))  # noqa: E731


class Brand(Base, IdMixin, TimestampMixin, WorkspaceMixin):
    __tablename__ = "brands"
    name: Mapped[str] = mapped_column(Text, nullable=False)
    slug: Mapped[str] = mapped_column(CITEXT, nullable=False)
    description: Mapped[str | None] = mapped_column(Text)
    industry: Mapped[str | None] = mapped_column(Text)
    sub_industry: Mapped[str | None] = mapped_column(Text)
    website: Mapped[str | None] = mapped_column(Text)
    geography: Mapped[list[str]] = mapped_column(ARRAY(Text), default=list, server_default=sa_text("'{}'"))
    languages: Mapped[list[str]] = mapped_column(ARRAY(Text), default=lambda: ["en"], server_default=sa_text("'{en}'"))
    timezone: Mapped[str] = mapped_column(Text, default="UTC", server_default="UTC")
    logo_asset_id: Mapped[UUID | None] = mapped_column(PG_UUID(as_uuid=True))
    status: Mapped[str] = mapped_column(Text, default="active", server_default="active")
    created_by: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), ForeignKey("users.id"), nullable=False)
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    settings: Mapped[BrandSettings | None] = relationship(back_populates="brand", uselist=False, lazy="selectin", cascade="all, delete-orphan")
    pillars: Mapped[list[ContentPillar]] = relationship(lazy="selectin", cascade="all, delete-orphan", order_by="ContentPillar.position")


class BrandSettings(Base, WorkspaceMixin):
    __tablename__ = "brand_settings"
    brand_id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), ForeignKey("brands.id", ondelete="CASCADE"), primary_key=True)
    audience: Mapped[dict[str, Any]] = J()
    offering: Mapped[dict[str, Any]] = J()
    voice: Mapped[dict[str, Any]] = J()
    policies: Mapped[dict[str, Any]] = J()
    topics: Mapped[dict[str, Any]] = J()
    visual: Mapped[dict[str, Any]] = J()
    platforms: Mapped[dict[str, Any]] = J()
    goals: Mapped[dict[str, Any]] = J()
    strategy: Mapped[dict[str, Any]] = J()
    context_cache_key: Mapped[str | None] = mapped_column(Text)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=sa_text("now()"), onupdate=sa_text("now()"))
    brand: Mapped[Brand] = relationship(back_populates="settings")


class ContentPillar(Base, IdMixin, TimestampMixin, WorkspaceMixin):
    __tablename__ = "content_pillars"
    brand_id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), ForeignKey("brands.id", ondelete="CASCADE"), nullable=False)
    name: Mapped[str] = mapped_column(Text, nullable=False)
    description: Mapped[str | None] = mapped_column(Text)
    share_target: Mapped[float | None] = mapped_column(Numeric(4, 3))
    color: Mapped[str | None] = mapped_column(Text)
    examples: Mapped[list[str]] = mapped_column(ARRAY(Text), default=list, server_default=sa_text("'{}'"))
    position: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    status: Mapped[str] = mapped_column(Text, default="active", server_default="active")


class BrandAsset(Base, IdMixin, WorkspaceMixin):
    __tablename__ = "brand_assets"
    brand_id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), ForeignKey("brands.id", ondelete="CASCADE"), nullable=False)
    kind: Mapped[str] = mapped_column(Text, nullable=False)
    media_asset_id: Mapped[UUID | None] = mapped_column(PG_UUID(as_uuid=True))
    meta: Mapped[dict[str, Any]] = J()
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=sa_text("now()"))

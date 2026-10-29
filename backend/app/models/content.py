from __future__ import annotations

from datetime import date, datetime
from typing import Any
from uuid import UUID

from pgvector.sqlalchemy import Vector
from sqlalchemy import BigInteger, Boolean, DateTime, ForeignKey, Integer, Numeric, Text
from sqlalchemy import text as sa_text
from sqlalchemy.dialects.postgresql import ARRAY, CITEXT, JSONB
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.config import settings
from app.models._types import ContentFormatT, ContentStatusT, ContentTypeT, PlatformT, RiskLevelT
from app.models.base import Base, IdMixin, TimestampMixin, WorkspaceMixin
from app.models.enums import ContentFormat, ContentStatus, ContentType, Platform, RiskLevel

J = lambda: mapped_column(JSONB, default=dict, server_default=sa_text("'{}'::jsonb"))  # noqa: E731


class Campaign(Base, IdMixin, TimestampMixin, WorkspaceMixin):
    __tablename__ = "campaigns"
    brand_id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), ForeignKey("brands.id", ondelete="CASCADE"), nullable=False)
    name: Mapped[str] = mapped_column(Text, nullable=False)
    description: Mapped[str | None] = mapped_column(Text)
    goal: Mapped[str | None] = mapped_column(Text)
    starts_on: Mapped[date | None]
    ends_on: Mapped[date | None]
    color: Mapped[str | None] = mapped_column(Text)
    status: Mapped[str] = mapped_column(Text, default="planned", server_default="planned")
    created_by: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), ForeignKey("users.id"), nullable=False)


class ContentIdea(Base, IdMixin, TimestampMixin, WorkspaceMixin):
    __tablename__ = "content_ideas"
    brand_id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), ForeignKey("brands.id", ondelete="CASCADE"), nullable=False)
    campaign_id: Mapped[UUID | None] = mapped_column(PG_UUID(as_uuid=True), ForeignKey("campaigns.id", ondelete="SET NULL"))
    pillar_id: Mapped[UUID | None] = mapped_column(PG_UUID(as_uuid=True), ForeignKey("content_pillars.id", ondelete="SET NULL"))
    title: Mapped[str] = mapped_column(Text, nullable=False)
    angle: Mapped[str | None] = mapped_column(Text)
    content_type: Mapped[ContentType | None] = mapped_column(ContentTypeT)
    formats: Mapped[list[ContentFormat]] = mapped_column(ARRAY(ContentFormatT), default=list, server_default=sa_text("'{}'"))
    platforms: Mapped[list[Platform]] = mapped_column(ARRAY(PlatformT), default=list, server_default=sa_text("'{}'"))
    hooks: Mapped[list[Any]] = mapped_column(JSONB, default=list, server_default=sa_text("'[]'::jsonb"))
    evidence: Mapped[dict[str, Any]] = J()
    score: Mapped[float | None] = mapped_column(Numeric(5, 3))
    novelty_score: Mapped[float | None] = mapped_column(Numeric(5, 3))
    status: Mapped[str] = mapped_column(Text, default="new", server_default="new")
    promoted_content_id: Mapped[UUID | None] = mapped_column(PG_UUID(as_uuid=True))
    embedding: Mapped[list[float] | None] = mapped_column(Vector(settings.embedding_dims))
    embedding_model: Mapped[str | None] = mapped_column(Text)
    ai_run_id: Mapped[UUID | None] = mapped_column(PG_UUID(as_uuid=True))
    created_by: Mapped[UUID | None] = mapped_column(PG_UUID(as_uuid=True), ForeignKey("users.id"))


class ContentItem(Base, IdMixin, TimestampMixin, WorkspaceMixin):
    __tablename__ = "content_items"
    brand_id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), ForeignKey("brands.id", ondelete="CASCADE"), nullable=False)
    campaign_id: Mapped[UUID | None] = mapped_column(PG_UUID(as_uuid=True), ForeignKey("campaigns.id", ondelete="SET NULL"))
    idea_id: Mapped[UUID | None] = mapped_column(PG_UUID(as_uuid=True), ForeignKey("content_ideas.id", ondelete="SET NULL"))
    pillar_id: Mapped[UUID | None] = mapped_column(PG_UUID(as_uuid=True), ForeignKey("content_pillars.id", ondelete="SET NULL"))
    title: Mapped[str] = mapped_column(Text, nullable=False)
    content_type: Mapped[ContentType | None] = mapped_column(ContentTypeT)
    master_format: Mapped[ContentFormat] = mapped_column(ContentFormatT, default=ContentFormat.text)
    status: Mapped[ContentStatus] = mapped_column(ContentStatusT, default=ContentStatus.draft)
    body: Mapped[dict[str, Any]] = J()
    language: Mapped[str] = mapped_column(Text, default="en", server_default="en")
    current_version: Mapped[int] = mapped_column(Integer, default=1, server_default="1")
    ai_generated: Mapped[bool] = mapped_column(Boolean, default=False, server_default=sa_text("false"))
    generation_metadata: Mapped[dict[str, Any]] = J()
    risk_level: Mapped[RiskLevel] = mapped_column(RiskLevelT, default=RiskLevel.low)
    approval_required: Mapped[bool] = mapped_column(Boolean, default=True, server_default=sa_text("true"))
    critique: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    factcheck: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    embedding: Mapped[list[float] | None] = mapped_column(Vector(settings.embedding_dims))
    embedding_model: Mapped[str | None] = mapped_column(Text)
    created_by: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), ForeignKey("users.id"), nullable=False)
    assigned_to: Mapped[UUID | None] = mapped_column(PG_UUID(as_uuid=True), ForeignKey("users.id"))
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    variants: Mapped[list[ContentVariant]] = relationship(lazy="selectin", cascade="all, delete-orphan", order_by="ContentVariant.created_at")
    sources: Mapped[list[ContentSource]] = relationship(lazy="selectin", cascade="all, delete-orphan")


class ContentVariant(Base, IdMixin, TimestampMixin, WorkspaceMixin):
    __tablename__ = "content_variants"
    content_item_id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), ForeignKey("content_items.id", ondelete="CASCADE"), nullable=False)
    platform: Mapped[Platform] = mapped_column(PlatformT, nullable=False)
    format: Mapped[ContentFormat] = mapped_column(ContentFormatT, nullable=False)
    social_account_id: Mapped[UUID | None] = mapped_column(PG_UUID(as_uuid=True), ForeignKey("social_accounts.id", ondelete="SET NULL"))
    text: Mapped[str | None] = mapped_column(Text)
    segments: Mapped[list[Any]] = mapped_column(JSONB, default=list, server_default=sa_text("'[]'::jsonb"))
    hashtags: Mapped[list[str]] = mapped_column(ARRAY(Text), default=list, server_default=sa_text("'{}'"))
    media_plan: Mapped[dict[str, Any]] = J()
    platform_metadata: Mapped[dict[str, Any]] = J()
    status: Mapped[ContentStatus] = mapped_column(ContentStatusT, default=ContentStatus.draft)
    validation: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    critique: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    factcheck: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    changes_made: Mapped[list[str]] = mapped_column(ARRAY(Text), default=list, server_default=sa_text("'{}'"))
    current_version: Mapped[int] = mapped_column(Integer, default=1, server_default="1")
    ai_generated: Mapped[bool] = mapped_column(Boolean, default=False, server_default=sa_text("false"))
    generation_metadata: Mapped[dict[str, Any]] = J()
    assets: Mapped[list[ContentAsset]] = relationship(lazy="selectin", cascade="all, delete-orphan", order_by="ContentAsset.position",
                                                      primaryjoin="ContentVariant.id==ContentAsset.variant_id")


class ContentVersion(Base, IdMixin, WorkspaceMixin):
    __tablename__ = "content_versions"
    target_type: Mapped[str] = mapped_column(Text, nullable=False)
    target_id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), nullable=False)
    version: Mapped[int] = mapped_column(Integer, nullable=False)
    snapshot: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    author_type: Mapped[str] = mapped_column(Text, nullable=False)
    author_id: Mapped[str] = mapped_column(Text, nullable=False)
    ai_call_id: Mapped[UUID | None] = mapped_column(PG_UUID(as_uuid=True))
    diff_summary: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=sa_text("now()"))


class ContentSource(Base):
    __tablename__ = "content_sources"
    content_item_id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), ForeignKey("content_items.id", ondelete="CASCADE"), primary_key=True)
    source_id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), ForeignKey("research_sources.id", ondelete="CASCADE"), primary_key=True)
    claim_text: Mapped[str | None] = mapped_column(Text)
    used_for: Mapped[str] = mapped_column(Text, primary_key=True, default="claim", server_default="claim")


class Hashtag(Base, IdMixin, WorkspaceMixin):
    __tablename__ = "hashtags"
    brand_id: Mapped[UUID | None] = mapped_column(PG_UUID(as_uuid=True), ForeignKey("brands.id", ondelete="CASCADE"))
    tag: Mapped[str] = mapped_column(CITEXT, nullable=False)
    platform: Mapped[Platform | None] = mapped_column(PlatformT)
    uses: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    avg_engagement: Mapped[float | None] = mapped_column(Numeric(10, 4))
    banned: Mapped[bool] = mapped_column(Boolean, default=False, server_default=sa_text("false"))
    last_used_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class MediaAsset(Base, IdMixin, TimestampMixin, WorkspaceMixin):
    __tablename__ = "media_assets"
    brand_id: Mapped[UUID | None] = mapped_column(PG_UUID(as_uuid=True), ForeignKey("brands.id", ondelete="SET NULL"))
    kind: Mapped[str] = mapped_column(Text, nullable=False)
    source: Mapped[str] = mapped_column(Text, nullable=False)
    bucket: Mapped[str] = mapped_column(Text, nullable=False)
    object_key: Mapped[str] = mapped_column(Text, nullable=False)
    mime: Mapped[str] = mapped_column(Text, nullable=False)
    bytes: Mapped[int] = mapped_column(BigInteger, nullable=False)
    width: Mapped[int | None] = mapped_column(Integer)
    height: Mapped[int | None] = mapped_column(Integer)
    duration_ms: Mapped[int | None] = mapped_column(Integer)
    fps: Mapped[float | None] = mapped_column(Numeric(6, 3))
    codec: Mapped[str | None] = mapped_column(Text)
    sha256: Mapped[str] = mapped_column(Text, nullable=False)
    alt_text: Mapped[str | None] = mapped_column(Text)
    caption: Mapped[str | None] = mapped_column(Text)
    labels: Mapped[list[str]] = mapped_column(ARRAY(Text), default=list, server_default=sa_text("'{}'"))
    ai_generated: Mapped[bool] = mapped_column(Boolean, default=False, server_default=sa_text("false"))
    provider: Mapped[str | None] = mapped_column(Text)
    model: Mapped[str | None] = mapped_column(Text)
    prompt: Mapped[str | None] = mapped_column(Text)
    seed: Mapped[int | None] = mapped_column(BigInteger)
    generation_params: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    derived_from_id: Mapped[UUID | None] = mapped_column(PG_UUID(as_uuid=True), ForeignKey("media_assets.id", ondelete="SET NULL"))
    transform: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    platform_target: Mapped[str | None] = mapped_column(Text)
    carousel_group_id: Mapped[UUID | None] = mapped_column(PG_UUID(as_uuid=True))
    position: Mapped[int | None] = mapped_column(Integer)
    status: Mapped[str] = mapped_column(Text, default="ready", server_default="ready")
    error: Mapped[str | None] = mapped_column(Text)
    created_by: Mapped[UUID | None] = mapped_column(PG_UUID(as_uuid=True), ForeignKey("users.id"))
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class ContentAsset(Base, IdMixin, WorkspaceMixin):
    __tablename__ = "content_assets"
    content_item_id: Mapped[UUID | None] = mapped_column(PG_UUID(as_uuid=True), ForeignKey("content_items.id", ondelete="CASCADE"))
    variant_id: Mapped[UUID | None] = mapped_column(PG_UUID(as_uuid=True), ForeignKey("content_variants.id", ondelete="CASCADE"))
    media_asset_id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), ForeignKey("media_assets.id", ondelete="RESTRICT"), nullable=False)
    role: Mapped[str] = mapped_column(Text, default="primary", server_default="primary")
    position: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    alt_text: Mapped[str | None] = mapped_column(Text)
    media: Mapped[MediaAsset] = relationship(lazy="joined")

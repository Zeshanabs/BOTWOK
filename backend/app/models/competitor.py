from __future__ import annotations

from datetime import date, datetime
from typing import Any
from uuid import UUID

from pgvector.sqlalchemy import Vector
from sqlalchemy import BigInteger, DateTime, ForeignKey, Integer, Numeric, Text
from sqlalchemy import text as sa_text
from sqlalchemy.dialects.postgresql import ARRAY, JSONB
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.config import settings
from app.models._types import AvailabilityT, ContentFormatT, PlatformT
from app.models.base import Base, IdMixin, TimestampMixin, WorkspaceMixin
from app.models.enums import Availability, ContentFormat, Platform


class Competitor(Base, IdMixin, TimestampMixin, WorkspaceMixin):
    __tablename__ = "competitors"
    brand_id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), ForeignKey("brands.id", ondelete="CASCADE"), nullable=False)
    name: Mapped[str] = mapped_column(Text, nullable=False)
    website: Mapped[str | None] = mapped_column(Text)
    description: Mapped[str | None] = mapped_column(Text)
    industry: Mapped[str | None] = mapped_column(Text)
    tags: Mapped[list[str]] = mapped_column(ARRAY(Text), default=list, server_default=sa_text("'{}'"))
    status: Mapped[str] = mapped_column(Text, default="active", server_default="active")
    monitoring_frequency: Mapped[str] = mapped_column(Text, default="weekly", server_default="weekly")
    last_synced_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_by: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), ForeignKey("users.id"), nullable=False)
    profiles: Mapped[list[CompetitorProfile]] = relationship(lazy="selectin", cascade="all, delete-orphan")


class CompetitorProfile(Base, IdMixin, TimestampMixin, WorkspaceMixin):
    __tablename__ = "competitor_profiles"
    competitor_id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), ForeignKey("competitors.id", ondelete="CASCADE"), nullable=False)
    platform: Mapped[Platform | None] = mapped_column(PlatformT)
    kind: Mapped[str] = mapped_column(Text, default="social", server_default="social")
    handle: Mapped[str | None] = mapped_column(Text)
    url: Mapped[str | None] = mapped_column(Text)
    platform_account_id: Mapped[str | None] = mapped_column(Text)
    availability: Mapped[Availability] = mapped_column(AvailabilityT, default=Availability.not_collected)
    followers_count: Mapped[int | None] = mapped_column(BigInteger)
    media_count: Mapped[int | None] = mapped_column(BigInteger)
    bio: Mapped[str | None] = mapped_column(Text)
    profile_meta: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict, server_default=sa_text("'{}'::jsonb"))
    sync_status: Mapped[str | None] = mapped_column(Text)
    last_synced_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_error: Mapped[str | None] = mapped_column(Text)


class CompetitorPost(Base, IdMixin, WorkspaceMixin):
    __tablename__ = "competitor_posts"
    profile_id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), ForeignKey("competitor_profiles.id", ondelete="CASCADE"), nullable=False)
    platform: Mapped[Platform | None] = mapped_column(PlatformT)
    external_id: Mapped[str | None] = mapped_column(Text)
    url: Mapped[str | None] = mapped_column(Text)
    posted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    format: Mapped[ContentFormat | None] = mapped_column(ContentFormatT)
    text: Mapped[str | None] = mapped_column(Text)
    hashtags: Mapped[list[str]] = mapped_column(ARRAY(Text), default=list, server_default=sa_text("'{}'"))
    mentions: Mapped[list[str]] = mapped_column(ARRAY(Text), default=list, server_default=sa_text("'{}'"))
    media_urls: Mapped[list[str]] = mapped_column(ARRAY(Text), default=list, server_default=sa_text("'{}'"))
    like_count: Mapped[int | None] = mapped_column(BigInteger)
    comment_count: Mapped[int | None] = mapped_column(BigInteger)
    share_count: Mapped[int | None] = mapped_column(BigInteger)
    view_count: Mapped[int | None] = mapped_column(BigInteger)
    availability: Mapped[Availability] = mapped_column(AvailabilityT, nullable=False)
    content_hash: Mapped[str] = mapped_column(Text, nullable=False)
    analysis: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict, server_default=sa_text("'{}'::jsonb"))
    embedding: Mapped[list[float] | None] = mapped_column(Vector(settings.embedding_dims))
    embedding_model: Mapped[str | None] = mapped_column(Text)
    retention_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    retrieved_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=sa_text("now()"))


class CompetitorSnapshot(Base, IdMixin, WorkspaceMixin):
    __tablename__ = "competitor_snapshots"
    profile_id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), ForeignKey("competitor_profiles.id", ondelete="CASCADE"), nullable=False)
    captured_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=sa_text("now()"))
    followers_count: Mapped[int | None] = mapped_column(BigInteger)
    posts_last_7d: Mapped[int | None] = mapped_column(Integer)
    posts_last_30d: Mapped[int | None] = mapped_column(Integer)
    avg_engagement: Mapped[float | None] = mapped_column(Numeric(10, 4))
    format_mix: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    top_hashtags: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    posting_hours: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    raw: Mapped[dict[str, Any] | None] = mapped_column(JSONB)


class CompetitorReport(Base, IdMixin, WorkspaceMixin):
    __tablename__ = "competitor_reports"
    brand_id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), ForeignKey("brands.id", ondelete="CASCADE"), nullable=False)
    competitor_ids: Mapped[list[UUID]] = mapped_column(ARRAY(PG_UUID(as_uuid=True)), nullable=False)
    kind: Mapped[str] = mapped_column(Text, nullable=False)
    period_start: Mapped[date | None]
    period_end: Mapped[date | None]
    content: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    rendered_object_key: Mapped[str | None] = mapped_column(Text)
    ai_run_id: Mapped[UUID | None] = mapped_column(PG_UUID(as_uuid=True))
    created_by: Mapped[UUID | None] = mapped_column(PG_UUID(as_uuid=True), ForeignKey("users.id"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=sa_text("now()"))

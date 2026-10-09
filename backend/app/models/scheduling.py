from __future__ import annotations

from datetime import date, datetime
from typing import Any
from uuid import UUID

from sqlalchemy import BigInteger, Boolean, DateTime, ForeignKey, Integer, Numeric, Text
from sqlalchemy import text as sa_text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models._types import PlatformT, ScheduleStatusT
from app.models.base import Base, IdMixin, TimestampMixin, WorkspaceMixin
from app.models.enums import Platform, ScheduleStatus


class RecurringSchedule(Base, IdMixin, TimestampMixin, WorkspaceMixin):
    __tablename__ = "recurring_schedules"
    brand_id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), ForeignKey("brands.id", ondelete="CASCADE"), nullable=False)
    name: Mapped[str] = mapped_column(Text, nullable=False)
    rrule: Mapped[str] = mapped_column(Text, nullable=False)
    timezone: Mapped[str] = mapped_column(Text, nullable=False)
    kind: Mapped[str] = mapped_column(Text, nullable=False)
    payload: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict, server_default=sa_text("'{}'::jsonb"))
    status: Mapped[str] = mapped_column(Text, default="active", server_default="active")
    next_run_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_materialized_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_by: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), ForeignKey("users.id"), nullable=False)


class ScheduledPost(Base, IdMixin, TimestampMixin, WorkspaceMixin):
    __tablename__ = "scheduled_posts"
    brand_id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), ForeignKey("brands.id", ondelete="CASCADE"), nullable=False)
    content_variant_id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), ForeignKey("content_variants.id", ondelete="CASCADE"), nullable=False)
    social_account_id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), ForeignKey("social_accounts.id", ondelete="RESTRICT"), nullable=False)
    scheduled_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    timezone: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[ScheduleStatus] = mapped_column(ScheduleStatusT, default=ScheduleStatus.scheduled)
    priority: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    queued_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    publishing_started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    published_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    attempt_count: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    max_attempts: Mapped[int] = mapped_column(Integer, default=5, server_default="5")
    next_attempt_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_error: Mapped[str | None] = mapped_column(Text)
    idempotency_root: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), server_default=sa_text("gen_random_uuid()"))
    recurring_schedule_id: Mapped[UUID | None] = mapped_column(PG_UUID(as_uuid=True), ForeignKey("recurring_schedules.id", ondelete="SET NULL"))
    approval_id: Mapped[UUID | None] = mapped_column(PG_UUID(as_uuid=True))
    native_schedule: Mapped[bool] = mapped_column(Boolean, default=False, server_default=sa_text("false"))
    created_by: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), ForeignKey("users.id"), nullable=False)
    attempts: Mapped[list[PublishAttempt]] = relationship(lazy="selectin", cascade="all, delete-orphan", order_by="PublishAttempt.attempt_no")


class PublishAttempt(Base, IdMixin, WorkspaceMixin):
    __tablename__ = "publish_attempts"
    scheduled_post_id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), ForeignKey("scheduled_posts.id", ondelete="CASCADE"), nullable=False)
    attempt_no: Mapped[int] = mapped_column(Integer, nullable=False)
    idempotency_key: Mapped[str] = mapped_column(Text, unique=True, nullable=False)
    status: Mapped[str] = mapped_column(Text, default="running", server_default="running")
    state: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict, server_default=sa_text("'{}'::jsonb"))
    request_fingerprint: Mapped[str] = mapped_column(Text, nullable=False)
    error_category: Mapped[str | None] = mapped_column(Text)
    error_code: Mapped[str | None] = mapped_column(Text)
    error_message: Mapped[str | None] = mapped_column(Text)
    platform_response: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    worker_id: Mapped[str | None] = mapped_column(Text)
    heartbeat_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=sa_text("now()"))
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class PublishedPost(Base, IdMixin, WorkspaceMixin):
    __tablename__ = "published_posts"
    brand_id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), ForeignKey("brands.id", ondelete="CASCADE"), nullable=False)
    scheduled_post_id: Mapped[UUID | None] = mapped_column(PG_UUID(as_uuid=True), ForeignKey("scheduled_posts.id", ondelete="SET NULL"))
    content_variant_id: Mapped[UUID | None] = mapped_column(PG_UUID(as_uuid=True), ForeignKey("content_variants.id", ondelete="SET NULL"))
    social_account_id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), ForeignKey("social_accounts.id", ondelete="RESTRICT"), nullable=False)
    platform: Mapped[Platform] = mapped_column(PlatformT, nullable=False)
    external_id: Mapped[str] = mapped_column(Text, nullable=False)
    external_url: Mapped[str | None] = mapped_column(Text)
    segments: Mapped[list[Any]] = mapped_column(JSONB, default=list, server_default=sa_text("'[]'::jsonb"))
    published_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    imported: Mapped[bool] = mapped_column(Boolean, default=False, server_default=sa_text("false"))
    raw: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=sa_text("now()"))


class PostMetric(Base, IdMixin, WorkspaceMixin):
    __tablename__ = "post_metrics"
    published_post_id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), ForeignKey("published_posts.id", ondelete="CASCADE"), nullable=False)
    platform: Mapped[Platform] = mapped_column(PlatformT, nullable=False)
    captured_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    window: Mapped[str] = mapped_column("metric_window", Text, default="lifetime", server_default="lifetime")
    impressions: Mapped[int | None] = mapped_column(BigInteger)
    reach: Mapped[int | None] = mapped_column(BigInteger)
    views: Mapped[int | None] = mapped_column(BigInteger)
    engaged_views: Mapped[int | None] = mapped_column(BigInteger)
    likes: Mapped[int | None] = mapped_column(BigInteger)
    comments: Mapped[int | None] = mapped_column(BigInteger)
    shares: Mapped[int | None] = mapped_column(BigInteger)
    saves: Mapped[int | None] = mapped_column(BigInteger)
    clicks: Mapped[int | None] = mapped_column(BigInteger)
    link_clicks: Mapped[int | None] = mapped_column(BigInteger)
    profile_clicks: Mapped[int | None] = mapped_column(BigInteger)
    watch_time_s: Mapped[int | None] = mapped_column(BigInteger)
    avg_watch_time_s: Mapped[float | None] = mapped_column(Numeric(10, 2))
    completion_rate: Mapped[float | None] = mapped_column(Numeric(6, 4))
    follows_from_post: Mapped[int | None] = mapped_column(BigInteger)
    reposts: Mapped[int | None] = mapped_column(BigInteger)
    replies: Mapped[int | None] = mapped_column(BigInteger)
    quotes: Mapped[int | None] = mapped_column(BigInteger)
    dislikes: Mapped[int | None] = mapped_column(BigInteger)
    engagement_rate: Mapped[float | None] = mapped_column(Numeric(8, 5))
    engagement_rate_basis: Mapped[str | None] = mapped_column(Text)
    raw: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    availability: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict, server_default=sa_text("'{}'::jsonb"))


class AccountMetric(Base, IdMixin, WorkspaceMixin):
    __tablename__ = "account_metrics"
    social_account_id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), ForeignKey("social_accounts.id", ondelete="CASCADE"), nullable=False)
    date: Mapped[date] = mapped_column(nullable=False)
    followers: Mapped[int | None] = mapped_column(BigInteger)
    followers_delta: Mapped[int | None] = mapped_column(BigInteger)
    following: Mapped[int | None] = mapped_column(BigInteger)
    impressions: Mapped[int | None] = mapped_column(BigInteger)
    reach: Mapped[int | None] = mapped_column(BigInteger)
    views: Mapped[int | None] = mapped_column(BigInteger)
    profile_views: Mapped[int | None] = mapped_column(BigInteger)
    website_clicks: Mapped[int | None] = mapped_column(BigInteger)
    posts_count: Mapped[int | None] = mapped_column(Integer)
    engagement_total: Mapped[int | None] = mapped_column(BigInteger)
    raw: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    availability: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict, server_default=sa_text("'{}'::jsonb"))


class AnalyticsSnapshot(Base, IdMixin, WorkspaceMixin):
    __tablename__ = "analytics_snapshots"
    brand_id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), ForeignKey("brands.id", ondelete="CASCADE"), nullable=False)
    scope: Mapped[str] = mapped_column(Text, nullable=False)
    scope_id: Mapped[str] = mapped_column(Text, nullable=False)
    period: Mapped[str] = mapped_column(Text, nullable=False)
    period_start: Mapped[date] = mapped_column(nullable=False)
    metrics: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    computed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=sa_text("now()"))


class Insight(Base, IdMixin, WorkspaceMixin):
    __tablename__ = "insights"
    brand_id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), ForeignKey("brands.id", ondelete="CASCADE"), nullable=False)
    period_start: Mapped[date] = mapped_column(nullable=False)
    period_end: Mapped[date] = mapped_column(nullable=False)
    statement: Mapped[str] = mapped_column(Text, nullable=False)
    kind: Mapped[str] = mapped_column(Text, nullable=False)
    metric: Mapped[str | None] = mapped_column(Text)
    effect_size: Mapped[float | None] = mapped_column(Numeric(10, 4))
    n: Mapped[int | None] = mapped_column(Integer)
    confidence: Mapped[str] = mapped_column(Text, nullable=False)
    evidence: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict, server_default=sa_text("'{}'::jsonb"))
    ai_run_id: Mapped[UUID | None] = mapped_column(PG_UUID(as_uuid=True))
    status: Mapped[str] = mapped_column(Text, default="new", server_default="new")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=sa_text("now()"))


class Recommendation(Base, IdMixin, WorkspaceMixin):
    __tablename__ = "recommendations"
    brand_id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), ForeignKey("brands.id", ondelete="CASCADE"), nullable=False)
    insight_id: Mapped[UUID | None] = mapped_column(PG_UUID(as_uuid=True), ForeignKey("insights.id", ondelete="SET NULL"))
    action: Mapped[str] = mapped_column(Text, nullable=False)
    rationale: Mapped[str | None] = mapped_column(Text)
    expected_impact: Mapped[str | None] = mapped_column(Text)
    priority: Mapped[str] = mapped_column(Text, default="p2", server_default="p2")
    target: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict, server_default=sa_text("'{}'::jsonb"))
    status: Mapped[str] = mapped_column(Text, default="proposed", server_default="proposed")
    applied_to: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    decided_by: Mapped[UUID | None] = mapped_column(PG_UUID(as_uuid=True), ForeignKey("users.id"))
    decided_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=sa_text("now()"))

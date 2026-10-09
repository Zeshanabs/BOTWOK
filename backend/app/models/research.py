from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import UUID

from pgvector.sqlalchemy import Vector
from sqlalchemy import BigInteger, Boolean, DateTime, ForeignKey, Integer, Numeric, Text
from sqlalchemy import text as sa_text
from sqlalchemy.dialects.postgresql import ARRAY, CITEXT, JSONB
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.config import settings
from app.models._types import PlatformT
from app.models.base import Base, IdMixin, WorkspaceMixin
from app.models.enums import Platform


class ResearchRun(Base, IdMixin, WorkspaceMixin):
    __tablename__ = "research_runs"
    brand_id: Mapped[UUID | None] = mapped_column(PG_UUID(as_uuid=True), ForeignKey("brands.id", ondelete="SET NULL"))
    competitor_id: Mapped[UUID | None] = mapped_column(PG_UUID(as_uuid=True), ForeignKey("competitors.id", ondelete="SET NULL"))
    query: Mapped[str] = mapped_column(Text, nullable=False)
    scope: Mapped[list[str]] = mapped_column(ARRAY(Text), default=lambda: ["web"], server_default=sa_text("'{web}'"))
    depth: Mapped[str] = mapped_column(Text, default="standard", server_default="standard")
    params: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict, server_default=sa_text("'{}'::jsonb"))
    status: Mapped[str] = mapped_column(Text, default="queued", server_default="queued")
    ai_run_id: Mapped[UUID | None] = mapped_column(PG_UUID(as_uuid=True))
    result: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    source_count: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    cost_usd: Mapped[float] = mapped_column(Numeric(12, 6), default=0, server_default="0")
    error: Mapped[str | None] = mapped_column(Text)
    created_by: Mapped[UUID | None] = mapped_column(PG_UUID(as_uuid=True), ForeignKey("users.id"))
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=sa_text("now()"))
    run_sources: Mapped[list[ResearchRunSource]] = relationship(lazy="selectin", cascade="all, delete-orphan", order_by="ResearchRunSource.rank")


class ResearchSource(Base, IdMixin, WorkspaceMixin):
    __tablename__ = "research_sources"
    competitor_id: Mapped[UUID | None] = mapped_column(PG_UUID(as_uuid=True), ForeignKey("competitors.id", ondelete="SET NULL"))
    canonical_url: Mapped[str] = mapped_column(Text, nullable=False)
    final_url: Mapped[str | None] = mapped_column(Text)
    domain: Mapped[str] = mapped_column(Text, nullable=False)
    title: Mapped[str | None] = mapped_column(Text)
    author: Mapped[str | None] = mapped_column(Text)
    source_kind: Mapped[str] = mapped_column(Text, default="web", server_default="web")
    platform: Mapped[Platform | None] = mapped_column(PlatformT)
    published_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    retrieved_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=sa_text("now()"))
    language: Mapped[str | None] = mapped_column(Text)
    summary: Mapped[str | None] = mapped_column(Text)
    keywords: Mapped[list[str]] = mapped_column(ARRAY(Text), default=list, server_default=sa_text("'{}'"))
    topics: Mapped[list[str]] = mapped_column(ARRAY(Text), default=list, server_default=sa_text("'{}'"))
    entities: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict, server_default=sa_text("'{}'::jsonb"))
    credibility_score: Mapped[float | None] = mapped_column(Numeric(4, 3))
    credibility_components: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    citation: Mapped[str | None] = mapped_column(Text)
    content_hash: Mapped[str | None] = mapped_column(Text)
    simhash: Mapped[int | None] = mapped_column(BigInteger)
    content_object_key: Mapped[str | None] = mapped_column(Text)
    word_count: Mapped[int | None] = mapped_column(Integer)
    trust: Mapped[str] = mapped_column(Text, default="untrusted", server_default="untrusted")
    injection_flag: Mapped[bool] = mapped_column(Boolean, default=False, server_default=sa_text("false"))
    fetch_status: Mapped[str] = mapped_column(Text, default="ok", server_default="ok")
    error: Mapped[str | None] = mapped_column(Text)
    duplicates_of: Mapped[UUID | None] = mapped_column(PG_UUID(as_uuid=True), ForeignKey("research_sources.id"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=sa_text("now()"))


class ResearchRunSource(Base):
    __tablename__ = "research_run_sources"
    run_id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), ForeignKey("research_runs.id", ondelete="CASCADE"), primary_key=True)
    source_id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), ForeignKey("research_sources.id", ondelete="CASCADE"), primary_key=True)
    rank: Mapped[int] = mapped_column(Integer, nullable=False)
    relevance_score: Mapped[float] = mapped_column(Numeric(4, 3), nullable=False)
    query_variant: Mapped[str | None] = mapped_column(Text)
    source: Mapped[ResearchSource] = relationship(lazy="joined")


class ResearchDocument(Base, IdMixin, WorkspaceMixin):
    __tablename__ = "research_documents"
    source_id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), ForeignKey("research_sources.id", ondelete="CASCADE"), unique=True, nullable=False)
    text_object_key: Mapped[str] = mapped_column(Text, nullable=False)
    structure: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict, server_default=sa_text("'{}'::jsonb"))
    extractor: Mapped[str | None] = mapped_column(Text)
    extracted_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=sa_text("now()"))


class ResearchChunk(Base, IdMixin, WorkspaceMixin):
    __tablename__ = "research_chunks"
    source_id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), ForeignKey("research_sources.id", ondelete="CASCADE"), nullable=False)
    chunk_index: Mapped[int] = mapped_column(Integer, nullable=False)
    section: Mapped[str | None] = mapped_column(Text)
    text: Mapped[str] = mapped_column(Text, nullable=False)
    token_count: Mapped[int | None] = mapped_column(Integer)
    embedding: Mapped[list[float] | None] = mapped_column(Vector(settings.embedding_dims))
    embedding_model: Mapped[str | None] = mapped_column(Text)


class RssFeed(Base, IdMixin, WorkspaceMixin):
    __tablename__ = "rss_feeds"
    brand_id: Mapped[UUID | None] = mapped_column(PG_UUID(as_uuid=True), ForeignKey("brands.id", ondelete="CASCADE"))
    competitor_id: Mapped[UUID | None] = mapped_column(PG_UUID(as_uuid=True), ForeignKey("competitors.id", ondelete="CASCADE"))
    url: Mapped[str] = mapped_column(Text, nullable=False)
    title: Mapped[str | None] = mapped_column(Text)
    status: Mapped[str] = mapped_column(Text, default="active", server_default="active")
    last_polled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_etag: Mapped[str | None] = mapped_column(Text)
    last_error: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=sa_text("now()"))


class Keyword(Base, IdMixin, WorkspaceMixin):
    __tablename__ = "keywords"
    brand_id: Mapped[UUID | None] = mapped_column(PG_UUID(as_uuid=True), ForeignKey("brands.id", ondelete="CASCADE"))
    term: Mapped[str] = mapped_column(CITEXT, nullable=False)
    source: Mapped[str] = mapped_column(Text, default="user", server_default="user")
    volume_hint: Mapped[int | None] = mapped_column(Integer)
    related: Mapped[list[str]] = mapped_column(ARRAY(Text), default=list, server_default=sa_text("'{}'"))
    frequency: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict, server_default=sa_text("'{}'::jsonb"))
    first_seen: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=sa_text("now()"))
    last_seen: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=sa_text("now()"))


class Trend(Base, IdMixin, WorkspaceMixin):
    __tablename__ = "trends"
    brand_id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), ForeignKey("brands.id", ondelete="CASCADE"), nullable=False)
    label: Mapped[str] = mapped_column(Text, nullable=False)
    summary: Mapped[str | None] = mapped_column(Text)
    score: Mapped[float] = mapped_column(Numeric(6, 3), nullable=False)
    velocity: Mapped[float | None] = mapped_column(Numeric(8, 3))
    status: Mapped[str] = mapped_column(Text, default="active", server_default="active")
    platforms: Mapped[list[Platform]] = mapped_column(ARRAY(PlatformT), default=list, server_default=sa_text("'{}'"))
    keywords: Mapped[list[str]] = mapped_column(ARRAY(Text), default=list, server_default=sa_text("'{}'"))
    first_seen: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    last_seen: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    example_source_ids: Mapped[list[UUID]] = mapped_column(ARRAY(PG_UUID(as_uuid=True)), default=list, server_default=sa_text("'{}'"))
    ai_run_id: Mapped[UUID | None] = mapped_column(PG_UUID(as_uuid=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=sa_text("now()"))
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=sa_text("now()"), onupdate=sa_text("now()"))


class TrendSignal(Base, IdMixin, WorkspaceMixin):
    __tablename__ = "trend_signals"
    trend_id: Mapped[UUID | None] = mapped_column(PG_UUID(as_uuid=True), ForeignKey("trends.id", ondelete="CASCADE"))
    kind: Mapped[str] = mapped_column(Text, nullable=False)
    term: Mapped[str] = mapped_column(Text, nullable=False)
    platform: Mapped[Platform | None] = mapped_column(PlatformT)
    observed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    value: Mapped[float] = mapped_column(Numeric(14, 3), nullable=False)
    source_id: Mapped[UUID | None] = mapped_column(PG_UUID(as_uuid=True), ForeignKey("research_sources.id", ondelete="SET NULL"))
    meta: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict, server_default=sa_text("'{}'::jsonb"))

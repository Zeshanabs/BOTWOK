"""Competitor API schemas (doc 17 §17.2 Competitors, doc 08)."""
from __future__ import annotations

from datetime import datetime
from typing import Any, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

ProfilePlatform = Literal["website", "blog", "rss", "other", "facebook", "instagram", "threads", "linkedin", "x", "tiktok",
                          "youtube", "pinterest", "gbp"]
MonitoringFrequency = Literal["none", "daily", "weekly"]


class ProfileIn(BaseModel):
    platform: ProfilePlatform
    handle: str | None = Field(default=None, max_length=200)
    url: str | None = Field(default=None, max_length=2000)

    @field_validator("handle")
    @classmethod
    def _handle(cls, v: str | None) -> str | None:
        if v is None:
            return None
        v = v.strip().lstrip("@")
        return v or None

    @model_validator(mode="after")
    def _needs_identity(self) -> ProfileIn:
        if self.platform in ("website", "blog", "rss", "other"):
            if not self.url:
                raise ValueError(f"{self.platform} profiles need a url")
        elif not (self.handle or self.url):
            raise ValueError("social profiles need a handle or url")
        return self


class CompetitorCreate(BaseModel):
    brand_id: UUID
    name: str = Field(min_length=1, max_length=200)
    website: str | None = Field(default=None, max_length=2000)
    description: str | None = Field(default=None, max_length=4000)
    industry: str | None = Field(default=None, max_length=200)
    tags: list[str] = Field(default_factory=list, max_length=30)
    monitoring_frequency: MonitoringFrequency = "weekly"
    profiles: list[ProfileIn] = Field(default_factory=list, max_length=20)
    sync_now: bool = True


class CompetitorUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=200)
    website: str | None = Field(default=None, max_length=2000)
    description: str | None = Field(default=None, max_length=4000)
    industry: str | None = Field(default=None, max_length=200)
    tags: list[str] | None = Field(default=None, max_length=30)
    status: Literal["active", "paused"] | None = None
    monitoring_frequency: MonitoringFrequency | None = None
    add_profiles: list[ProfileIn] = Field(default_factory=list, max_length=20)
    remove_profile_ids: list[UUID] = Field(default_factory=list, max_length=20)


class ProfileOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: UUID
    platform: str | None = None
    kind: str
    handle: str | None = None
    url: str | None = None
    availability: str
    sync_status: str | None = None
    followers_count: int | None = None
    media_count: int | None = None
    bio: str | None = None
    last_synced_at: datetime | None = None
    last_error: str | None = None
    profile_meta: dict[str, Any] = Field(default_factory=dict)

    @field_validator("platform", "availability", mode="before")
    @classmethod
    def _enum(cls, v: Any) -> Any:
        return getattr(v, "value", v)


class CompetitorOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: UUID
    brand_id: UUID
    name: str
    website: str | None = None
    description: str | None = None
    industry: str | None = None
    tags: list[str] = Field(default_factory=list)
    status: str
    monitoring_frequency: str
    last_synced_at: datetime | None = None
    created_at: datetime | None = None
    updated_at: datetime | None = None
    profiles: list[ProfileOut] = Field(default_factory=list)


class PostOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: UUID
    profile_id: UUID
    platform: str | None = None
    external_id: str | None = None
    url: str | None = None
    posted_at: datetime | None = None
    format: str | None = None
    text: str | None = None
    hashtags: list[str] = Field(default_factory=list)
    mentions: list[str] = Field(default_factory=list)
    like_count: int | None = None
    comment_count: int | None = None
    share_count: int | None = None
    view_count: int | None = None
    availability: str
    analysis: dict[str, Any] = Field(default_factory=dict)
    retention_until: datetime | None = None
    retrieved_at: datetime | None = None

    @field_validator("platform", "format", "availability", mode="before")
    @classmethod
    def _enum(cls, v: Any) -> Any:
        return getattr(v, "value", v)


class SnapshotOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: UUID
    profile_id: UUID
    captured_at: datetime
    followers_count: int | None = None
    posts_last_7d: int | None = None
    posts_last_30d: int | None = None
    avg_engagement: float | None = None
    format_mix: dict[str, Any] | None = None
    top_hashtags: dict[str, Any] | None = None
    posting_hours: dict[str, Any] | None = None
    raw: dict[str, Any] | None = None


class SyncAccepted(BaseModel):
    competitor_id: UUID
    job_ids: list[int | None] = Field(default_factory=list)
    profiles: list[UUID] = Field(default_factory=list)
    status: str = "queued"


class ReportCreate(BaseModel):
    kind: Literal["single", "comparison", "monitoring", "opportunities"] = "single"
    competitor_ids: list[UUID] = Field(default_factory=list, max_length=10)
    period_days: int = Field(default=30, ge=1, le=365)
    instructions: str | None = Field(default=None, max_length=2000)


class ReportOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: UUID
    brand_id: UUID
    competitor_ids: list[UUID]
    kind: str
    content: dict[str, Any]
    ai_run_id: UUID | None = None
    created_at: datetime | None = None


class CompareOut(BaseModel):
    period_days: int
    columns: list[dict[str, Any]]
    rows: list[dict[str, Any]]
    notes: list[str] = Field(default_factory=list)

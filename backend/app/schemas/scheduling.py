"""Scheduling & calendar API schemas (doc 17 "Scheduling & publishing", §17.3)."""
from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


class ScheduleCreate(BaseModel):
    content_variant_id: UUID
    social_account_id: UUID
    scheduled_at: datetime
    timezone: str = "UTC"
    priority: int = Field(default=0, ge=-10, le=10)
    force: bool = False   # override the 24 h duplicate-fingerprint check


class ScheduleUpdate(BaseModel):
    scheduled_at: datetime | None = None
    timezone: str | None = None
    priority: int | None = Field(default=None, ge=-10, le=10)


class ResumeIn(BaseModel):
    scheduled_at: datetime | None = None


class AttemptOut(BaseModel):
    id: str
    attempt_no: int
    status: str
    error_category: str | None = None
    error_code: str | None = None
    error_message: str | None = None
    started_at: str | None = None
    finished_at: str | None = None
    segments_done: int = 0


class SocialAccountBrief(BaseModel):
    id: str
    platform: str
    display_name: str
    handle: str | None = None


class CreatorBrief(BaseModel):
    id: str
    name: str | None = None


class ScheduledPostOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: str
    workspace_id: str
    brand_id: str
    content_variant_id: str
    social_account_id: str
    social_account: SocialAccountBrief | None = None
    scheduled_at: str
    timezone: str
    status: str
    priority: int
    attempt_count: int
    max_attempts: int
    next_attempt_at: str | None = None
    queued_at: str | None = None
    publishing_started_at: str | None = None
    published_at: str | None = None
    last_error: str | None = None
    partially_published_segments: int = 0
    recurring_schedule_id: str | None = None
    native_schedule: bool = False
    validation: dict[str, Any] | None = None
    attempts: list[AttemptOut] = Field(default_factory=list)
    created_by: CreatorBrief
    created_at: str | None = None
    updated_at: str | None = None


class BestTimesIn(BaseModel):
    brand_id: UUID
    platform: str
    social_account_id: UUID | None = None
    from_: datetime = Field(alias="from")
    to: datetime
    count: int = Field(default=5, ge=1, le=50)
    model_config = ConfigDict(populate_by_name=True)


class SlotOut(BaseModel):
    at: str
    local: str
    weekday: int
    hour: int
    score: float
    basis: str
    n: int


class BestTimesOut(BaseModel):
    slots: list[SlotOut]
    timezone: str
    evidence: str
    n_posts: int
    min_gap_minutes: int
    token_expires_at: str | None = None


class RecurringCreate(BaseModel):
    brand_id: UUID
    name: str = Field(min_length=1, max_length=200)
    rrule: str
    timezone: str = "UTC"
    kind: str = "repost_variant"
    payload: dict[str, Any] = Field(default_factory=dict)


class RecurringOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: UUID
    workspace_id: UUID
    brand_id: UUID
    name: str
    rrule: str
    timezone: str
    kind: str
    payload: dict[str, Any] = Field(default_factory=dict)
    status: str
    next_run_at: datetime | None = None
    last_materialized_until: datetime | None = None
    created_by: UUID
    created_at: datetime


class CalendarOut(BaseModel):
    from_: str = Field(alias="from")
    to: str
    cards: list[dict[str, Any]]
    tray: list[dict[str, Any]]
    model_config = ConfigDict(populate_by_name=True)

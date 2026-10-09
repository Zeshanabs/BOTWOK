"""Trends API schemas."""
from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator


class TrendOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: UUID
    brand_id: UUID
    label: str
    summary: str | None = None
    score: float
    velocity: float | None = None
    status: str
    platforms: list[str] = Field(default_factory=list)
    keywords: list[str] = Field(default_factory=list)
    first_seen: datetime
    last_seen: datetime
    example_source_ids: list[UUID] = Field(default_factory=list)
    ai_run_id: UUID | None = None
    created_at: datetime | None = None
    updated_at: datetime | None = None

    @field_validator("platforms", mode="before")
    @classmethod
    def _platforms(cls, v: Any) -> Any:
        return [getattr(p, "value", p) for p in (v or [])]


class SignalOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: UUID
    kind: str
    term: str
    platform: str | None = None
    observed_at: datetime
    value: float
    source_id: UUID | None = None
    meta: dict[str, Any] = Field(default_factory=dict)

    @field_validator("platform", mode="before")
    @classmethod
    def _platform(cls, v: Any) -> Any:
        return getattr(v, "value", v)


class TrendDetail(TrendOut):
    signals: list[SignalOut] = Field(default_factory=list)


class TrendScanRequest(BaseModel):
    brand_id: UUID
    window_days: int = Field(default=14, ge=7, le=60)

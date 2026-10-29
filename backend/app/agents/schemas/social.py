from __future__ import annotations

from typing import Literal

from pydantic import Field

from app.agents.schemas.common import SourcedOutput, StrictBase


class SocialPostRef(StrictBase):
    platform: str
    external_id: str | None = None
    url: str | None = None
    author: str | None = None
    text: str | None = Field(default=None, max_length=4000)
    published_at: str | None = None
    metrics: dict[str, float] = Field(default_factory=dict)
    source_id: str | None = None
    themes: list[str] = Field(default_factory=list)


class AvailabilityEntry(StrictBase):
    platform: str
    status: Literal["official_api", "not_available", "needs_approval", "quota_exhausted"]
    reason: str | None = None


class AudienceSignal(StrictBase):
    signal: str
    evidence: str | None = None
    platforms: list[str] = Field(default_factory=list)
    strength: float | None = Field(default=None, ge=0, le=1)


class SocialListeningResult(SourcedOutput):
    posts: list[SocialPostRef] = Field(default_factory=list)
    themes: list[str] = Field(default_factory=list)
    hashtags: list[str] = Field(default_factory=list)
    audience_signals: list[AudienceSignal] = Field(default_factory=list)
    availability: list[AvailabilityEntry] = Field(default_factory=list)
    summary: str | None = None

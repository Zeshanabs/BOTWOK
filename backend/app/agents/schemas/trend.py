from __future__ import annotations

from pydantic import Field

from app.agents.schemas.common import SourcedOutput, StrictBase


class TrendItem(StrictBase):
    label: str
    summary: str
    score: float = Field(default=0.0, ge=0)
    velocity: float | None = None
    first_seen: str | None = None
    platforms: list[str] = Field(default_factory=list)
    keywords: list[str] = Field(default_factory=list)
    example_sources: list[str] = Field(default_factory=list, description="source_ids")
    brand_relevance: float | None = Field(default=None, ge=0, le=1)
    trend_id: str | None = None


class TrendSet(SourcedOutput):
    trends: list[TrendItem] = Field(default_factory=list)
    window_days: int | None = None


class TrendExplanation(SourcedOutput):
    trend_id: str | None = None
    label: str
    explanation: str
    drivers: list[str] = Field(default_factory=list)
    content_angles: list[str] = Field(default_factory=list)

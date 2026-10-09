from __future__ import annotations

from pydantic import Field

from app.agents.schemas.common import SourcedOutput, StrictBase


class Pillar(StrictBase):
    name: str
    share: float = Field(default=0.0, ge=0, le=1)
    rationale: str | None = None


class PlatformStrategy(StrictBase):
    formats: list[str] = Field(default_factory=list)
    cadence: str | None = None                  # e.g. "3/week"
    best_times: list[str] = Field(default_factory=list)
    tone_adjustments: str | None = None


class CampaignIdea(StrictBase):
    name: str
    goal: str | None = None
    duration_weeks: int | None = None
    pillars: list[str] = Field(default_factory=list)


class Strategy(SourcedOutput):
    pillars: list[Pillar] = Field(default_factory=list)
    themes: list[str] = Field(default_factory=list)
    campaigns: list[CampaignIdea] = Field(default_factory=list)
    platform_strategy: dict[str, PlatformStrategy] = Field(default_factory=dict)
    content_mix: dict[str, float] = Field(default_factory=dict, description="content_type -> share")
    recommended_topics: list[str] = Field(default_factory=list)
    rationale: list[str] = Field(default_factory=list)
    trade_offs: list[str] = Field(default_factory=list)


class MixRecommendation(SourcedOutput):
    period: str | None = None
    content_mix: dict[str, float] = Field(default_factory=dict)
    pillar_mix: dict[str, float] = Field(default_factory=dict)
    cadence: dict[str, str] = Field(default_factory=dict)
    rationale: list[str] = Field(default_factory=list)


class CalendarSlot(StrictBase):
    date: str
    platform: str
    pillar: str | None = None
    content_type: str | None = None
    format: str | None = None
    topic: str
    idea_id: str | None = None
    notes: str | None = None


class CalendarPlan(SourcedOutput):
    period: str | None = None
    slots: list[CalendarSlot] = Field(default_factory=list)
    rationale: list[str] = Field(default_factory=list)


class Opportunity(StrictBase):
    title: str
    why_now: str
    pillar: str | None = None
    platforms: list[str] = Field(default_factory=list)
    candidate_ref: str | None = None            # trend label / idea id / source id
    priority: int = Field(default=3, ge=1, le=5)
    sources: list[str] = Field(default_factory=list)


class OpportunitySelection(SourcedOutput):
    selected: list[Opportunity] = Field(default_factory=list)
    rejected_reasons: list[str] = Field(default_factory=list)

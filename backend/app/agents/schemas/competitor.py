from __future__ import annotations

from pydantic import Field

from app.agents.schemas.common import SourcedOutput, StrictBase


class CompetitorRef(StrictBase):
    competitor_id: str | None = None
    name: str
    website: str | None = None
    handles: dict[str, str] = Field(default_factory=dict, description="platform -> handle")
    reason: str | None = None


class CompetitorList(SourcedOutput):
    competitors: list[CompetitorRef] = Field(default_factory=list)


class CompetitorAnalysis(SourcedOutput):
    competitor_id: str | None = None
    competitor_name: str | None = None
    posting_frequency: dict[str, float] = Field(default_factory=dict, description="platform -> posts per week")
    format_mix: dict[str, float] = Field(default_factory=dict)
    pillars: list[str] = Field(default_factory=list)
    hooks: list[str] = Field(default_factory=list)
    tone: str | None = None
    hashtags: list[str] = Field(default_factory=list)
    campaigns: list[str] = Field(default_factory=list)
    offers: list[str] = Field(default_factory=list)
    visual_style: str | None = None
    website_changes: list[str] = Field(default_factory=list)
    blog_activity: str | None = None
    news_mentions: list[str] = Field(default_factory=list)
    strengths: list[str] = Field(default_factory=list)
    weaknesses: list[str] = Field(default_factory=list)
    opportunities: list[str] = Field(default_factory=list)
    data_coverage: dict[str, str] = Field(default_factory=dict, description="platform -> availability")
    summary: str | None = None


class Gap(StrictBase):
    topic: str
    evidence: str
    sources: list[str] = Field(default_factory=list)
    opportunity_score: float = Field(default=0.5, ge=0, le=1)
    suggested_formats: list[str] = Field(default_factory=list)


class GapAnalysis(SourcedOutput):
    gaps: list[Gap] = Field(default_factory=list)
    recommendations: list[str] = Field(default_factory=list)


class ComparisonRow(StrictBase):
    competitor_id: str | None = None
    name: str
    metrics: dict[str, float | str] = Field(default_factory=dict)
    notes: str | None = None


class CompetitorComparison(SourcedOutput):
    rows: list[ComparisonRow] = Field(default_factory=list)
    dimensions: list[str] = Field(default_factory=list)
    summary: str | None = None

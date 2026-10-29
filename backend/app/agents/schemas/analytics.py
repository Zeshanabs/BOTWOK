from __future__ import annotations

from typing import Literal

from pydantic import Field

from app.agents.schemas.common import AgentOutput, StrictBase


class Insight(StrictBase):
    statement: str
    metric: str | None = None
    effect: str | None = None                   # e.g. "+34% engagement rate"
    n: int | None = None
    confidence: float | None = Field(default=None, ge=0, le=1)
    evidence_ids: list[str] = Field(default_factory=list)
    early_signal: bool = False
    platforms: list[str] = Field(default_factory=list)


class Recommendation(StrictBase):
    action: str
    rationale: str
    expected_impact: str | None = None
    priority: Literal["high", "medium", "low"] = "medium"
    links_to: str | None = None                 # pillar | format | time | topic | platform
    target: str | None = None


class Insights(AgentOutput):
    insights: list[Insight] = Field(default_factory=list)
    recommendations: list[Recommendation] = Field(default_factory=list)
    period: str | None = None
    data_notes: list[str] = Field(default_factory=list, description="missing metrics / small n warnings")

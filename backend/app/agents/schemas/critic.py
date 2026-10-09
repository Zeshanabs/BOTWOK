from __future__ import annotations

from typing import Literal

from pydantic import Field

from app.agents.schemas.common import AgentOutput, StrictBase


class Scores(StrictBase):
    quality: float = Field(default=0.5, ge=0, le=1)
    brand_fit: float = Field(default=0.5, ge=0, le=1)
    platform_fit: float = Field(default=0.5, ge=0, le=1)
    clarity: float = Field(default=0.5, ge=0, le=1)
    hook_strength: float = Field(default=0.5, ge=0, le=1)
    cta_strength: float = Field(default=0.5, ge=0, le=1)
    risk: float = Field(default=0.0, ge=0, le=1)


class Issue(StrictBase):
    severity: Literal["low", "medium", "high", "blocker"] = "low"
    kind: str
    span: str | None = None
    suggestion: str | None = None


class Critique(AgentOutput):
    scores: Scores = Field(default_factory=Scores)
    issues: list[Issue] = Field(default_factory=list)
    rewrite_suggestions: list[str] = Field(default_factory=list)
    policy_flags: list[str] = Field(default_factory=list)
    overall: float = Field(default=0.5, ge=0, le=1)
    recommend: Literal["approve", "revise", "reject"] = "revise"
    risk_level: Literal["low", "medium", "high"] = "low"
    topic_shift: bool = False

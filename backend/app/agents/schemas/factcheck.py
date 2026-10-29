from __future__ import annotations

from typing import Literal

from pydantic import Field

from app.agents.schemas.common import AgentOutput, StrictBase


class Evidence(StrictBase):
    source_id: str | None = None
    url: str | None = None
    quote: str | None = Field(default=None, max_length=1000)


class Claim(StrictBase):
    text: str
    verdict: Literal["supported", "contradicted", "unverifiable", "opinion"] = "unverifiable"
    confidence: float = Field(default=0.5, ge=0, le=1)
    evidence: list[Evidence] = Field(default_factory=list)
    regulated_domain: str | None = None         # health | finance | legal | None


class FactCheck(AgentOutput):
    claims: list[Claim] = Field(default_factory=list)
    overall_risk: Literal["low", "medium", "high"] = "low"
    requires_human: bool = True
    blocking: bool = False

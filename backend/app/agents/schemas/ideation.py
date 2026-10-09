from __future__ import annotations

from pydantic import Field

from app.agents.schemas.common import AgentOutput, StrictBase


class Idea(StrictBase):
    title: str
    angle: str
    pillar: str | None = None
    content_type: str | None = None
    formats: list[str] = Field(default_factory=list)
    platforms: list[str] = Field(default_factory=list)
    hook_options: list[str] = Field(default_factory=list, max_length=5)
    evidence_sources: list[str] = Field(default_factory=list, description="source_ids / trend ids / insight ids")
    novelty_score: float = Field(default=0.5, ge=0, le=1)
    idea_id: str | None = None


class IdeaBatch(AgentOutput):
    ideas: list[Idea] = Field(default_factory=list)
    dropped_as_duplicates: int = 0

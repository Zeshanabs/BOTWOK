"""Shared output primitives: SourceRef, ClaimSource, AgentOutput (reasoning_summary + confidence), SourcedOutput."""
from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class StrictBase(BaseModel):
    model_config = ConfigDict(extra="ignore", populate_by_name=True)


class SourceRef(StrictBase):
    source_id: str | None = None
    url: str | None = None
    title: str | None = None
    domain: str | None = None
    published_at: str | None = None
    snippet: str | None = Field(default=None, max_length=2000)
    credibility: float | None = Field(default=None, ge=0, le=1)
    relevance: float | None = Field(default=None, ge=0, le=1)
    kind: str | None = None                      # webpage | news | social_post | document | internal


class ClaimSource(StrictBase):
    claim: str
    source_id: str | None = None
    url: str | None = None
    unsourced: bool = False


class AgentOutput(StrictBase):
    """Every agent action returns a subclass. `reasoning_summary` is agent-written (3–8 bullets), never chain-of-thought."""
    reasoning_summary: list[str] = Field(default_factory=list, max_length=12)
    confidence: float | None = Field(default=None, ge=0, le=1)


class SourcedOutput(AgentOutput):
    sources: list[SourceRef] = Field(default_factory=list)


class GenericOutput(SourcedOutput):
    """Fallback for actions without a dedicated schema."""
    result: dict[str, Any] = Field(default_factory=dict)
    summary: str | None = None

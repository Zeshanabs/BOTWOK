from __future__ import annotations

from pydantic import Field

from app.agents.schemas.common import SourcedOutput, StrictBase


class KeyFinding(StrictBase):
    text: str
    sources: list[str] = Field(default_factory=list, description="source_ids supporting this finding")
    importance: float | None = Field(default=None, ge=0, le=1)


class ResearchResult(SourcedOutput):
    summary: str
    key_findings: list[KeyFinding] = Field(default_factory=list)
    topics: list[str] = Field(default_factory=list)
    keywords: list[str] = Field(default_factory=list)
    gaps: list[str] = Field(default_factory=list, description="questions the sources did not answer")
    query_variants: list[str] = Field(default_factory=list)


class SourceDetail(SourcedOutput):
    source_id: str
    title: str | None = None
    summary: str
    key_points: list[str] = Field(default_factory=list)
    quotes: list[str] = Field(default_factory=list)


class CrawlResult(SourcedOutput):
    root_url: str
    pages_fetched: int = 0
    summary: str
    key_findings: list[KeyFinding] = Field(default_factory=list)

"""Research API schemas (doc 17 §17.2 Research)."""
from __future__ import annotations

from datetime import datetime
from typing import Any, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator

ResearchScope = Literal["web", "news", "rss", "competitor_sites", "social", "instagram", "x", "threads", "youtube",
                        "linkedin", "tiktok", "facebook", "pinterest"]
Depth = Literal["quick", "standard", "deep"]


class ResearchRunCreate(BaseModel):
    query: str = Field(min_length=2, max_length=500)
    scope: list[ResearchScope] = Field(default_factory=lambda: ["web"], max_length=8)
    depth: Depth = "standard"
    recency_days: int | None = Field(default=None, ge=1, le=3650)
    brand_id: UUID | None = None
    competitor_id: UUID | None = None
    competitor_ids: list[UUID] = Field(default_factory=list, max_length=10)
    domains_allow: list[str] = Field(default_factory=list, max_length=20)
    domains_deny: list[str] = Field(default_factory=list, max_length=50)
    ai_run_id: UUID | None = None

    @field_validator("query")
    @classmethod
    def _strip(cls, v: str) -> str:
        v = " ".join(v.split())
        if len(v) < 2:
            raise ValueError("query too short")
        return v

    @field_validator("domains_allow", "domains_deny")
    @classmethod
    def _domains(cls, v: list[str]) -> list[str]:
        out = []
        for d in v:
            d = d.strip().lower()
            if d and len(d) <= 253:
                out.append(d)
        return out

    @field_validator("scope")
    @classmethod
    def _scope(cls, v: list[str]) -> list[str]:
        seen: list[str] = []
        for s in v or ["web"]:
            if s not in seen:
                seen.append(s)
        return seen or ["web"]


class RunAccepted(BaseModel):
    run_id: UUID
    ai_run_id: UUID | None = None
    status: str
    status_url: str


class SourceCard(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: UUID
    title: str | None = None
    canonical_url: str
    domain: str
    source_kind: str
    published_at: datetime | None = None
    retrieved_at: datetime | None = None
    summary: str | None = None
    credibility_score: float | None = None
    injection_flag: bool = False
    fetch_status: str = "ok"
    competitor_id: UUID | None = None
    trust: str = "untrusted"
    keywords: list[str] = Field(default_factory=list)


class RankedSource(BaseModel):
    id: UUID
    rank: int
    title: str | None = None
    url: str
    domain: str
    published_at: datetime | None = None
    relevance: float
    credibility: float | None = None
    summary: str | None = None
    injection_flag: bool = False
    source_kind: str = "web"
    query_variant: str | None = None


class ResearchRunOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: UUID
    query: str
    scope: list[str]
    depth: str
    status: str
    brand_id: UUID | None = None
    competitor_id: UUID | None = None
    ai_run_id: UUID | None = None
    params: dict[str, Any] = Field(default_factory=dict)
    source_count: int = 0
    cost_usd: float = 0
    error: str | None = None
    created_at: datetime | None = None
    started_at: datetime | None = None
    completed_at: datetime | None = None


class ResearchRunDetail(ResearchRunOut):
    result: dict[str, Any] | None = None
    sources: list[RankedSource] = Field(default_factory=list)


class SourceDetail(SourceCard):
    final_url: str | None = None
    author: str | None = None
    language: str | None = None
    topics: list[str] = Field(default_factory=list)
    entities: dict[str, Any] = Field(default_factory=dict)
    credibility_components: dict[str, Any] | None = None
    citation: str | None = None
    word_count: int | None = None
    duplicates_of: UUID | None = None
    error: str | None = None
    text: str | None = None
    text_truncated: bool = False


class SourcePin(BaseModel):
    pinned: bool = True
    notes: str | None = Field(default=None, max_length=4000)
    brand_id: UUID | None = None
    trust: Literal["trusted", "untrusted"] | None = None
    credibility_override: float | None = Field(default=None, ge=0, le=1)


class FeedCreate(BaseModel):
    url: str = Field(min_length=8, max_length=2000)
    title: str | None = Field(default=None, max_length=300)
    brand_id: UUID | None = None
    competitor_id: UUID | None = None
    poll_now: bool = True


class FeedOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: UUID
    url: str
    title: str | None = None
    status: str
    brand_id: UUID | None = None
    competitor_id: UUID | None = None
    last_polled_at: datetime | None = None
    last_error: str | None = None
    created_at: datetime | None = None


class KeywordCreate(BaseModel):
    term: str = Field(min_length=1, max_length=120)
    brand_id: UUID | None = None
    related: list[str] = Field(default_factory=list, max_length=50)
    volume_hint: int | None = Field(default=None, ge=0)

    @field_validator("term")
    @classmethod
    def _term(cls, v: str) -> str:
        v = " ".join(v.split()).lower()
        if not v:
            raise ValueError("empty term")
        return v


class KeywordOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: UUID
    term: str
    brand_id: UUID | None = None
    source: str
    volume_hint: int | None = None
    related: list[str] = Field(default_factory=list)
    frequency: dict[str, Any] = Field(default_factory=dict)
    first_seen: datetime | None = None
    last_seen: datetime | None = None

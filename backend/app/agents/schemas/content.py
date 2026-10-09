from __future__ import annotations

from typing import Any

from pydantic import Field

from app.agents.schemas.common import AgentOutput, ClaimSource, StrictBase


class GenerationMetadata(StrictBase):
    model: str | None = None
    prompt_version: int | None = None
    temperature: float | None = None
    run_id: str | None = None


class ContentDraft(AgentOutput):
    title: str | None = None
    hook: str
    body: str
    cta: str | None = None
    hashtags: list[str] = Field(default_factory=list)
    keywords: list[str] = Field(default_factory=list)
    visual_concept: str | None = None
    alt_text: str | None = None
    platform: str | None = None
    format: str | None = None
    content_type: str | None = None
    platform_metadata: dict[str, Any] = Field(default_factory=dict)
    sources: list[ClaimSource] = Field(default_factory=list, description="claim -> source_id (or unsourced=true)")
    generation_metadata: GenerationMetadata = Field(default_factory=GenerationMetadata)
    content_id: str | None = None
    variant_id: str | None = None


class Variant(AgentOutput):
    platform: str
    format: str | None = None
    text: str | None = None
    segments: list[str] = Field(default_factory=list, description="ordered parts for threads/carousels/scripts")
    hashtags: list[str] = Field(default_factory=list)
    media_plan: dict[str, Any] = Field(default_factory=dict)
    metadata: dict[str, Any] = Field(default_factory=dict)
    changes_made: list[str] = Field(default_factory=list)
    variant_id: str | None = None
    content_id: str | None = None

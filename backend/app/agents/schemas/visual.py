from __future__ import annotations

from typing import Any

from pydantic import Field

from app.agents.schemas.common import AgentOutput, StrictBase


class TextOverlay(StrictBase):
    slide: int | None = None
    text: str
    position: str | None = None


class VisualPlan(AgentOutput):
    concept: str
    image_prompts: list[str] = Field(default_factory=list)
    negative_prompts: list[str] = Field(default_factory=list)
    layout: str | None = None
    text_overlays: list[TextOverlay] = Field(default_factory=list)
    brand_elements: dict[str, Any] = Field(default_factory=dict)
    alt_text: str
    assets: list[str] = Field(default_factory=list, description="media_asset_ids created")
    script: list[dict[str, Any]] = Field(default_factory=list, description="video: [{t, on_screen, spoken}]")
    duration_s: int | None = None
    policy_flags: list[str] = Field(default_factory=list)

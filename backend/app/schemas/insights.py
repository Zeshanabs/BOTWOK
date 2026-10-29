"""Insights & recommendations API schemas (doc 13 §13.5, doc 17 "Analytics & insights")."""
from __future__ import annotations

from datetime import date, datetime
from typing import Any, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator


class InsightOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: UUID
    brand_id: UUID
    period_start: date
    period_end: date
    statement: str
    kind: str
    metric: str | None = None
    effect_size: float | None = None
    n: int | None = None
    confidence: str
    evidence: dict[str, Any] = Field(default_factory=dict)
    ai_run_id: UUID | None = None
    status: str
    created_at: datetime | None = None

    @field_validator("effect_size", mode="before")
    @classmethod
    def _num(cls, v: Any) -> float | None:
        return float(v) if v is not None else None


class RecommendationOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: UUID
    brand_id: UUID
    insight_id: UUID | None = None
    action: str
    rationale: str | None = None
    expected_impact: str | None = None
    priority: str
    target: dict[str, Any] = Field(default_factory=dict)
    status: str
    applied_to: dict[str, Any] | None = None
    decided_by: UUID | None = None
    decided_at: datetime | None = None
    created_at: datetime | None = None


class AnalyzeIn(BaseModel):
    brand_id: UUID
    period_days: int = Field(default=30, ge=1, le=365)
    mode: Literal["auto", "deterministic", "ai"] = "auto"
    metric: Literal["engagement_rate", "engagement", "impressions", "reach", "views", "clicks", "saves", "shares"] = "engagement_rate"


class AnalyzeOut(BaseModel):
    """202 (AI run started) → ``run_id``/``status_url``; 200 (deterministic) → counts and ids."""
    mode: Literal["ai", "deterministic"]
    run_id: UUID | None = None
    status: str | None = None
    status_url: str | None = None
    insights_created: int | None = None
    recommendations_created: int | None = None
    insight_ids: list[UUID] = Field(default_factory=list)
    recommendation_ids: list[UUID] = Field(default_factory=list)
    period: dict[str, Any] = Field(default_factory=dict)
    coverage: dict[str, Any] | None = None
    data_notes: list[str] = Field(default_factory=list)


class RecommendationDecisionIn(BaseModel):
    status: Literal["accepted", "rejected"]
    reason: str | None = Field(default=None, max_length=1000)


class AcknowledgeIn(BaseModel):
    status: Literal["acknowledged", "dismissed"] = "acknowledged"

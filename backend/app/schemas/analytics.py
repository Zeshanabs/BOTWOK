"""Analytics API schemas (doc 17 "Analytics & insights")."""
from __future__ import annotations

from typing import Any
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


class SyncIn(BaseModel):
    social_account_id: UUID | None = None
    brand_id: UUID | None = None
    force: bool = False


class SyncOut(BaseModel):
    enqueued: int
    account_ids: list[str]


class KPI(BaseModel):
    value: float | None = None
    coverage: int = 0
    basis: Any = None
    median: float | None = None
    previous: float | None = None
    delta_pct: float | None = None


class OverviewOut(BaseModel):
    brand_id: str | None = None
    from_: str = Field(alias="from")
    to: str
    kpis: dict[str, KPI]
    previous_period: dict[str, str] | None = None
    accounts: list[dict[str, Any]] = Field(default_factory=list)
    model_config = ConfigDict(populate_by_name=True)


class PostMetricsOut(BaseModel):
    published_post_id: str
    external_id: str
    external_url: str | None = None
    published_at: str
    platform: str
    social_account_id: str
    account_name: str | None = None
    content_variant_id: str | None = None
    content_item_id: str | None = None
    title: str | None = None
    text: str | None = None
    format: str | None = None
    pillar_id: str | None = None
    campaign_id: str | None = None
    content_type: str | None = None
    captured_at: str | None = None
    metrics: dict[str, float | None]
    availability: dict[str, str]
    engagement_rate: float | None = None
    engagement_rate_basis: str | None = None


class PostsOut(BaseModel):
    items: list[PostMetricsOut]
    coverage: dict[str, int]


class BreakdownGroup(BaseModel):
    key: str
    label: str
    n: int
    n_with_metric: int
    value: float | None = None
    median: float | None = None
    ci: list[float | None] | None = None
    effect_vs_overall: float | None = None
    min_n_ok: bool


class BreakdownOut(BaseModel):
    by: str
    metric: str
    groups: list[BreakdownGroup]
    coverage: dict[str, int]
    basis: dict[str, int]
    overall: float | None = None

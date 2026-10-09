"""Request/response schemas for ideas, campaigns, content, variants, versions and approvals."""
from __future__ import annotations

from datetime import date, datetime
from typing import Any, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from app.models.enums import (
    ApprovalStatus,
    ContentFormat,
    ContentStatus,
    ContentType,
    MemberRole,
    Platform,
    RiskLevel,
)


class _Out(BaseModel):
    model_config = ConfigDict(from_attributes=True)


# ── common ─────────────────────────────────────────────────────────────────────

class RunAccepted(BaseModel):
    run_id: UUID | str
    run_ids: list[UUID | str] = Field(default_factory=list)
    status: str = "queued"
    status_url: str


class ValidationIssue(BaseModel):
    code: str
    message: str
    field: str | None = None
    severity: Literal["error", "warning", "info"] = "error"


class ValidationResult(BaseModel):
    ok: bool
    issues: list[ValidationIssue] = Field(default_factory=list)
    stats: dict[str, Any] = Field(default_factory=dict)


# ── ideas ──────────────────────────────────────────────────────────────────────

class IdeaCreate(BaseModel):
    brand_id: UUID
    title: str = Field(min_length=1, max_length=500)
    angle: str | None = None
    campaign_id: UUID | None = None
    pillar_id: UUID | None = None
    content_type: ContentType | None = None
    formats: list[ContentFormat] = Field(default_factory=list)
    platforms: list[Platform] = Field(default_factory=list)
    hooks: list[Any] = Field(default_factory=list)
    evidence: dict[str, Any] = Field(default_factory=dict)
    score: float | None = None


class IdeaUpdate(BaseModel):
    title: str | None = Field(default=None, min_length=1, max_length=500)
    angle: str | None = None
    campaign_id: UUID | None = None
    pillar_id: UUID | None = None
    content_type: ContentType | None = None
    formats: list[ContentFormat] | None = None
    platforms: list[Platform] | None = None
    hooks: list[Any] | None = None
    evidence: dict[str, Any] | None = None
    score: float | None = None
    status: Literal["new", "shortlisted", "promoted", "discarded"] | None = None


class IdeaOut(_Out):
    id: UUID
    brand_id: UUID
    campaign_id: UUID | None = None
    pillar_id: UUID | None = None
    title: str
    angle: str | None = None
    content_type: ContentType | None = None
    formats: list[ContentFormat] = Field(default_factory=list)
    platforms: list[Platform] = Field(default_factory=list)
    hooks: list[Any] = Field(default_factory=list)
    evidence: dict[str, Any] = Field(default_factory=dict)
    score: float | None = None
    novelty_score: float | None = None
    status: str
    promoted_content_id: UUID | None = None
    ai_run_id: UUID | None = None
    created_by: UUID | None = None
    created_at: datetime
    updated_at: datetime


class IdeaGenerateFrom(BaseModel):
    trend_ids: list[UUID] | None = None
    research_run_id: UUID | None = None
    insight_ids: list[UUID] | None = None
    prompt: str | None = None


class IdeaGenerateRequest(BaseModel):
    model_config = ConfigDict(populate_by_name=True)
    brand_id: UUID
    count: int = Field(default=10, ge=1, le=50)
    pillars: list[str] | None = None
    platforms: list[Platform] | None = None
    from_: IdeaGenerateFrom | None = Field(default=None, alias="from")


class IdeaPromoteRequest(BaseModel):
    title: str | None = None
    master_format: ContentFormat | None = None
    campaign_id: UUID | None = None
    assigned_to: UUID | None = None


# ── campaigns ──────────────────────────────────────────────────────────────────

CampaignStatus = Literal["planned", "active", "completed", "archived"]


class CampaignCreate(BaseModel):
    brand_id: UUID
    name: str = Field(min_length=1, max_length=200)
    description: str | None = None
    goal: str | None = None
    starts_on: date | None = None
    ends_on: date | None = None
    color: str | None = None
    status: CampaignStatus = "planned"


class CampaignUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=200)
    description: str | None = None
    goal: str | None = None
    starts_on: date | None = None
    ends_on: date | None = None
    color: str | None = None
    status: CampaignStatus | None = None


class CampaignOut(_Out):
    id: UUID
    brand_id: UUID
    name: str
    description: str | None = None
    goal: str | None = None
    starts_on: date | None = None
    ends_on: date | None = None
    color: str | None = None
    status: str
    created_by: UUID
    created_at: datetime
    updated_at: datetime


# ── content ────────────────────────────────────────────────────────────────────

class ContentBody(BaseModel):
    model_config = ConfigDict(extra="allow")
    hook: str | None = None
    body_md: str | None = None
    cta: str | None = None
    hashtags: list[str] | None = None
    keywords: list[str] | None = None
    visual_concept: str | None = None
    alt_text: str | None = None
    notes: str | None = None


class ContentCreate(BaseModel):
    brand_id: UUID
    title: str = Field(min_length=1, max_length=500)
    content_type: ContentType | None = None
    pillar_id: UUID | None = None
    campaign_id: UUID | None = None
    idea_id: UUID | None = None
    master_format: ContentFormat = ContentFormat.text
    body: ContentBody | None = None
    language: str = "en"
    assigned_to: UUID | None = None


class ContentUpdate(BaseModel):
    title: str | None = Field(default=None, min_length=1, max_length=500)
    content_type: ContentType | None = None
    pillar_id: UUID | None = None
    campaign_id: UUID | None = None
    master_format: ContentFormat | None = None
    body: ContentBody | None = None
    language: str | None = None
    assigned_to: UUID | None = None


class TransitionRequest(BaseModel):
    to: ContentStatus
    comment: str | None = Field(default=None, max_length=2000)


class RequestApprovalRequest(BaseModel):
    comment: str | None = Field(default=None, max_length=2000)
    expires_in_hours: int = Field(default=72, ge=1, le=24 * 30)


class GenerateRequest(BaseModel):
    mode: Literal["write", "rewrite", "shorten", "expand", "change_tone", "regenerate"] = "write"
    platform: Platform | None = None
    format: ContentFormat | None = None
    instructions: str | None = Field(default=None, max_length=4000)
    source_ids: list[UUID] = Field(default_factory=list)
    length: str | int | None = None


class RepurposeTarget(BaseModel):
    platform: Platform
    format: ContentFormat
    social_account_id: UUID | None = None


class RepurposeRequest(BaseModel):
    targets: list[RepurposeTarget] = Field(min_length=1, max_length=13)


class CritiqueRequest(BaseModel):
    variant_id: UUID | None = None


class VariantCreate(BaseModel):
    platform: Platform
    format: ContentFormat
    social_account_id: UUID | None = None
    text: str | None = None
    segments: list[Any] = Field(default_factory=list)
    hashtags: list[str] = Field(default_factory=list)
    media_plan: dict[str, Any] = Field(default_factory=dict)
    platform_metadata: dict[str, Any] = Field(default_factory=dict)
    changes_made: list[str] = Field(default_factory=list)


class VariantUpdate(BaseModel):
    text: str | None = None
    segments: list[Any] | None = None
    hashtags: list[str] | None = None
    media_plan: dict[str, Any] | None = None
    platform_metadata: dict[str, Any] | None = None
    social_account_id: UUID | None = None
    changes_made: list[str] | None = None


class AssetAttachRequest(BaseModel):
    media_asset_id: UUID
    variant_id: UUID | None = None
    role: Literal["primary", "carousel_slide", "thumbnail", "cover", "subtitle"] = "primary"
    position: int | None = Field(default=None, ge=0)
    alt_text: str | None = Field(default=None, max_length=2000)


class MediaBrief(BaseModel):
    id: UUID
    kind: str
    mime: str
    width: int | None = None
    height: int | None = None
    duration_ms: int | None = None
    bytes: int | None = None
    sha256: str | None = None
    alt_text: str | None = None
    status: str | None = None
    object_key: str | None = None
    bucket: str | None = None


class AssetOut(BaseModel):
    id: UUID
    media_asset_id: UUID
    variant_id: UUID | None = None
    content_item_id: UUID | None = None
    role: str
    position: int
    alt_text: str | None = None
    media: MediaBrief | None = None


class VariantOut(BaseModel):
    id: UUID
    content_item_id: UUID
    platform: Platform
    format: ContentFormat
    social_account_id: UUID | None = None
    text: str | None = None
    segments: list[Any] = Field(default_factory=list)
    hashtags: list[str] = Field(default_factory=list)
    media_plan: dict[str, Any] = Field(default_factory=dict)
    platform_metadata: dict[str, Any] = Field(default_factory=dict)
    status: ContentStatus
    validation: ValidationResult | None = None
    critique: dict[str, Any] | None = None
    factcheck: dict[str, Any] | None = None
    changes_made: list[str] = Field(default_factory=list)
    current_version: int
    ai_generated: bool
    generation_metadata: dict[str, Any] = Field(default_factory=dict)
    assets: list[AssetOut] = Field(default_factory=list)
    created_at: datetime
    updated_at: datetime


class SourceOut(BaseModel):
    source_id: UUID
    claim_text: str | None = None
    used_for: str
    title: str | None = None
    url: str | None = None
    domain: str | None = None
    credibility: float | None = None


class ContentListItem(BaseModel):
    id: UUID
    brand_id: UUID
    campaign_id: UUID | None = None
    idea_id: UUID | None = None
    pillar_id: UUID | None = None
    title: str
    content_type: ContentType | None = None
    master_format: ContentFormat
    status: ContentStatus
    body: dict[str, Any] = Field(default_factory=dict)
    language: str
    current_version: int
    ai_generated: bool
    risk_level: RiskLevel
    approval_required: bool
    created_by: UUID
    assigned_to: UUID | None = None
    platforms: list[str] = Field(default_factory=list)
    variant_count: int = 0
    created_at: datetime
    updated_at: datetime


class ContentItemOut(ContentListItem):
    generation_metadata: dict[str, Any] = Field(default_factory=dict)
    critique: dict[str, Any] | None = None
    factcheck: dict[str, Any] | None = None
    variants: list[VariantOut] = Field(default_factory=list)
    sources: list[SourceOut] = Field(default_factory=list)
    assets: list[AssetOut] = Field(default_factory=list)


class VersionOut(_Out):
    id: UUID
    target_type: str
    target_id: UUID
    version: int
    snapshot: dict[str, Any]
    author_type: str
    author_id: str
    ai_call_id: UUID | None = None
    diff_summary: str | None = None
    created_at: datetime


class ContentPage(BaseModel):
    items: list[ContentListItem]
    next_cursor: str | None = None


class IdeaPage(BaseModel):
    items: list[IdeaOut]
    next_cursor: str | None = None


class CampaignPage(BaseModel):
    items: list[CampaignOut]
    next_cursor: str | None = None


# ── approvals ──────────────────────────────────────────────────────────────────

class ApprovalOut(_Out):
    id: UUID
    brand_id: UUID | None = None
    kind: str
    target_type: str
    target_id: UUID
    payload: dict[str, Any] = Field(default_factory=dict)
    status: ApprovalStatus
    requested_by: str
    required_roles: list[MemberRole] = Field(default_factory=list)
    decided_by: UUID | None = None
    decided_at: datetime | None = None
    decision_comment: str | None = None
    expires_at: datetime | None = None
    created_at: datetime


class ApprovalTarget(BaseModel):
    type: str
    id: UUID
    item: ContentItemOut | None = None
    variant_id: UUID | None = None
    variants: list[VariantOut] = Field(default_factory=list)
    critique: dict[str, Any] | None = None
    factcheck: dict[str, Any] | None = None
    sources: list[SourceOut] = Field(default_factory=list)
    generation_metadata: dict[str, Any] | None = None
    risk_level: RiskLevel | None = None
    payload: dict[str, Any] | None = None
    missing: bool = False


class ApprovalDetail(ApprovalOut):
    target: ApprovalTarget | None = None


class ApprovalPage(BaseModel):
    items: list[ApprovalOut]
    next_cursor: str | None = None


class ApproveRequest(BaseModel):
    comment: str | None = Field(default=None, max_length=2000)


class RejectRequest(BaseModel):
    comment: str = Field(min_length=1, max_length=2000)
    decision: Literal["reject", "request_changes"] = "reject"

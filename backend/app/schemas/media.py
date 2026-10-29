"""Media schemas: media_assets, uploads, generation, platform transforms."""
from __future__ import annotations

from datetime import datetime
from typing import Any, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.models.enums import ContentFormat, Platform

CONTENT_ASSET_ROLES = Literal["primary", "carousel_slide", "thumbnail", "cover", "subtitle"]


class MediaAssetOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: UUID
    workspace_id: UUID
    brand_id: UUID | None = None
    kind: str
    source: str
    bucket: str
    object_key: str
    mime: str
    bytes: int
    width: int | None = None
    height: int | None = None
    duration_ms: int | None = None
    fps: float | None = None
    codec: str | None = None
    sha256: str
    alt_text: str | None = None
    caption: str | None = None
    labels: list[str] = Field(default_factory=list)
    ai_generated: bool = False
    provider: str | None = None
    model: str | None = None
    prompt: str | None = None
    seed: int | None = None
    generation_params: dict[str, Any] | None = None
    derived_from_id: UUID | None = None
    transform: dict[str, Any] | None = None
    platform_target: str | None = None
    carousel_group_id: UUID | None = None
    position: int | None = None
    status: str
    error: str | None = None
    created_by: UUID | None = None
    created_at: datetime
    updated_at: datetime
    url: str | None = None


class UploadUrlIn(BaseModel):
    filename: str = Field(min_length=1, max_length=255)
    content_type: str = Field(min_length=3, max_length=120)
    size_bytes: int | None = Field(default=None, ge=1)


class UploadUrlOut(BaseModel):
    upload_url: str
    key: str
    bucket: str
    method: Literal["PUT"] = "PUT"
    headers: dict[str, str] = Field(default_factory=dict)
    expires_in: int


class RegisterUploadIn(BaseModel):
    key: str = Field(min_length=1, max_length=300)
    filename: str = Field(min_length=1, max_length=255)
    brand_id: UUID | None = None
    alt_text: str | None = Field(default=None, max_length=1500)
    caption: str | None = Field(default=None, max_length=2200)


class MediaUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    alt_text: str | None = Field(default=None, max_length=1500)
    caption: str | None = Field(default=None, max_length=2200)
    labels: list[str] | None = None
    brand_id: UUID | None = None


class GenerateImageIn(BaseModel):
    prompt: str = Field(min_length=1, max_length=4000)
    brand_id: UUID | None = None
    provider: str | None = Field(default=None, max_length=40)
    size: str = Field(default="1024x1024", max_length=20)
    n: int = Field(default=1, ge=1, le=4)
    negative_prompt: str | None = Field(default=None, max_length=2000)
    style: str | None = Field(default=None, max_length=200)
    quality: str | None = Field(default=None, max_length=20)
    reference_asset_ids: list[UUID] = Field(default_factory=list, max_length=4)
    alt_text: str | None = Field(default=None, max_length=1500)
    background: bool = False   # true → enqueue jobs.media.generate and return 202

    @field_validator("size")
    @classmethod
    def _size(cls, v: str) -> str:
        from app.integrations.media.base import parse_size
        parse_size(v)
        return v.strip().lower()


class GenerateImageOut(BaseModel):
    items: list[MediaAssetOut]


class TransformIn(BaseModel):
    platform: Platform
    format: ContentFormat
    aspect: str | None = Field(default=None, max_length=12, description="Override, e.g. '1.91:1', '4:5', '16:9'")
    pad_color: str | None = Field(default=None, max_length=9, description="Hex; default = brand primary or white")
    background: bool | None = Field(default=None, description="Force async (videos are always processed async)")


class JobAcceptedOut(BaseModel):
    status: Literal["queued"] = "queued"
    job_id: int | None = None
    detail: str | None = None


class MediaUrlOut(BaseModel):
    url: str
    expires_in: int | None = None
    public: bool = False


class AttachIn(BaseModel):
    media_asset_id: UUID
    variant_id: UUID | None = None
    content_item_id: UUID | None = None
    role: CONTENT_ASSET_ROLES = "primary"
    position: int | None = Field(default=None, ge=0)
    alt_text: str | None = Field(default=None, max_length=1500)

"""Publishing API schemas."""
from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


class PublishNowIn(BaseModel):
    content_variant_id: UUID
    social_account_id: UUID
    force: bool = False


class PublishNowOut(BaseModel):
    scheduled_post_id: str
    status: str


class PublishAttemptOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: UUID
    workspace_id: UUID
    scheduled_post_id: UUID
    attempt_no: int
    idempotency_key: str
    status: str
    state: dict[str, Any] = Field(default_factory=dict)
    request_fingerprint: str
    error_category: str | None = None
    error_code: str | None = None
    error_message: str | None = None
    platform_response: dict[str, Any] | None = None
    worker_id: str | None = None
    heartbeat_at: datetime | None = None
    started_at: datetime
    finished_at: datetime | None = None


class PublishedPostOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: UUID
    workspace_id: UUID
    brand_id: UUID
    scheduled_post_id: UUID | None = None
    content_variant_id: UUID | None = None
    social_account_id: UUID
    platform: str
    external_id: str
    external_url: str | None = None
    segments: list[Any] = Field(default_factory=list)
    published_at: datetime
    imported: bool = False
    deleted_at: datetime | None = None
    created_at: datetime


class DeletedOut(BaseModel):
    id: str
    deleted_at: str

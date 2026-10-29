"""Social accounts API schemas (doc 17 "Social")."""
from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


class SocialAccountOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: UUID
    workspace_id: UUID
    brand_id: UUID
    platform: str
    auth_flavor: str
    external_id: str
    parent_external_id: str | None = None
    display_name: str
    handle: str | None = None
    avatar_url: str | None = None
    account_type: str | None = None
    status: str
    scopes: list[str] = Field(default_factory=list)
    capabilities: dict[str, Any] = Field(default_factory=dict)
    health: dict[str, Any] = Field(default_factory=dict)
    last_probe_at: datetime | None = None
    connected_by: UUID
    disconnected_at: datetime | None = None
    created_at: datetime
    updated_at: datetime
    token_expires_at: datetime | None = None


class ConnectStartOut(BaseModel):
    auth_url: str
    state: str
    platform: str
    flavor: str
    redirect_uri: str
    expires_at: str


class ConnectableAccountOut(BaseModel):
    external_id: str
    display_name: str
    handle: str | None = None
    avatar_url: str | None = None
    account_type: str | None = None
    parent_external_id: str | None = None


class SelectionOut(BaseModel):
    status: str = "select"
    selection_token: str
    platform: str
    accounts: list[ConnectableAccountOut]


class SelectIn(BaseModel):
    selection_token: str
    external_id: str


class AccountHealthOut(BaseModel):
    account_id: str
    status: str
    token_valid: bool | None = None
    scopes_missing: list[str] = Field(default_factory=list)
    capabilities: dict[str, Any] = Field(default_factory=dict)
    limits_remaining: Any = None
    health: dict[str, Any] = Field(default_factory=dict)

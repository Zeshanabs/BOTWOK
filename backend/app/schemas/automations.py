"""Automation API schemas (doc 17 "Automations", doc 14)."""
from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


class NodeIn(BaseModel):
    key: str = Field(min_length=1, max_length=64)
    type: str = Field(min_length=1, max_length=64)
    config: dict[str, Any] = Field(default_factory=dict)
    label: str | None = Field(default=None, max_length=200)
    position: dict[str, Any] | None = None


class EdgeIn(BaseModel):
    model_config = ConfigDict(populate_by_name=True)
    from_: str = Field(alias="from", min_length=1, max_length=64)
    to: str = Field(min_length=1, max_length=64)
    branch: str | None = Field(default=None, max_length=32)
    condition: dict[str, Any] | None = None


class WorkflowSettings(BaseModel):
    model_config = ConfigDict(extra="forbid")
    on_error: str | None = Field(default=None, pattern="^(stop|continue|notify)$")
    max_cost_usd: float | None = Field(default=None, ge=0, le=1000)
    timeout_minutes: int | None = Field(default=None, ge=1, le=43200)
    concurrency: str | None = Field(default=None, pattern="^(single|parallel)$")
    notify_user_ids: list[str] | None = None


class WorkflowCreate(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    description: str | None = Field(default=None, max_length=2000)
    brand_id: UUID | None = None
    nodes: list[NodeIn] = Field(default_factory=list, max_length=100)
    edges: list[EdgeIn] = Field(default_factory=list, max_length=300)
    settings: WorkflowSettings | None = None
    autonomous_actions_enabled: bool = False


class WorkflowUpdate(BaseModel):
    """PUT /automations/{id}: full replacement of nodes/edges; other fields keep their value when omitted."""
    name: str | None = Field(default=None, min_length=1, max_length=200)
    description: str | None = Field(default=None, max_length=2000)
    brand_id: UUID | None = None
    nodes: list[NodeIn] = Field(max_length=100)
    edges: list[EdgeIn] = Field(default_factory=list, max_length=300)
    settings: WorkflowSettings | None = None
    autonomous_actions_enabled: bool | None = None


class NodeOut(BaseModel):
    key: str
    type: str
    config: dict[str, Any]
    label: str | None = None
    position: dict[str, Any] | None = None


class EdgeOut(BaseModel):
    model_config = ConfigDict(populate_by_name=True, serialize_by_alias=True)
    from_: str = Field(alias="from")
    to: str
    branch: str | None = None
    condition: dict[str, Any] | None = None


class WorkflowSummary(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: UUID
    workspace_id: UUID
    brand_id: UUID | None = None
    name: str
    description: str | None = None
    status: str
    version: int
    trigger_summary: str | None = None
    autonomous_actions_enabled: bool
    settings: dict[str, Any] = Field(default_factory=dict)
    last_run_at: datetime | None = None
    next_run_at: datetime | None = None
    created_by: UUID
    created_at: datetime
    updated_at: datetime


class WorkflowOut(WorkflowSummary):
    nodes: list[NodeOut] = Field(default_factory=list)
    edges: list[EdgeOut] = Field(default_factory=list)
    webhook_url: str | None = None          # admins only, when the trigger is trigger.webhook
    signing_secret: str | None = None       # admins only, when the workflow has a webhook node


class WorkflowPage(BaseModel):
    items: list[WorkflowSummary]
    next_cursor: str | None = None


class RunRequest(BaseModel):
    payload: dict[str, Any] = Field(default_factory=dict)
    dry_run: bool = False


class RunAccepted(BaseModel):
    run_id: UUID
    status: str
    dry_run: bool = False
    status_url: str


class RunOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: UUID
    workflow_id: UUID
    workflow_version: int
    trigger_type: str
    trigger_payload: dict[str, Any] = Field(default_factory=dict)
    status: str
    current_node_key: str | None = None
    waiting_until: datetime | None = None
    approval_id: UUID | None = None
    cost_usd: float = 0
    error: str | None = None
    dry_run: bool = False
    started_at: datetime
    finished_at: datetime | None = None


class StepOut(BaseModel):
    id: UUID
    node_key: str
    node_type: str | None = None
    label: str | None = None
    status: str
    input: dict[str, Any] | None = None
    output: dict[str, Any] | None = None
    ai_run_id: UUID | None = None
    attempts: int = 0
    error: str | None = None
    started_at: datetime | None = None
    finished_at: datetime | None = None
    duration_ms: int | None = None


class RunDetail(RunOut):
    context: dict[str, Any] = Field(default_factory=dict)
    steps: list[StepOut] = Field(default_factory=list)


class RunPage(BaseModel):
    items: list[RunOut]
    next_cursor: str | None = None


class FromTemplateRequest(BaseModel):
    name: str | None = Field(default=None, max_length=200)
    brand_id: UUID | None = None
    params: dict[str, Any] = Field(default_factory=dict)
    autonomous_actions_enabled: bool | None = None
    enable: bool = False


class WebhookAccepted(BaseModel):
    run_id: UUID
    status: str

"""Request/response models for /ai routes (doc 17)."""
from __future__ import annotations

from datetime import datetime
from typing import Any, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


class CreateRunRequest(BaseModel):
    message: str = Field(default="", max_length=20000)
    brand_id: UUID | None = None
    conversation_id: UUID | None = None
    mode: Literal["chat", "task", "tool", "automation"] = "chat"
    agent: str | None = None
    action: str | None = None
    inputs: dict[str, Any] | None = None
    budget_usd: float | None = Field(default=None, gt=0, le=100)


class CreateRunResponse(BaseModel):
    run_id: UUID
    conversation_id: UUID | None = None
    status: str
    status_url: str


class TaskView(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    key: str
    parent_key: str | None = None
    label: str
    agent: str
    action: str
    status: str
    duration_ms: int | None = None
    cost_usd: float = 0
    tokens_in: int = 0
    tokens_out: int = 0
    sources_count: int = 0
    depends_on: list[str] = []
    requires_approval: bool = False
    error: str | None = None
    started_at: datetime | None = None
    finished_at: datetime | None = None


class PlanView(BaseModel):
    goal: str | None = None
    tasks: list[TaskView] = []
    deliverables: list[str] = []
    approval_points: list[str] = []


class RunView(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: UUID
    status: str
    mode: str
    brand_id: UUID | None = None
    conversation_id: UUID | None = None
    message: str | None = None
    intent: dict[str, Any] | None = None
    plan: PlanView
    result: dict[str, Any] | None = None
    cost_usd: float = 0
    tokens: dict[str, int] = {}
    budget: dict[str, Any] = {}
    error: str | None = None
    reasoning_summary: str | None = None
    cancel_requested: bool = False
    created_at: datetime | None = None
    started_at: datetime | None = None
    finished_at: datetime | None = None


class RunListItem(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: UUID
    status: str
    mode: str
    brand_id: UUID | None = None
    conversation_id: UUID | None = None
    message: str | None = None
    cost_usd: float = 0
    error: str | None = None
    created_at: datetime | None = None
    finished_at: datetime | None = None


class ToolCallView(BaseModel):
    id: UUID
    task_key: str | None = None
    call_index: int
    tool_name: str
    side_effect: str
    args_summary: str
    result_summary: str
    status: str
    duration_ms: int | None = None
    error: str | None = None
    approval_id: UUID | None = None
    started_at: datetime | None = None
    finished_at: datetime | None = None


class ConversationView(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: UUID
    title: str | None = None
    brand_id: UUID | None = None
    user_id: UUID | None = None
    summary: str | None = None
    context_ref: dict[str, Any] | None = None
    message_count: int = 0
    created_at: datetime | None = None
    updated_at: datetime | None = None


class CreateConversationRequest(BaseModel):
    title: str | None = Field(default=None, max_length=200)
    brand_id: UUID | None = None
    context_ref: dict[str, Any] | None = None


class MessageView(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: UUID
    role: str
    content: dict[str, Any]
    run_id: UUID | None = None
    created_at: datetime | None = None


class AgentView(BaseModel):
    id: str
    name: str
    description: str
    tier: str
    tools: list[str]
    actions: dict[str, Any]
    limits: dict[str, Any]
    enabled: bool = True
    prompt_version: int | None = None


class SettingsUpdate(BaseModel):
    routing: dict[str, Any] | None = None
    providers: dict[str, Any] | None = None
    media: dict[str, Any] | None = None
    search: dict[str, Any] | None = None
    safety: dict[str, Any] | None = None
    budgets: dict[str, Any] | None = None


class PromptView(BaseModel):
    agent_id: str
    action: str | None = None
    version: int
    body: str
    source: str
    template_id: str | None = None
    variables: list[str] = []
    versions: list[dict[str, Any]] = []


class PromptUpdate(BaseModel):
    body: str = Field(min_length=20, max_length=60000)
    action: str | None = None
    model_hints: dict[str, Any] | None = None
    activate_version: int | None = None


class ProviderKeyRequest(BaseModel):
    api_key: str = Field(min_length=8, max_length=512)


class ProviderTestRequest(BaseModel):
    model: str | None = None


class ResumeRequest(BaseModel):
    resume_from: str | None = None

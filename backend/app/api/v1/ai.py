"""/ai routes (doc 17 AI section): runs, conversations, settings, agents, usage, prompts, provider keys."""
from __future__ import annotations

from datetime import datetime
from typing import Annotated, Any
from uuid import UUID

from fastapi import APIRouter, Depends, Query
from sqlalchemy import select

from app.agents.orchestrator.service import AIService
from app.agents.registry import list_specs
from app.api.deps import DB, CurrentMember, require_role
from app.core.pagination import Page
from app.models.ai import AIAgent
from app.schemas.ai import (
    AgentView,
    ConversationView,
    CreateConversationRequest,
    CreateRunRequest,
    CreateRunResponse,
    MessageView,
    PromptUpdate,
    PromptView,
    ProviderKeyRequest,
    ProviderTestRequest,
    ResumeRequest,
    RunListItem,
    RunView,
    SettingsUpdate,
    ToolCallView,
)
from app.services.ai_settings_service import AISettingsService

try:  # consumers register when the API process imports this router
    import app.events.consumers_ai  # noqa: F401
except Exception:  # noqa: BLE001
    pass

router = APIRouter(prefix="/ai", tags=["ai"])
svc = AIService()
settings_svc = AISettingsService()
Editor = Annotated[Any, Depends(require_role("approver"))]      # owner/admin/editor/approver may run AI (doc 00 §4)
Admin = Annotated[Any, Depends(require_role("admin"))]


# ----------------------------------------------------------------------------- runs

@router.post("/runs", response_model=CreateRunResponse, status_code=202)
async def create_run(body: CreateRunRequest, db: DB, member: Editor):
    run = await svc.create_run(db, member, message=body.message, brand_id=body.brand_id, conversation_id=body.conversation_id,
                               mode=body.mode, agent=body.agent, action=body.action, inputs=body.inputs, budget_usd=body.budget_usd)
    return CreateRunResponse(run_id=run.id, conversation_id=run.conversation_id, status=run.status.value,
                             status_url=f"/api/v1/ai/runs/{run.id}")


@router.get("/runs", response_model=Page[RunListItem])
async def list_runs(db: DB, member: CurrentMember, limit: int = Query(25, ge=1, le=100), cursor: str | None = None,
                    status: str | None = None, brand_id: UUID | None = None, mode: str | None = None):
    rows, nxt = await svc.list_runs(db, member.workspace_id, limit=limit, cursor=cursor, status=status, brand_id=brand_id, mode=mode)
    return Page(items=[RunListItem(id=r.id, status=r.status.value, mode=r.mode, brand_id=r.brand_id, conversation_id=r.conversation_id,
                                   message=(r.input or {}).get("message"), cost_usd=float(r.cost_usd or 0), error=r.error,
                                   created_at=r.created_at, finished_at=r.finished_at) for r in rows], next_cursor=nxt)


@router.get("/runs/{run_id}", response_model=RunView)
async def get_run(run_id: UUID, db: DB, member: CurrentMember, include_outputs: bool = False):
    run = await svc.get_run(db, member.workspace_id, run_id)
    return svc.run_view(run, include_outputs=include_outputs)


@router.post("/runs/{run_id}/cancel", status_code=202)
async def cancel_run(run_id: UUID, db: DB, member: Editor):
    run = await svc.cancel_run(db, member, run_id)
    return {"run_id": run.id, "status": run.status.value, "cancel_requested": True}


@router.post("/runs/{run_id}/resume", status_code=202)
async def resume_run(run_id: UUID, db: DB, member: Editor, body: ResumeRequest | None = None):
    run = await svc.resume_run(db, member, run_id, resume_from=body.resume_from if body else None)
    return {"run_id": run.id, "status": run.status.value}


@router.get("/runs/{run_id}/steps")
async def run_steps(run_id: UUID, db: DB, member: CurrentMember):
    run = await svc.get_run(db, member.workspace_id, run_id)
    return {"items": await svc.steps_view(db, run)}


@router.get("/runs/{run_id}/tool-calls", response_model=Page[ToolCallView])
async def run_tool_calls(run_id: UUID, db: DB, member: CurrentMember, limit: int = Query(50, ge=1, le=200), cursor: str | None = None):
    run = await svc.get_run(db, member.workspace_id, run_id)
    items, nxt = await svc.tool_calls_view(db, run, limit=limit, cursor=cursor)
    return Page(items=[ToolCallView(**i) for i in items], next_cursor=nxt)


# ----------------------------------------------------------------------------- conversations

@router.get("/conversations", response_model=Page[ConversationView])
async def list_conversations(db: DB, member: CurrentMember, limit: int = Query(25, ge=1, le=100), cursor: str | None = None,
                             brand_id: UUID | None = None, mine: bool = True):
    rows, nxt = await svc.list_conversations(db, member.workspace_id, user_id=member.user.id if mine else None, brand_id=brand_id,
                                             limit=limit, cursor=cursor)
    counts = await svc.conversation_message_counts(db, [r.id for r in rows])
    return Page(items=[ConversationView(id=r.id, title=r.title, brand_id=r.brand_id, user_id=r.user_id, summary=r.summary,
                                        context_ref=r.context_ref, message_count=counts.get(r.id, 0), created_at=r.created_at,
                                        updated_at=r.updated_at) for r in rows], next_cursor=nxt)


@router.post("/conversations", response_model=ConversationView, status_code=201)
async def create_conversation(body: CreateConversationRequest, db: DB, member: Editor):
    c = await svc.create_conversation(db, member, title=body.title, brand_id=body.brand_id, context_ref=body.context_ref)
    return ConversationView(id=c.id, title=c.title, brand_id=c.brand_id, user_id=c.user_id, summary=c.summary, context_ref=c.context_ref,
                            message_count=0, created_at=c.created_at, updated_at=c.updated_at)


@router.get("/conversations/{conversation_id}/messages", response_model=Page[MessageView])
async def list_messages(conversation_id: UUID, db: DB, member: CurrentMember, limit: int = Query(50, ge=1, le=200),
                        cursor: str | None = None):
    rows, nxt = await svc.list_messages(db, member.workspace_id, conversation_id, limit=limit, cursor=cursor)
    return Page(items=[MessageView.model_validate(r) for r in rows], next_cursor=nxt)


# ----------------------------------------------------------------------------- settings / agents / usage

@router.get("/settings")
async def get_settings(db: DB, member: CurrentMember):
    data = await settings_svc.get(db, member.workspace_id)
    data["provider_status"] = await settings_svc.list_providers(db, member.workspace_id)
    return data


@router.put("/settings")
async def update_settings(body: SettingsUpdate, db: DB, member: Admin):
    patch = {k: v for k, v in body.model_dump().items() if v is not None}
    data = await settings_svc.update(db, member.workspace_id, patch, member=member)
    data["provider_status"] = await settings_svc.list_providers(db, member.workspace_id)
    return data


@router.get("/agents", response_model=list[AgentView])
async def list_agents(db: DB, member: CurrentMember, include_orchestration: bool = False):
    rows = {r.id: r for r in (await db.execute(select(AIAgent))).scalars().all()}
    out = []
    for spec in list_specs(include_orchestration=include_orchestration):
        row = rows.get(spec.id)
        out.append(AgentView(id=spec.id, name=spec.name or spec.id, description=spec.description, tier=spec.tier, tools=list(spec.tools),
                             actions=spec.actions_catalog(), limits=spec.limits(), enabled=bool(row.enabled) if row else True))
    return out


@router.get("/usage")
async def usage(db: DB, member: CurrentMember, from_: datetime | None = Query(None, alias="from"), to: datetime | None = None,
                group_by: str = Query("day", pattern="^(day|agent|model|provider)$")):
    return await settings_svc.usage_summary(db, member.workspace_id, from_, to, group_by)


# ----------------------------------------------------------------------------- prompts

@router.get("/prompts/{agent_id}", response_model=PromptView)
async def get_prompt(agent_id: str, db: DB, member: CurrentMember, action: str | None = None):
    p = await settings_svc.get_prompt(db, member.workspace_id, agent_id, action)
    p["versions"] = await settings_svc.list_prompt_versions(db, member.workspace_id, agent_id)
    return PromptView(**p)


@router.put("/prompts/{agent_id}", response_model=PromptView)
async def put_prompt(agent_id: str, body: PromptUpdate, db: DB, member: Admin):
    if body.activate_version is not None:
        p = await settings_svc.activate_prompt_version(db, member.workspace_id, agent_id, body.activate_version, body.action)
    else:
        p = await settings_svc.set_prompt(db, member.workspace_id, agent_id, body.body, user_id=member.user.id, action=body.action,
                                          model_hints=body.model_hints, member=member)
    p["versions"] = await settings_svc.list_prompt_versions(db, member.workspace_id, agent_id)
    return PromptView(**p)


# ----------------------------------------------------------------------------- providers

@router.post("/providers/{name}/key")
async def set_provider_key(name: str, body: ProviderKeyRequest, db: DB, member: Admin):
    return await settings_svc.set_provider_key(db, member.workspace_id, name, body.api_key, user_id=member.user.id, member=member)


@router.delete("/providers/{name}/key", status_code=204)
async def delete_provider_key(name: str, db: DB, member: Admin):
    await settings_svc.delete_provider_key(db, member.workspace_id, name, member=member)
    return None


@router.post("/providers/{name}/test")
async def test_provider(name: str, db: DB, member: Admin, body: ProviderTestRequest | None = None):
    return await settings_svc.test_provider(db, member.workspace_id, name, body.model if body else None)

"""Workspace settings routes: workspace settings, budgets, API keys, export (stub)."""
from __future__ import annotations

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Request, Response

from app.api.deps import DB, CurrentMember, Member, require_role
from app.core.errors import not_found
from app.core.ids import new_id
from app.schemas.identity import (
    ApiKeyCreate,
    ApiKeyCreated,
    ApiKeyOut,
    BudgetOut,
    BudgetsUpdate,
    ExportAccepted,
    WorkspaceSettingsOut,
    WorkspaceSettingsUpdate,
)
from app.services.audit_service import audit
from app.services.workspace_service import WorkspaceService

router = APIRouter(prefix="/settings", tags=["settings"])
Admin = Annotated[Member, Depends(require_role("admin"))]


@router.get("/workspace", response_model=WorkspaceSettingsOut)
async def get_workspace_settings(member: CurrentMember, db: DB) -> WorkspaceSettingsOut:
    ws = await WorkspaceService.get(db, member.workspace_id)
    return WorkspaceSettingsOut.model_validate(WorkspaceService.settings_view(ws))


@router.put("/workspace", response_model=WorkspaceSettingsOut)
async def put_workspace_settings(body: WorkspaceSettingsUpdate, member: Admin, request: Request, db: DB) -> WorkspaceSettingsOut:
    ws = await WorkspaceService.update_settings(db, member, body, request=request)
    await db.commit()
    return WorkspaceSettingsOut.model_validate(WorkspaceService.settings_view(ws))


@router.get("/budgets", response_model=list[BudgetOut])
async def get_budgets(member: CurrentMember, db: DB) -> list[BudgetOut]:
    return [BudgetOut.model_validate(b) for b in await WorkspaceService.list_budgets(db, member.workspace_id)]


@router.put("/budgets", response_model=list[BudgetOut])
async def put_budgets(body: BudgetsUpdate, member: Admin, request: Request, db: DB) -> list[BudgetOut]:
    rows = await WorkspaceService.update_budgets(db, member, body.budgets, request=request)
    await db.commit()
    return [BudgetOut.model_validate(b) for b in rows]


@router.get("/api-keys", response_model=list[ApiKeyOut])
async def list_api_keys(member: Admin, db: DB) -> list[ApiKeyOut]:
    return [ApiKeyOut.model_validate(k) for k in await WorkspaceService.list_api_keys(db, member.workspace_id)]


@router.post("/api-keys", response_model=ApiKeyCreated, status_code=201)
async def create_api_key(body: ApiKeyCreate, member: Admin, request: Request, db: DB) -> ApiKeyCreated:
    key, secret = await WorkspaceService.create_api_key(db, member, body.name, body.scopes, body.expires_at, request=request)
    await db.commit()
    return ApiKeyCreated.model_validate({**ApiKeyOut.model_validate(key).model_dump(), "secret": secret})


@router.delete("/api-keys/{key_id}", status_code=204)
async def revoke_api_key(key_id: UUID, member: Admin, request: Request, db: DB) -> Response:
    await WorkspaceService.revoke_api_key(db, member, key_id, request=request)
    await db.commit()
    return Response(status_code=204)


@router.post("/export", response_model=ExportAccepted, status_code=202)
async def request_export(member: Admin, request: Request, db: DB) -> ExportAccepted:
    """Workspace export/backup — stub: records the request (audit) but does not enqueue a job yet."""
    export_id = new_id()
    await audit(db, member, "workspace.export_requested", "export", export_id, request=request)
    await db.commit()
    return ExportAccepted(id=export_id, status="queued", status_url=f"/api/v1/settings/exports/{export_id}")


@router.get("/exports/{export_id}")
async def get_export(export_id: UUID, member: Admin) -> None:
    raise not_found("Export")

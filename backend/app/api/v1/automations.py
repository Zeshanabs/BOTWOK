"""Automations API (doc 17 "Automations", doc 14). Thin: validate → AutomationEngine → schema.

Roles: admins/owners create, edit, enable/disable and delete workflows; editors (and above) may run and cancel runs;
every member can read. ``POST /automations/{id}/webhook/{secret}`` is public (secret compared in constant time).
"""
from __future__ import annotations

import json
from typing import Annotated, Any
from uuid import UUID

from fastapi import APIRouter, Depends, Query, Request, Response, status
from sqlalchemy import select

from app.api.deps import DB, CurrentMember, Member, require_role
from app.config import settings
from app.core.db import set_workspace
from app.core.errors import ProblemError, not_found, validation
from app.models.platform import AutomationWorkflow, WorkflowNode
from app.schemas.automations import (
    FromTemplateRequest,
    RunAccepted,
    RunDetail,
    RunOut,
    RunPage,
    RunRequest,
    StepOut,
    WebhookAccepted,
    WorkflowCreate,
    WorkflowOut,
    WorkflowPage,
    WorkflowSummary,
    WorkflowUpdate,
)
from app.workflows import templates as tpl
from app.workflows.catalog import catalog
from app.workflows.engine import AutomationEngine
from app.workflows.validation import schema_errors

router = APIRouter(prefix="/automations", tags=["automations"])
Admin = Annotated[Member, Depends(require_role("admin"))]
Editor = Annotated[Member, Depends(require_role("editor"))]
MAX_WEBHOOK_BODY = 256 * 1024


async def _out(db: DB, member: Member, wf: AutomationWorkflow) -> WorkflowOut:
    nodes, edges = await AutomationEngine.definition(db, wf)
    data = WorkflowSummary.model_validate(wf).model_dump()
    data["settings"] = {k: v for k, v in (wf.settings or {}).items() if not k.startswith("_")}
    out = WorkflowOut(**data, nodes=nodes, edges=edges)
    if member.has("admin"):
        types = {n["type"] for n in nodes}
        if "trigger.webhook" in types:
            out.webhook_url = (f"{settings.public_base_url.rstrip('/')}/api/v1/automations/{wf.id}/webhook/"
                               f"{AutomationEngine.webhook_secret(wf)}")
        if "webhook" in types:
            out.signing_secret = AutomationEngine.signing_secret(wf)
    return out


def _summary(wf: AutomationWorkflow) -> WorkflowSummary:
    s = WorkflowSummary.model_validate(wf)
    s.settings = {k: v for k, v in (wf.settings or {}).items() if not k.startswith("_")}
    return s


def _run_out(run: Any) -> RunOut:
    return RunOut.model_validate(run).model_copy(update={"status": getattr(run.status, "value", run.status),
                                                         "cost_usd": float(run.cost_usd or 0)})


async def _run_detail(db: DB, run: Any) -> RunDetail:
    snap = (run.context or {}).get("_workflow") or {}
    meta = {n["key"]: n for n in snap.get("nodes") or []}
    steps = []
    for s in await AutomationEngine.steps(db, run):
        n = meta.get(s.node_key) or {}
        dur = int((s.finished_at - s.started_at).total_seconds() * 1000) if s.finished_at and s.started_at else None
        steps.append(StepOut(id=s.id, node_key=s.node_key, node_type=n.get("type"), label=n.get("label"), status=s.status,
                             input=s.input, output=s.output, ai_run_id=s.ai_run_id, attempts=s.attempts or 0,
                             error=s.error, started_at=s.started_at, finished_at=s.finished_at, duration_ms=dur))
    context = {k: v for k, v in (run.context or {}).items() if not k.startswith("_")}
    return RunDetail(**_run_out(run).model_dump(), context=context, steps=steps)


def _definition(body: WorkflowCreate | WorkflowUpdate) -> dict[str, Any]:
    d: dict[str, Any] = {"nodes": [n.model_dump() for n in body.nodes],
                         "edges": [e.model_dump(by_alias=True) for e in body.edges]}
    for f in ("name", "description", "autonomous_actions_enabled"):
        v = getattr(body, f)
        if v is not None:
            d[f] = v
    if "brand_id" in body.model_fields_set:
        d["brand_id"] = body.brand_id
    if body.settings is not None:
        d["settings"] = body.settings.model_dump(exclude_none=True)
    return d


# ---------------------------------------------------------------------------------------------- catalog / templates
@router.get("/node-types")
async def node_types(member: CurrentMember) -> list[dict[str, Any]]:
    return catalog()


@router.get("/templates")
async def templates(member: CurrentMember) -> list[dict[str, Any]]:
    return tpl.list_templates()


@router.post("/from-template/{key}", response_model=WorkflowOut, status_code=status.HTTP_201_CREATED)
async def from_template(key: str, db: DB, member: Admin, body: FromTemplateRequest | None = None) -> WorkflowOut:
    body = body or FromTemplateRequest()
    try:
        d = tpl.instantiate(key, body.params)
    except KeyError as e:
        raise not_found("Template") from e
    if d["requires_autonomous_actions"] and body.autonomous_actions_enabled is not True:
        raise validation("This template schedules or publishes content: pass autonomous_actions_enabled=true to confirm "
                         "(an admin decision; content still requires human approval)",
                         [{"node_key": None, "code": "autonomous_actions_disabled",
                           "message": "template requires autonomous_actions_enabled=true"}])
    definition = {"name": body.name or d["name"], "description": d["description"], "nodes": d["nodes"], "edges": d["edges"],
                  "settings": d["settings"], "brand_id": body.brand_id,
                  "autonomous_actions_enabled": bool(body.autonomous_actions_enabled)}
    wf = await AutomationEngine.save(db, member, None, definition)
    if body.enable:
        wf = await AutomationEngine.enable(db, member, wf.id)
    out = await _out(db, member, wf)
    await db.commit()
    return out


# ---------------------------------------------------------------------------------------------- runs (static paths first)
@router.get("/runs/{run_id}", response_model=RunDetail)
async def get_run(run_id: UUID, db: DB, member: CurrentMember) -> RunDetail:
    run = await AutomationEngine.get_run(db, member.workspace_id, run_id)
    return await _run_detail(db, run)


@router.post("/runs/{run_id}/cancel", response_model=RunDetail)
async def cancel_run(run_id: UUID, db: DB, member: Editor) -> RunDetail:
    run = await AutomationEngine.cancel(db, member, run_id)
    await db.commit()
    await set_workspace(db, member.workspace_id)
    return await _run_detail(db, run)


# ---------------------------------------------------------------------------------------------- workflows
@router.get("", response_model=WorkflowPage)
async def list_workflows(db: DB, member: CurrentMember, brand_id: UUID | None = None, status_: Annotated[str | None, Query(alias="status")] = None,
                         limit: Annotated[int, Query(ge=1, le=200)] = 50, cursor: str | None = None) -> WorkflowPage:
    rows, nxt = await AutomationEngine.list_workflows(db, member.workspace_id, brand_id=brand_id, status=status_,
                                                      limit=limit, cursor=cursor)
    return WorkflowPage(items=[_summary(r) for r in rows], next_cursor=nxt)


@router.post("", response_model=WorkflowOut, status_code=status.HTTP_201_CREATED)
async def create_workflow(body: WorkflowCreate, db: DB, member: Admin) -> WorkflowOut:
    wf = await AutomationEngine.save(db, member, None, _definition(body))
    out = await _out(db, member, wf)
    await db.commit()
    return out


@router.get("/{workflow_id}", response_model=WorkflowOut)
async def get_workflow(workflow_id: UUID, db: DB, member: CurrentMember) -> WorkflowOut:
    wf = await AutomationEngine.get(db, member.workspace_id, workflow_id)
    return await _out(db, member, wf)


@router.put("/{workflow_id}", response_model=WorkflowOut)
async def update_workflow(workflow_id: UUID, body: WorkflowUpdate, db: DB, member: Admin) -> WorkflowOut:
    wf = await AutomationEngine.save(db, member, workflow_id, _definition(body))
    out = await _out(db, member, wf)
    await db.commit()
    return out


@router.delete("/{workflow_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_workflow(workflow_id: UUID, db: DB, member: Admin) -> Response:
    await AutomationEngine.delete(db, member, workflow_id)
    await db.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post("/{workflow_id}/enable", response_model=WorkflowOut)
async def enable(workflow_id: UUID, db: DB, member: Admin) -> WorkflowOut:
    wf = await AutomationEngine.enable(db, member, workflow_id)
    out = await _out(db, member, wf)
    await db.commit()
    return out


@router.post("/{workflow_id}/disable", response_model=WorkflowOut)
async def disable(workflow_id: UUID, db: DB, member: Admin) -> WorkflowOut:
    wf = await AutomationEngine.disable(db, member, workflow_id)
    out = await _out(db, member, wf)
    await db.commit()
    return out


@router.post("/{workflow_id}/run", response_model=RunAccepted, status_code=status.HTTP_202_ACCEPTED)
async def run_workflow(workflow_id: UUID, db: DB, member: Editor, body: RunRequest | None = None) -> RunAccepted:
    body = body or RunRequest()
    wf = await AutomationEngine.get(db, member.workspace_id, workflow_id)
    run = await AutomationEngine.start(db, wf, "manual", body.payload, dry_run=body.dry_run, user_id=member.user.id)
    try:
        from app.services.audit_service import audit
        await audit(db, member, "automation.run", "automation_run", run.id, after={"workflow_id": str(wf.id),
                                                                                 "dry_run": body.dry_run})
        await db.commit()
    except Exception:  # noqa: BLE001 - audit never blocks the run
        await db.rollback()
    return RunAccepted(run_id=run.id, status=getattr(run.status, "value", run.status), dry_run=run.dry_run,
                       status_url=f"/api/v1/automations/runs/{run.id}")


@router.get("/{workflow_id}/runs", response_model=RunPage)
async def list_runs(workflow_id: UUID, db: DB, member: CurrentMember, status_: Annotated[str | None, Query(alias="status")] = None,
                    limit: Annotated[int, Query(ge=1, le=200)] = 50, cursor: str | None = None) -> RunPage:
    await AutomationEngine.get(db, member.workspace_id, workflow_id)
    rows, nxt = await AutomationEngine.list_runs(db, member.workspace_id, workflow_id, status=status_, limit=limit,
                                                 cursor=cursor)
    return RunPage(items=[_run_out(r) for r in rows], next_cursor=nxt)


# ---------------------------------------------------------------------------------------------- public webhook trigger
@router.post("/{workflow_id}/webhook/{secret}", response_model=WebhookAccepted, status_code=status.HTTP_202_ACCEPTED)
async def webhook_trigger(workflow_id: UUID, secret: str, request: Request, db: DB) -> WebhookAccepted:
    wf = await db.get(AutomationWorkflow, workflow_id)
    # same 404 for unknown workflow, wrong secret or non-webhook trigger: no oracle
    if wf is None or not AutomationEngine.verify_webhook_secret(wf, secret) or wf.status != "active":
        raise not_found("Automation")
    node = (await db.execute(select(WorkflowNode).where(WorkflowNode.workflow_id == wf.id,
                                                        WorkflowNode.type == "trigger.webhook"))).scalar_one_or_none()
    if node is None:
        raise not_found("Automation")
    await set_workspace(db, wf.workspace_id)
    too_large = ProblemError(413, "payload_too_large", "Payload too large", f"max {MAX_WEBHOOK_BODY} bytes")
    declared = request.headers.get("content-length", "")
    if declared.isdigit() and int(declared) > MAX_WEBHOOK_BODY:
        raise too_large
    buf = bytearray()
    async for chunk in request.stream():
        buf.extend(chunk)
        if len(buf) > MAX_WEBHOOK_BODY:
            raise too_large
    raw = bytes(buf)
    try:
        body = json.loads(raw) if raw else {}
    except ValueError as e:
        raise validation("body must be JSON") from e
    schema = (node.config or {}).get("schema")
    if isinstance(schema, dict) and schema:
        errs = schema_errors(body, schema, "body", allow_templates=False)
        if errs:
            raise validation("body does not match the webhook schema",
                             [{"node_key": node.key, "message": m, "code": "invalid_body"} for m in errs])
    run = await AutomationEngine.start(db, wf, "webhook", body if isinstance(body, dict) else {"body": body},
                                       trigger_extra={"body": body})
    return WebhookAccepted(run_id=run.id, status=getattr(run.status, "value", run.status))

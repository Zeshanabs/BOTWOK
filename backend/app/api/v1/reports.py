"""Reports API (doc 13 §13.6, doc 17, doc 24): list, create (async generation), get, export, delete."""
from __future__ import annotations

from typing import Annotated, Literal
from uuid import UUID

from fastapi import APIRouter, Depends, Query, Response, status

from app.api.deps import DB, CurrentMember, Member, require_role
from app.core.pagination import Page
from app.schemas.reports import (
    ReportCreatedOut,
    ReportCreateIn,
    ReportKind,
    ReportListItem,
    ReportOut,
    report_view,
)
from app.services.report_service import ReportService

router = APIRouter(prefix="/reports", tags=["reports"])
Editor = Annotated[Member, Depends(require_role("editor"))]


@router.get("", response_model=Page[ReportListItem])
async def list_reports(db: DB, member: CurrentMember, brand_id: UUID | None = None, kind: ReportKind | None = None,
                       status_: Annotated[Literal["generating", "ready", "failed"] | None, Query(alias="status")] = None,
                       limit: Annotated[int, Query(ge=1, le=200)] = 50, cursor: str | None = None):
    rows, nxt = await ReportService.list(db, member.workspace_id, brand_id=brand_id, kind=kind, status=status_, limit=limit,
                                         cursor=cursor)
    return Page[ReportListItem](items=[ReportListItem.model_validate(report_view(r, detail=False)) for r in rows],
                                next_cursor=nxt)


@router.post("", response_model=ReportCreatedOut, status_code=status.HTTP_202_ACCEPTED)
async def create_report(body: ReportCreateIn, db: DB, member: Editor):
    options = {"audience": body.audience, "length": body.length, "instructions": body.instructions,
               "campaign_ids": [str(c) for c in body.campaign_ids]}
    report = await ReportService.create(db, member, body.kind, body.brand_id, body.period_start, body.period_end,
                                        recipients=body.recipients, title=body.title, options=options, use_ai=body.use_ai)
    out = ReportCreatedOut.model_validate({**report_view(report), "report_id": report.id, "run_id": report.ai_run_id,
                                           "status_url": f"/api/v1/reports/{report.id}"})
    await db.commit()
    return out


@router.get("/{report_id}", response_model=ReportOut)
async def get_report(report_id: UUID, db: DB, member: CurrentMember):
    return ReportOut.model_validate(report_view(await ReportService.get(db, member.workspace_id, report_id)))


@router.get("/{report_id}/export")
async def export_report(report_id: UUID, db: DB, member: CurrentMember,
                        format: Literal["markdown", "md", "html", "pdf"] = "markdown") -> Response:
    body, media_type, filename = await ReportService.export(db, member, report_id, format)
    return Response(content=body, media_type=media_type,
                    headers={"Content-Disposition": f'attachment; filename="{filename}"'})


@router.delete("/{report_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_report(report_id: UUID, db: DB, member: Editor) -> Response:
    await ReportService.delete(db, member, report_id)
    await db.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)

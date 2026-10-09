"""Approvals API (doc 17 "Approvals"). Thin: validate → ApprovalService → schema."""
from __future__ import annotations

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Query

from app.api.deps import DB, CurrentMember
from app.schemas.content import ApprovalDetail, ApprovalOut, ApprovalPage, ApproveRequest, RejectRequest
from app.services.approval_service import ApprovalService

router = APIRouter(prefix="/approvals", tags=["approvals"])


@router.get("", response_model=ApprovalPage)
async def list_approvals(db: DB, member: CurrentMember,
                         status_: Annotated[list[str] | None, Query(alias="status")] = None,
                         brand_id: UUID | None = None, kind: str | None = None, target_id: UUID | None = None,
                         limit: Annotated[int, Query(ge=1, le=200)] = 50, cursor: str | None = None) -> ApprovalPage:
    rows, nxt = await ApprovalService.list(db, member, status=status_ or ["pending"], brand_id=brand_id, kind=kind,
                                           target_id=target_id, limit=limit, cursor=cursor)
    return ApprovalPage(items=[ApprovalOut.model_validate(r) for r in rows], next_cursor=nxt)


async def _detail(db: DB, member: CurrentMember, approval_id: UUID) -> ApprovalDetail:
    ap = await ApprovalService.get(db, member.workspace_id, approval_id)
    data = ApprovalOut.model_validate(ap).model_dump()
    data["target"] = await ApprovalService.preview(db, ap)
    return ApprovalDetail.model_validate(data)


@router.get("/{approval_id}", response_model=ApprovalDetail)
async def get_approval(approval_id: UUID, db: DB, member: CurrentMember) -> ApprovalDetail:
    return await _detail(db, member, approval_id)


@router.post("/{approval_id}/approve", response_model=ApprovalOut)
async def approve(approval_id: UUID, db: DB, member: CurrentMember, body: ApproveRequest | None = None) -> ApprovalOut:
    ap = await ApprovalService.approve(db, member, approval_id, body.comment if body else None)
    out = ApprovalOut.model_validate(ap)
    await db.commit()
    return out


@router.post("/{approval_id}/reject", response_model=ApprovalOut)
async def reject(approval_id: UUID, body: RejectRequest, db: DB, member: CurrentMember) -> ApprovalOut:
    ap = await ApprovalService.reject(db, member, approval_id, body.comment, body.decision)
    out = ApprovalOut.model_validate(ap)
    await db.commit()
    return out

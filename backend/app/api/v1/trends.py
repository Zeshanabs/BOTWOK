"""Trends API: list/get trends, run a deterministic scan."""
from __future__ import annotations

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Query

from app.api.deps import DB, CurrentMember, Member, require_role
from app.schemas.trends import SignalOut, TrendDetail, TrendOut, TrendScanRequest
from app.services.trend_service import TrendService

router = APIRouter(prefix="/trends", tags=["trends"])
Editor = Annotated[Member, Depends(require_role("editor"))]


@router.get("", response_model=list[TrendOut])
async def list_trends(db: DB, member: CurrentMember, brand_id: UUID | None = None,
                      status_: Annotated[str | None, Query(alias="status")] = None,
                      limit: Annotated[int, Query(ge=1, le=200)] = 50) -> list[TrendOut]:
    rows = await TrendService.list(db, member.workspace_id, brand_id=brand_id, status=status_, limit=limit)
    return [TrendOut.model_validate(r) for r in rows]


@router.post("/scan")
async def scan(body: TrendScanRequest, db: DB, member: Editor) -> dict:
    actor = {"type": "user", "id": str(member.user.id)}
    res = await TrendService.scan(db, member.workspace_id, body.brand_id, window_days=body.window_days, actor=actor)
    await db.commit()
    return res


@router.get("/{trend_id}", response_model=TrendDetail)
async def get_trend(trend_id: UUID, db: DB, member: CurrentMember) -> TrendDetail:
    trend, signals = await TrendService.get(db, member.workspace_id, trend_id)
    out = TrendDetail.model_validate(trend)
    out.signals = [SignalOut.model_validate(s) for s in signals]
    return out

"""Calendar API (doc 12 §12.8): aggregated cards for a window plus the unscheduled approved tray."""
from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Query

from app.api.deps import DB, CurrentMember
from app.schemas.scheduling import CalendarOut
from app.services.scheduling_service import SchedulingService

router = APIRouter(prefix="/calendar", tags=["calendar"])
svc = SchedulingService()


@router.get("", response_model=CalendarOut, response_model_by_alias=True)
async def calendar(db: DB, member: CurrentMember, from_: Annotated[datetime | None, Query(alias="from")] = None, to: datetime | None = None,
                   view: str = "month", brand_id: UUID | None = None, platform: Annotated[list[str] | None, Query()] = None,
                   status: Annotated[list[str] | None, Query()] = None, campaign: UUID | None = None, pillar: UUID | None = None,
                   member_id: Annotated[UUID | None, Query(alias="member")] = None, approval: str | None = None, tray: bool = True):
    now = datetime.now(UTC)
    if from_ is None:
        from_ = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0) if view == "month" else now - timedelta(days=7)
    if to is None:
        to = from_ + timedelta(days={"day": 1, "week": 7, "list": 30, "board": 30}.get(view, 35))
    res = await svc.calendar(db, member.workspace_id, from_, to, brand_id=brand_id, platform=platform, status=status, campaign=campaign, pillar=pillar,
                             member=member_id, approval=approval, include_tray=tray)
    return CalendarOut.model_validate(res)

"""Competitors API (doc 17 §17.2 Competitors, doc 08). Thin: validate → CompetitorService → schema."""
from __future__ import annotations

from datetime import datetime
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Query, Response, status

from app.api.deps import DB, CurrentMember, Member, require_role
from app.core.errors import validation
from app.schemas.competitors import (
    CompareOut,
    CompetitorCreate,
    CompetitorOut,
    CompetitorUpdate,
    PostOut,
    ReportCreate,
    ReportOut,
    SnapshotOut,
    SyncAccepted,
)
from app.services.competitor_service import CompetitorService

router = APIRouter(prefix="/competitors", tags=["competitors"])
Editor = Annotated[Member, Depends(require_role("editor"))]


def _parse_period(period: str | None, default: int = 90) -> int:
    if not period:
        return default
    p = period.strip().lower()
    try:
        if p.endswith("d"):
            return max(1, min(365, int(p[:-1])))
        if p.endswith("w"):
            return max(1, min(365, int(p[:-1]) * 7))
        return max(1, min(365, int(p)))
    except ValueError as e:
        raise validation("period must look like 30d, 12w or 90") from e


@router.get("", response_model=list[CompetitorOut])
async def list_competitors(db: DB, member: CurrentMember, brand_id: UUID | None = None,
                           status_: Annotated[str | None, Query(alias="status")] = None) -> list[CompetitorOut]:
    rows = await CompetitorService.list(db, member.workspace_id, brand_id=brand_id, status=status_)
    return [CompetitorOut.model_validate(r) for r in rows]


@router.post("", response_model=CompetitorOut, status_code=status.HTTP_201_CREATED)
async def create_competitor(body: CompetitorCreate, db: DB, member: Editor) -> CompetitorOut:
    comp = await CompetitorService.create(db, member, body)
    out = CompetitorOut.model_validate(comp)
    await db.commit()
    if body.sync_now:
        await CompetitorService.request_sync(db, member.workspace_id, comp.id)
        await db.commit()
    return out


@router.get("/compare", response_model=CompareOut)
async def compare(db: DB, member: CurrentMember, ids: str, period: str | None = "90d") -> CompareOut:
    try:
        id_list = [UUID(x.strip()) for x in ids.split(",") if x.strip()]
    except ValueError as e:
        raise validation("ids must be a comma-separated list of UUIDs") from e
    if not id_list or len(id_list) > 10:
        raise validation("between 1 and 10 ids are required")
    return CompareOut.model_validate(await CompetitorService.compare(db, member.workspace_id, id_list,
                                                                     period_days=_parse_period(period)))


@router.get("/topic-clusters")
async def topic_clusters(db: DB, member: CurrentMember, brand_id: UUID, ids: str | None = None,
                         days: Annotated[int, Query(ge=7, le=365)] = 90) -> dict:
    try:
        id_list = [UUID(x.strip()) for x in (ids or "").split(",") if x.strip()]
    except ValueError as e:
        raise validation("ids must be UUIDs") from e
    return await CompetitorService.topic_clusters(db, member.workspace_id, brand_id, id_list or None, days=days)


@router.get("/{competitor_id}", response_model=CompetitorOut)
async def get_competitor(competitor_id: UUID, db: DB, member: CurrentMember) -> CompetitorOut:
    return CompetitorOut.model_validate(await CompetitorService.get(db, member.workspace_id, competitor_id))


@router.patch("/{competitor_id}", response_model=CompetitorOut)
async def update_competitor(competitor_id: UUID, body: CompetitorUpdate, db: DB, member: Editor) -> CompetitorOut:
    comp = await CompetitorService.update(db, member, competitor_id, body)
    out = CompetitorOut.model_validate(comp)
    await db.commit()
    return out


@router.delete("/{competitor_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_competitor(competitor_id: UUID, db: DB, member: Editor) -> Response:
    await CompetitorService.delete(db, member, competitor_id)
    await db.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post("/{competitor_id}/sync", response_model=SyncAccepted, status_code=status.HTTP_202_ACCEPTED)
async def sync_competitor(competitor_id: UUID, db: DB, member: Editor) -> SyncAccepted:
    job_ids, profile_ids = await CompetitorService.request_sync(db, member.workspace_id, competitor_id)
    await db.commit()
    return SyncAccepted(competitor_id=competitor_id, job_ids=job_ids, profiles=profile_ids,
                        status="queued" if profile_ids else "nothing_to_sync")


@router.get("/{competitor_id}/posts", response_model=list[PostOut])
async def list_posts(competitor_id: UUID, db: DB, member: CurrentMember, profile_id: UUID | None = None,
                     platform: str | None = None, since: datetime | None = None,
                     limit: Annotated[int, Query(ge=1, le=200)] = 50, offset: Annotated[int, Query(ge=0)] = 0) -> list[PostOut]:
    rows = await CompetitorService.list_posts(db, member.workspace_id, competitor_id, profile_id=profile_id,
                                              platform=platform, since=since, limit=limit, offset=offset)
    return [PostOut.model_validate(r) for r in rows]


@router.get("/{competitor_id}/snapshots", response_model=list[SnapshotOut])
async def list_snapshots(competitor_id: UUID, db: DB, member: CurrentMember, profile_id: UUID | None = None,
                         limit: Annotated[int, Query(ge=1, le=200)] = 50) -> list[SnapshotOut]:
    rows = await CompetitorService.list_snapshots(db, member.workspace_id, competitor_id, profile_id=profile_id, limit=limit)
    return [SnapshotOut.model_validate(r) for r in rows]


@router.get("/{competitor_id}/stats")
async def describe(competitor_id: UUID, db: DB, member: CurrentMember,
                   days: Annotated[int, Query(ge=7, le=365)] = 90) -> dict:
    comp = await CompetitorService.get(db, member.workspace_id, competitor_id)
    return {"competitor_id": str(comp.id),
            "profiles": [await CompetitorService.describe(db, p.id, days=days) for p in comp.profiles]}


@router.get("/{competitor_id}/reports", response_model=list[ReportOut])
async def list_reports(competitor_id: UUID, db: DB, member: CurrentMember) -> list[ReportOut]:
    rows = await CompetitorService.list_reports(db, member.workspace_id, competitor_id)
    return [ReportOut.model_validate(r) for r in rows]


@router.post("/{competitor_id}/reports", response_model=ReportOut, status_code=status.HTTP_202_ACCEPTED)
async def create_report(competitor_id: UUID, body: ReportCreate, db: DB, member: Editor) -> ReportOut:
    report = await CompetitorService.create_report(db, member, competitor_id, body)
    out = ReportOut.model_validate(report)
    await db.commit()
    return out

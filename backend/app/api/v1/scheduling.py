"""Scheduling API (doc 17 "Scheduling & publishing"): posts CRUD + pause/resume/cancel, best-times, recurring."""
from __future__ import annotations

from datetime import datetime
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Query, Response, status

from app.api.deps import DB, CurrentMember, Member, require_role
from app.models.identity import User
from app.models.social import SocialAccount
from app.schemas.scheduling import (
    BestTimesIn,
    BestTimesOut,
    RecurringCreate,
    RecurringOut,
    ResumeIn,
    ScheduleCreate,
    ScheduledPostOut,
    ScheduleUpdate,
)
from app.services.scheduling_service import SchedulingService, serialize_scheduled_post

router = APIRouter(prefix="/scheduling", tags=["scheduling"])
Editor = Annotated[Member, Depends(require_role("editor"))]
svc = SchedulingService()


async def _out(db: DB, sp) -> ScheduledPostOut:
    account = await db.get(SocialAccount, sp.social_account_id)
    creator = await db.get(User, sp.created_by)
    await db.refresh(sp, ["attempts"])
    return ScheduledPostOut.model_validate(serialize_scheduled_post(sp, account, creator))


@router.get("/posts", response_model=list[ScheduledPostOut])
async def list_posts(db: DB, member: CurrentMember, brand_id: UUID | None = None,
                     status_: Annotated[list[str] | None, Query(alias="status")] = None, platform: str | None = None,
                     social_account_id: UUID | None = None, since: datetime | None = None, until: datetime | None = None,
                     limit: Annotated[int, Query(ge=1, le=500)] = 200, offset: int = 0):
    rows = await svc.list(db, member.workspace_id, brand_id=brand_id, status=status_, platform=platform, social_account_id=social_account_id,
                          since=since, until=until, limit=limit, offset=offset)
    return [await _out(db, sp) for sp in rows]


@router.post("/posts", response_model=ScheduledPostOut, status_code=status.HTTP_201_CREATED)
async def create_post(body: ScheduleCreate, db: DB, member: Editor):
    sp = await svc.schedule(db, member, body.content_variant_id, body.social_account_id, body.scheduled_at, body.timezone, body.priority, force=body.force)
    out = await _out(db, sp)
    await db.commit()
    return out


@router.get("/posts/{post_id}", response_model=ScheduledPostOut)
async def get_post(post_id: UUID, db: DB, member: CurrentMember):
    return await _out(db, await svc.get(db, member.workspace_id, post_id))


@router.patch("/posts/{post_id}", response_model=ScheduledPostOut)
async def update_post(post_id: UUID, body: ScheduleUpdate, db: DB, member: Editor):
    sp = await svc.reschedule(db, member, post_id, scheduled_at=body.scheduled_at, timezone=body.timezone, priority=body.priority)
    out = await _out(db, sp)
    await db.commit()
    return out


@router.delete("/posts/{post_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_post(post_id: UUID, db: DB, member: Editor):
    await svc.cancel(db, member, post_id)
    await db.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post("/posts/{post_id}/pause", response_model=ScheduledPostOut)
async def pause_post(post_id: UUID, db: DB, member: Editor):
    sp = await svc.pause(db, member, post_id)
    out = await _out(db, sp)
    await db.commit()
    return out


@router.post("/posts/{post_id}/resume", response_model=ScheduledPostOut)
async def resume_post(post_id: UUID, db: DB, member: Editor, body: ResumeIn | None = None):
    sp = await svc.resume(db, member, post_id, scheduled_at=body.scheduled_at if body else None)
    out = await _out(db, sp)
    await db.commit()
    return out


@router.post("/posts/{post_id}/cancel", response_model=ScheduledPostOut)
async def cancel_post(post_id: UUID, db: DB, member: Editor):
    sp = await svc.cancel(db, member, post_id)
    out = await _out(db, sp)
    await db.commit()
    return out


@router.post("/best-times", response_model=BestTimesOut)
async def best_times(body: BestTimesIn, db: DB, member: CurrentMember):
    res = await svc.best_times(db, body.brand_id, body.platform, body.social_account_id, body.from_, body.to, body.count, workspace_id=member.workspace_id)
    return BestTimesOut(**res)


@router.get("/recurring", response_model=list[RecurringOut])
async def list_recurring(db: DB, member: CurrentMember, brand_id: UUID | None = None):
    return [RecurringOut.model_validate(r) for r in await svc.list_recurring(db, member.workspace_id, brand_id)]


@router.post("/recurring", response_model=RecurringOut, status_code=status.HTTP_201_CREATED)
async def create_recurring(body: RecurringCreate, db: DB, member: Editor):
    r = await svc.create_recurring(db, member, body.model_dump())
    out = RecurringOut.model_validate(r)
    await db.commit()
    return out

"""Publishing API (doc 17): publish-now, queue, attempts (+retry), published posts (+platform delete)."""
from __future__ import annotations

from datetime import datetime
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Query, status

from app.api.deps import DB, CurrentMember, Member, require_role
from app.models.identity import User
from app.models.social import SocialAccount
from app.schemas.publishing import (
    DeletedOut,
    PublishAttemptOut,
    PublishedPostOut,
    PublishNowIn,
    PublishNowOut,
)
from app.schemas.scheduling import ScheduledPostOut
from app.services.publishing_service import PublishingService
from app.services.scheduling_service import serialize_scheduled_post

router = APIRouter(prefix="/publishing", tags=["publishing"])
Editor = Annotated[Member, Depends(require_role("editor"))]
Admin = Annotated[Member, Depends(require_role("admin"))]
svc = PublishingService()


async def _sp_out(db: DB, sp) -> ScheduledPostOut:
    account = await db.get(SocialAccount, sp.social_account_id)
    creator = await db.get(User, sp.created_by)
    await db.refresh(sp, ["attempts"])
    return ScheduledPostOut.model_validate(serialize_scheduled_post(sp, account, creator))


@router.post("/publish-now", response_model=PublishNowOut, status_code=status.HTTP_202_ACCEPTED)
async def publish_now(body: PublishNowIn, db: DB, member: Editor):
    sp = await svc.publish_now(db, member, body.content_variant_id, body.social_account_id, force=body.force)
    await db.commit()
    return PublishNowOut(scheduled_post_id=str(sp.id), status=sp.status.value)


@router.get("/queue", response_model=list[ScheduledPostOut])
async def queue(db: DB, member: CurrentMember, status_: Annotated[list[str] | None, Query(alias="status")] = None, brand_id: UUID | None = None,
                limit: Annotated[int, Query(ge=1, le=500)] = 200):
    rows = await svc.queue(db, member.workspace_id, status_, brand_id, limit)
    return [await _sp_out(db, sp) for sp in rows]


@router.get("/attempts/{attempt_id}", response_model=PublishAttemptOut)
async def get_attempt(attempt_id: UUID, db: DB, member: CurrentMember):
    return PublishAttemptOut.model_validate(await svc.get_attempt(db, member.workspace_id, attempt_id))


@router.post("/attempts/{attempt_id}/retry", response_model=ScheduledPostOut, status_code=status.HTTP_202_ACCEPTED)
async def retry_attempt(attempt_id: UUID, db: DB, member: Editor):
    sp = await svc.retry_attempt(db, member, attempt_id)
    out = await _sp_out(db, sp)
    await db.commit()
    return out


@router.get("/published", response_model=list[PublishedPostOut])
async def list_published(db: DB, member: CurrentMember, brand_id: UUID | None = None, platform: str | None = None, social_account_id: UUID | None = None,
                         since: datetime | None = None, until: datetime | None = None, include_deleted: bool = False,
                         limit: Annotated[int, Query(ge=1, le=500)] = 100, offset: int = 0):
    rows = await svc.list_published(db, member.workspace_id, brand_id=brand_id, platform=platform, social_account_id=social_account_id, since=since,
                                    until=until, include_deleted=include_deleted, limit=limit, offset=offset)
    return [PublishedPostOut.model_validate(r) for r in rows]


@router.delete("/published/{published_id}", response_model=DeletedOut)
async def delete_published(published_id: UUID, db: DB, member: Admin):
    pp = await svc.delete_published(db, member, published_id)
    await db.commit()
    return DeletedOut(id=str(pp.id), deleted_at=pp.deleted_at.isoformat())

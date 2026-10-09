"""Notification inbox routes."""
from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Query

from app.api.deps import DB, CurrentMember
from app.schemas.identity import NotificationOut, NotificationPage
from app.services.notification_service import NotificationService

router = APIRouter(prefix="/notifications", tags=["notifications"])


@router.get("", response_model=NotificationPage)
async def list_notifications(member: CurrentMember, db: DB, unread: bool = False, cursor: str | None = None,
                             limit: int = Query(default=50, ge=1, le=200)) -> NotificationPage:
    items, nxt, unread_count = await NotificationService.list(db, member.workspace_id, member.user.id, unread_only=unread,
                                                              cursor=cursor, limit=limit)
    return NotificationPage(items=[NotificationOut.model_validate(n) for n in items], next_cursor=nxt, unread_count=unread_count)


@router.post("/read-all")
async def read_all(member: CurrentMember, db: DB) -> dict[str, int]:
    n = await NotificationService.mark_all_read(db, member.workspace_id, member.user.id)
    await db.commit()
    return {"updated": n}


@router.post("/{notification_id}/read", response_model=NotificationOut)
async def mark_read(notification_id: UUID, member: CurrentMember, db: DB) -> NotificationOut:
    n = await NotificationService.mark_read(db, member.workspace_id, member.user.id, notification_id)
    await db.commit()
    return NotificationOut.model_validate(n)

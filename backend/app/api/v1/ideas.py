"""Ideas API (doc 17 "Ideas & content"). Thin: validate → ContentService → schema."""
from __future__ import annotations

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Query, Response, status

from app.api.deps import DB, CurrentMember
from app.schemas.content import (
    ContentItemOut,
    IdeaCreate,
    IdeaGenerateRequest,
    IdeaOut,
    IdeaPage,
    IdeaPromoteRequest,
    IdeaUpdate,
    RunAccepted,
)
from app.services.content_service import ContentService

router = APIRouter(prefix="/ideas", tags=["ideas"])


@router.get("", response_model=IdeaPage)
async def list_ideas(db: DB, member: CurrentMember, brand_id: UUID | None = None, campaign_id: UUID | None = None,
                     status_: Annotated[list[str] | None, Query(alias="status")] = None, q: str | None = None,
                     limit: Annotated[int, Query(ge=1, le=200)] = 50, cursor: str | None = None) -> IdeaPage:
    rows, nxt = await ContentService.list_ideas(db, member, brand_id=brand_id, status=status_, q=q, campaign_id=campaign_id,
                                                limit=limit, cursor=cursor)
    return IdeaPage(items=[IdeaOut.model_validate(r) for r in rows], next_cursor=nxt)


@router.post("", response_model=IdeaOut, status_code=status.HTTP_201_CREATED)
async def create_idea(body: IdeaCreate, db: DB, member: CurrentMember) -> IdeaOut:
    idea, _dup = await ContentService.create_idea(db, member, body.model_dump(exclude_unset=True))
    out = IdeaOut.model_validate(idea)
    await db.commit()
    return out


@router.post("/generate", response_model=RunAccepted, status_code=status.HTTP_202_ACCEPTED)
async def generate_ideas(body: IdeaGenerateRequest, db: DB, member: CurrentMember) -> RunAccepted:
    res = await ContentService.generate_ideas(
        db, member, brand_id=body.brand_id, count=body.count, pillars=body.pillars,
        platforms=[p.value for p in body.platforms or []],
        from_=body.from_.model_dump(exclude_none=True, mode="json") if body.from_ else None)
    await db.commit()
    return RunAccepted(**res)


@router.patch("/{idea_id}", response_model=IdeaOut)
async def update_idea(idea_id: UUID, body: IdeaUpdate, db: DB, member: CurrentMember) -> IdeaOut:
    idea = await ContentService.update_idea(db, member, idea_id, body.model_dump(exclude_unset=True))
    out = IdeaOut.model_validate(idea)
    await db.commit()
    return out


@router.delete("/{idea_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_idea(idea_id: UUID, db: DB, member: CurrentMember) -> Response:
    await ContentService.delete_idea(db, member, idea_id)
    await db.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post("/{idea_id}/promote", response_model=ContentItemOut, status_code=status.HTTP_201_CREATED)
async def promote_idea(idea_id: UUID, db: DB, member: CurrentMember, body: IdeaPromoteRequest | None = None) -> ContentItemOut:
    item = await ContentService.promote_idea(db, member, idea_id, body.model_dump(exclude_unset=True) if body else None)
    out = ContentItemOut.model_validate(await ContentService.serialize_item(db, item))
    await db.commit()
    return out

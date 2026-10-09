"""Campaigns API (doc 00 §14). Thin: validate → ContentService → schema."""
from __future__ import annotations

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Query, Response, status

from app.api.deps import DB, CurrentMember
from app.schemas.content import CampaignCreate, CampaignOut, CampaignPage, CampaignUpdate
from app.services.content_service import ContentService

router = APIRouter(prefix="/campaigns", tags=["campaigns"])


@router.get("", response_model=CampaignPage)
async def list_campaigns(db: DB, member: CurrentMember, brand_id: UUID | None = None,
                         status_: Annotated[str | None, Query(alias="status")] = None,
                         limit: Annotated[int, Query(ge=1, le=200)] = 100, cursor: str | None = None) -> CampaignPage:
    rows, nxt = await ContentService.list_campaigns(db, member, brand_id=brand_id, status=status_, limit=limit, cursor=cursor)
    return CampaignPage(items=[CampaignOut.model_validate(r) for r in rows], next_cursor=nxt)


@router.post("", response_model=CampaignOut, status_code=status.HTTP_201_CREATED)
async def create_campaign(body: CampaignCreate, db: DB, member: CurrentMember) -> CampaignOut:
    c = await ContentService.create_campaign(db, member, body.model_dump(exclude_unset=True))
    out = CampaignOut.model_validate(c)
    await db.commit()
    return out


@router.get("/{campaign_id}", response_model=CampaignOut)
async def get_campaign(campaign_id: UUID, db: DB, member: CurrentMember) -> CampaignOut:
    return CampaignOut.model_validate(await ContentService.get_campaign(db, member.workspace_id, campaign_id))


@router.patch("/{campaign_id}", response_model=CampaignOut)
async def update_campaign(campaign_id: UUID, body: CampaignUpdate, db: DB, member: CurrentMember) -> CampaignOut:
    c = await ContentService.update_campaign(db, member, campaign_id, body.model_dump(exclude_unset=True))
    out = CampaignOut.model_validate(c)
    await db.commit()
    return out


@router.delete("/{campaign_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_campaign(campaign_id: UUID, db: DB, member: CurrentMember) -> Response:
    await ContentService.delete_campaign(db, member, campaign_id)
    await db.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)

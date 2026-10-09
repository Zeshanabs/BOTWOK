"""Content API (doc 17 "Ideas & content"). Thin: validate → ContentService → schema."""
from __future__ import annotations

from typing import Annotated, Literal
from uuid import UUID

from fastapi import APIRouter, Query, Response, status

from app.api.deps import DB, CurrentMember
from app.schemas.content import (
    ApprovalOut,
    AssetAttachRequest,
    AssetOut,
    ContentCreate,
    ContentItemOut,
    ContentListItem,
    ContentPage,
    ContentUpdate,
    CritiqueRequest,
    GenerateRequest,
    RepurposeRequest,
    RequestApprovalRequest,
    RunAccepted,
    TransitionRequest,
    VariantCreate,
    VariantOut,
    VariantUpdate,
    VersionOut,
)
from app.services.content_service import ContentService, _asset_dict

router = APIRouter(prefix="/content", tags=["content"])


async def _item_out(db: DB, member: CurrentMember, item_id: UUID) -> ContentItemOut:
    item = await ContentService.get_item(db, member.workspace_id, item_id)
    return ContentItemOut.model_validate(await ContentService.serialize_item(db, item))


@router.get("", response_model=ContentPage)
async def list_content(db: DB, member: CurrentMember, brand_id: UUID | None = None,
                       status_: Annotated[list[str] | None, Query(alias="status")] = None,
                       pillar_id: UUID | None = None, campaign_id: UUID | None = None,
                       platform: Annotated[list[str] | None, Query()] = None, q: str | None = None,
                       assignee: UUID | None = None, ai_generated: bool | None = None,
                       limit: Annotated[int, Query(ge=1, le=200)] = 50, cursor: str | None = None) -> ContentPage:
    rows, nxt = await ContentService.list_items(db, member, brand_id=brand_id, status=status_, pillar_id=pillar_id,
                                                campaign_id=campaign_id, platform=platform, q=q, assignee=assignee,
                                                ai_generated=ai_generated, limit=limit, cursor=cursor)
    items = [ContentListItem.model_validate(await ContentService.serialize_item(db, r, full=False)) for r in rows]
    return ContentPage(items=items, next_cursor=nxt)


@router.post("", response_model=ContentItemOut, status_code=status.HTTP_201_CREATED)
async def create_content(body: ContentCreate, db: DB, member: CurrentMember) -> ContentItemOut:
    item = await ContentService.create_item(db, member, body.model_dump(exclude_unset=True))
    out = ContentItemOut.model_validate(await ContentService.serialize_item(db, item))
    await db.commit()
    return out


@router.get("/{content_id}", response_model=ContentItemOut)
async def get_content(content_id: UUID, db: DB, member: CurrentMember) -> ContentItemOut:
    return await _item_out(db, member, content_id)


@router.patch("/{content_id}", response_model=ContentItemOut)
async def update_content(content_id: UUID, body: ContentUpdate, db: DB, member: CurrentMember) -> ContentItemOut:
    await ContentService.update_item(db, member, content_id, body.model_dump(exclude_unset=True))
    out = await _item_out(db, member, content_id)
    await db.commit()
    return out


@router.delete("/{content_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_content(content_id: UUID, db: DB, member: CurrentMember) -> Response:
    await ContentService.delete_item(db, member, content_id)
    await db.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)


# ── AI entry points (202 + run id; progress via SSE) ────────────────────────────

@router.post("/{content_id}/generate", response_model=RunAccepted, status_code=status.HTTP_202_ACCEPTED)
async def generate(content_id: UUID, body: GenerateRequest, db: DB, member: CurrentMember) -> RunAccepted:
    res = await ContentService.generate(db, member, content_id, body.model_dump(mode="json"))
    await db.commit()
    return RunAccepted(**res)


@router.post("/{content_id}/repurpose", response_model=RunAccepted, status_code=status.HTTP_202_ACCEPTED)
async def repurpose(content_id: UUID, body: RepurposeRequest, db: DB, member: CurrentMember) -> RunAccepted:
    res = await ContentService.repurpose(db, member, content_id, [t.model_dump(mode="json") for t in body.targets])
    await db.commit()
    return RunAccepted(**res)


@router.post("/{content_id}/critique", response_model=RunAccepted, status_code=status.HTTP_202_ACCEPTED)
async def critique(content_id: UUID, db: DB, member: CurrentMember, body: CritiqueRequest | None = None) -> RunAccepted:
    res = await ContentService.critique(db, member, content_id, body.variant_id if body else None)
    await db.commit()
    return RunAccepted(**res)


@router.post("/{content_id}/fact-check", response_model=RunAccepted, status_code=status.HTTP_202_ACCEPTED)
async def fact_check(content_id: UUID, db: DB, member: CurrentMember, body: CritiqueRequest | None = None) -> RunAccepted:
    res = await ContentService.fact_check(db, member, content_id, body.variant_id if body else None)
    await db.commit()
    return RunAccepted(**res)


# ── variants ───────────────────────────────────────────────────────────────────

@router.get("/{content_id}/variants", response_model=list[VariantOut])
async def list_variants(content_id: UUID, db: DB, member: CurrentMember) -> list[VariantOut]:
    rows = await ContentService.list_variants(db, member.workspace_id, content_id)
    return [VariantOut.model_validate(ContentService.serialize_variant(v)) for v in rows]


@router.post("/{content_id}/variants", response_model=VariantOut, status_code=status.HTTP_201_CREATED)
async def create_variant(content_id: UUID, body: VariantCreate, db: DB, member: CurrentMember) -> VariantOut:
    v = await ContentService.create_variant(db, member, content_id, body.model_dump(mode="json"))
    v = await ContentService.get_variant(db, member.workspace_id, content_id, v.id)
    out = VariantOut.model_validate(ContentService.serialize_variant(v))
    await db.commit()
    return out


@router.patch("/{content_id}/variants/{variant_id}", response_model=VariantOut)
async def update_variant(content_id: UUID, variant_id: UUID, body: VariantUpdate, db: DB, member: CurrentMember) -> VariantOut:
    v = await ContentService.update_variant(db, member, content_id, variant_id, body.model_dump(exclude_unset=True, mode="json"))
    out = VariantOut.model_validate(ContentService.serialize_variant(v))
    await db.commit()
    return out


# ── versions ───────────────────────────────────────────────────────────────────

@router.get("/{content_id}/versions", response_model=list[VersionOut])
async def list_versions(content_id: UUID, db: DB, member: CurrentMember,
                        target: Literal["all", "item", "variant"] = "all") -> list[VersionOut]:
    rows = await ContentService.list_versions(db, member.workspace_id, content_id, target)
    return [VersionOut.model_validate(r) for r in rows]


@router.post("/{content_id}/versions/{version}/restore", response_model=ContentItemOut)
async def restore_version(content_id: UUID, version: int, db: DB, member: CurrentMember,
                          variant_id: UUID | None = None) -> ContentItemOut:
    await ContentService.restore_version(db, member, content_id, version, variant_id=variant_id)
    out = await _item_out(db, member, content_id)
    await db.commit()
    return out


# ── status & approvals ─────────────────────────────────────────────────────────

@router.post("/{content_id}/transition", response_model=ContentItemOut)
async def transition(content_id: UUID, body: TransitionRequest, db: DB, member: CurrentMember) -> ContentItemOut:
    await ContentService.transition(db, member, content_id, body.to, body.comment)
    out = await _item_out(db, member, content_id)
    await db.commit()
    return out


@router.post("/{content_id}/request-approval", response_model=ApprovalOut, status_code=status.HTTP_201_CREATED)
async def request_approval(content_id: UUID, db: DB, member: CurrentMember,
                           body: RequestApprovalRequest | None = None) -> ApprovalOut:
    body = body or RequestApprovalRequest()
    ap = await ContentService.request_approval(db, member, content_id, body.comment, expires_in_hours=body.expires_in_hours)
    out = ApprovalOut.model_validate(ap)
    await db.commit()
    return out


# ── assets ─────────────────────────────────────────────────────────────────────

@router.post("/{content_id}/assets", response_model=AssetOut, status_code=status.HTTP_201_CREATED)
async def attach_asset(content_id: UUID, body: AssetAttachRequest, db: DB, member: CurrentMember) -> AssetOut:
    ca = await ContentService.attach_asset(db, member, content_id, body.media_asset_id, variant_id=body.variant_id,
                                           role=body.role, position=body.position, alt_text=body.alt_text)
    out = AssetOut.model_validate(_asset_dict(ca))
    await db.commit()
    return out


@router.delete("/{content_id}/assets/{asset_id}", status_code=status.HTTP_204_NO_CONTENT)
async def remove_asset(content_id: UUID, asset_id: UUID, db: DB, member: CurrentMember) -> Response:
    await ContentService.remove_asset(db, member, content_id, asset_id)
    await db.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)

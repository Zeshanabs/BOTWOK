"""Media API: library, uploads (presigned PUT → register), generation, platform transforms, background removal, URLs."""
from __future__ import annotations

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Query, Response, status

from app.api.deps import DB, Member, require_role
from app.core.pagination import Page
from app.schemas.media import (
    GenerateImageIn,
    GenerateImageOut,
    JobAcceptedOut,
    MediaAssetOut,
    MediaUpdate,
    MediaUrlOut,
    RegisterUploadIn,
    TransformIn,
    UploadUrlIn,
    UploadUrlOut,
)
from app.services.brand_service import actor_user_id
from app.services.media_service import PRESIGN_GET_TTL_S, MediaService, defer_media_job

router = APIRouter(prefix="/media", tags=["media"])

Viewer = Annotated[Member, Depends(require_role("viewer"))]
Editor = Annotated[Member, Depends(require_role("editor"))]


async def _out(assets: list, with_urls: bool = True) -> list[MediaAssetOut]:
    urls = await MediaService.urls_for(assets) if with_urls and assets else {}
    return [MediaAssetOut.model_validate(a).model_copy(update={"url": urls.get(a.id)}) for a in assets]


@router.get("", response_model=Page[MediaAssetOut])
async def list_media(db: DB, member: Viewer, kind: str | None = None, brand_id: UUID | None = None,
                     source: str | None = None, derived_from_id: UUID | None = None, platform: str | None = None,
                     carousel_group_id: UUID | None = None, limit: Annotated[int, Query(ge=1, le=200)] = 50,
                     cursor: str | None = None):
    rows, next_cursor = await MediaService.list_media(db, member.workspace_id, kind=kind, brand_id=brand_id,
                                                      source=source, derived_from_id=derived_from_id,
                                                      platform_target=platform, carousel_group_id=carousel_group_id,
                                                      limit=limit, cursor=cursor)
    return Page[MediaAssetOut](items=await _out(rows), next_cursor=next_cursor)


@router.post("/upload-url", response_model=UploadUrlOut)
async def create_upload_url(body: UploadUrlIn, member: Editor):
    return UploadUrlOut(**await MediaService.create_upload_url(member, body.filename, body.content_type,
                                                               body.size_bytes))


@router.post("", response_model=MediaAssetOut, status_code=status.HTTP_201_CREATED)
async def register_upload(body: RegisterUploadIn, db: DB, member: Editor):
    asset = await MediaService.register_upload(db, member, body.key, body.filename, brand_id=body.brand_id,
                                               alt_text=body.alt_text, caption=body.caption)
    return (await _out([asset]))[0]


@router.post("/generate", response_model=GenerateImageOut | JobAcceptedOut, status_code=status.HTTP_201_CREATED)
async def generate(body: GenerateImageIn, db: DB, member: Editor, response: Response):
    if body.background:
        uid = actor_user_id(member)
        job_id = await defer_media_job("jobs.media.generate", None, workspace_id=str(member.workspace_id),
                                       user_id=str(uid) if uid else None, prompt=body.prompt,
                                       brand_id=str(body.brand_id) if body.brand_id else None, provider=body.provider,
                                       size=body.size, n=body.n, negative_prompt=body.negative_prompt,
                                       style=body.style, quality=body.quality,
                                       reference_asset_ids=[str(r) for r in body.reference_asset_ids],
                                       alt_text=body.alt_text)
        response.status_code = status.HTTP_202_ACCEPTED
        return JobAcceptedOut(job_id=job_id, detail="Watch for MEDIA_GENERATED events")
    assets = await MediaService.generate_image(db, member, body.brand_id, body.prompt, body.provider, body.size, body.n,
                                               negative_prompt=body.negative_prompt, style=body.style,
                                               quality=body.quality, reference_asset_ids=body.reference_asset_ids,
                                               alt_text=body.alt_text)
    return GenerateImageOut(items=await _out(assets))


@router.get("/{media_id}", response_model=MediaAssetOut)
async def get_media(media_id: UUID, db: DB, member: Viewer):
    return (await _out([await MediaService.get(db, member.workspace_id, media_id)]))[0]


@router.patch("/{media_id}", response_model=MediaAssetOut)
async def update_media(media_id: UUID, body: MediaUpdate, db: DB, member: Editor):
    return (await _out([await MediaService.update(db, member, media_id, body)]))[0]


@router.delete("/{media_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_media(media_id: UUID, db: DB, member: Editor) -> Response:
    await MediaService.delete(db, member, media_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post("/{media_id}/transform", response_model=MediaAssetOut | JobAcceptedOut,
             status_code=status.HTTP_201_CREATED)
async def transform(media_id: UUID, body: TransformIn, db: DB, member: Editor, response: Response):
    asset = await MediaService.get(db, member.workspace_id, media_id)
    if body.background or MediaService.needs_async(asset):
        if asset.kind == "video":
            from app.media.pipelines.video import require_ffmpeg
            require_ffmpeg()
        job_id = await MediaService.enqueue_transform(member, asset.id, body.platform, body.format, aspect=body.aspect,
                                                      pad_color=body.pad_color)
        response.status_code = status.HTTP_202_ACCEPTED
        return JobAcceptedOut(job_id=job_id, detail="Watch for MEDIA_PROCESSED events")
    rendition = await MediaService.transform_for_platform(db, member, asset.id, body.platform, body.format,
                                                          aspect=body.aspect, pad_color=body.pad_color)
    return (await _out([rendition]))[0]


@router.post("/{media_id}/remove-background", response_model=MediaAssetOut, status_code=status.HTTP_201_CREATED)
async def remove_background(media_id: UUID, db: DB, member: Editor):
    return (await _out([await MediaService.remove_background(db, member, media_id)]))[0]


@router.get("/{media_id}/url", response_model=MediaUrlOut)
async def media_url(media_id: UUID, db: DB, member: Viewer,
                    expires_s: Annotated[int, Query(ge=60, le=7 * 24 * 3600)] = PRESIGN_GET_TTL_S):
    asset = await MediaService.get(db, member.workspace_id, media_id)
    url, public = await MediaService.public_url(asset, expires_s)
    return MediaUrlOut(url=url, expires_in=None if public else expires_s, public=public)

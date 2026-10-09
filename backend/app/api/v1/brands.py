"""Brands API: brands, settings sections, pillars, assets, BrandContext preview, import-from-website."""
from __future__ import annotations

from typing import Annotated, Any, Literal
from uuid import UUID

from fastapi import APIRouter, Depends, Query, Response, status

from app.api.deps import DB, Member, require_role
from app.core.errors import ProblemError
from app.core.pagination import Page
from app.schemas.brand import (
    BrandAssetCreate,
    BrandAssetOut,
    BrandContextOut,
    BrandCreate,
    BrandOut,
    BrandSettingsOut,
    BrandSettingsUpdate,
    BrandUpdate,
    ImportFromWebsiteIn,
    ImportFromWebsiteOut,
    PillarCreate,
    PillarOut,
    PillarUpdate,
)
from app.services.brand_service import BrandService, estimate_tokens, safe_audit

router = APIRouter(prefix="/brands", tags=["brands"])

Viewer = Annotated[Member, Depends(require_role("viewer"))]
Admin = Annotated[Member, Depends(require_role("admin"))]


@router.get("", response_model=Page[BrandOut])
async def list_brands(db: DB, member: Viewer, status_: Annotated[str | None, Query(alias="status")] = None):
    brands = await BrandService.list_brands(db, member.workspace_id, status=status_)
    return Page[BrandOut](items=[BrandOut.model_validate(b) for b in brands])


@router.post("", response_model=BrandOut, status_code=status.HTTP_201_CREATED)
async def create_brand(body: BrandCreate, db: DB, member: Admin):
    return BrandOut.model_validate(await BrandService.create(db, member, body))


@router.get("/{brand_id}", response_model=BrandOut)
async def get_brand(brand_id: UUID, db: DB, member: Viewer):
    return BrandOut.model_validate(await BrandService.get(db, member.workspace_id, brand_id))


@router.patch("/{brand_id}", response_model=BrandOut)
async def update_brand(brand_id: UUID, body: BrandUpdate, db: DB, member: Admin):
    return BrandOut.model_validate(await BrandService.update(db, member, brand_id, body))


@router.delete("/{brand_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_brand(brand_id: UUID, db: DB, member: Admin) -> Response:
    await BrandService.soft_delete(db, member, brand_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


# ------------------------------------------------------------------ settings
@router.get("/{brand_id}/settings", response_model=BrandSettingsOut)
async def get_settings(brand_id: UUID, db: DB, member: Viewer):
    return BrandSettingsOut.model_validate(await BrandService.get_settings(db, member.workspace_id, brand_id))


@router.put("/{brand_id}/settings", response_model=BrandSettingsOut)
async def put_settings(brand_id: UUID, body: BrandSettingsUpdate, db: DB, member: Admin):
    return BrandSettingsOut.model_validate(await BrandService.update_settings(db, member, brand_id, body))


# ------------------------------------------------------------------ pillars
@router.get("/{brand_id}/pillars", response_model=Page[PillarOut])
async def list_pillars(brand_id: UUID, db: DB, member: Viewer,
                       status_: Annotated[str | None, Query(alias="status")] = None):
    rows = await BrandService.list_pillars(db, member.workspace_id, brand_id, status=status_)
    return Page[PillarOut](items=[PillarOut.model_validate(p) for p in rows])


@router.post("/{brand_id}/pillars", response_model=PillarOut, status_code=status.HTTP_201_CREATED)
async def create_pillar(brand_id: UUID, body: PillarCreate, db: DB, member: Admin):
    pillar, warnings = await BrandService.create_pillar(db, member, brand_id, body)
    return BrandService.pillar_out(pillar, warnings)


@router.patch("/{brand_id}/pillars/{pillar_id}", response_model=PillarOut)
async def update_pillar(brand_id: UUID, pillar_id: UUID, body: PillarUpdate, db: DB, member: Admin):
    pillar, warnings = await BrandService.update_pillar(db, member, brand_id, pillar_id, body)
    return BrandService.pillar_out(pillar, warnings)


@router.delete("/{brand_id}/pillars/{pillar_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_pillar(brand_id: UUID, pillar_id: UUID, db: DB, member: Admin) -> Response:
    await BrandService.delete_pillar(db, member, brand_id, pillar_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


# ------------------------------------------------------------------ assets
@router.get("/{brand_id}/assets", response_model=Page[BrandAssetOut])
async def list_assets(brand_id: UUID, db: DB, member: Viewer, kind: str | None = None):
    rows = await BrandService.list_assets(db, member.workspace_id, brand_id, kind=kind)
    return Page[BrandAssetOut](items=[BrandAssetOut.model_validate(a) for a in rows])


@router.post("/{brand_id}/assets", response_model=BrandAssetOut, status_code=status.HTTP_201_CREATED)
async def attach_asset(brand_id: UUID, body: BrandAssetCreate, db: DB, member: Admin):
    return BrandAssetOut.model_validate(await BrandService.attach_asset(db, member, brand_id, body))


# ------------------------------------------------------------------ context
@router.get("/{brand_id}/context", response_model=BrandContextOut)
async def get_context(brand_id: UUID, db: DB, member: Viewer, mode: Literal["compact", "full"] = "compact"):
    text = await BrandService.build_context(db, brand_id, mode, workspace_id=member.workspace_id)
    return BrandContextOut(text=text, token_estimate=estimate_tokens(text), mode=mode)


# ------------------------------------------------------------------ import from website (AI run)
def _run_id(run: Any) -> UUID:
    value = getattr(run, "id", None)
    if value is None and isinstance(run, dict):
        value = run.get("run_id") or run.get("id")
    if value is None:
        value = getattr(run, "run_id", None)
    if value is None:
        raise ProblemError(502, "ai_run_failed", "AI run could not be created")
    return value if isinstance(value, UUID) else UUID(str(value))


@router.post("/{brand_id}/import-from-website", response_model=ImportFromWebsiteOut,
             status_code=status.HTTP_202_ACCEPTED)
async def import_from_website(brand_id: UUID, body: ImportFromWebsiteIn, db: DB, member: Admin):
    brand = await BrandService.get(db, member.workspace_id, brand_id)
    try:
        from app.agents.orchestrator.service import AIService  # pyright: ignore[reportMissingImports]
    except ImportError as e:
        raise ProblemError(501, "ai_not_available", "AI is not available",
                           "The AI orchestrator is not installed in this build.") from e
    try:
        service: Any = AIService()
    except TypeError:
        service = AIService
    url = str(body.url)
    run = await service.create_run(db, member, message=f"Import brand settings from {url}", brand_id=brand.id,
                                   mode="tool", agent="research", action="import_brand", inputs={"url": url})
    run_id = _run_id(run)
    await safe_audit(db, member, "brand.import_from_website", "brand", brand.id,
                     after={"url": url, "run_id": str(run_id)})
    return ImportFromWebsiteOut(run_id=run_id, status_url=f"/api/v1/ai/runs/{run_id}")

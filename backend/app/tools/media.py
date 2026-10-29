"""LLM tools for media + brand visual identity (doc 05 §5.2.7, doc 06 `visual` agent allowlist).

Registered with ai-core's `app.tools.registry.tool` (loaded by `load_builtin_tools()`); if the registry is absent a local
fallback only records metadata (`fn.__tool_meta__`, `TOOLS`) so the functions stay importable and callable.
"""
from __future__ import annotations

import enum
from collections.abc import AsyncIterator, Callable
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any
from uuid import UUID

from app.core.errors import ProblemError

WRITE_ROLES = {"editor", "admin", "owner"}
READ_ROLES = {"viewer", "approver", "editor", "admin", "owner"}


@dataclass
class _LocalToolContext:  # TEMP fallback shape (mirrors ai-core's ToolContext fields we use)
    workspace_id: UUID
    db: Any = None
    user_id: UUID | None = None
    brand_id: UUID | None = None
    run_id: UUID | None = None
    agent_id: str | None = None
    role: str = "editor"
    extra: dict[str, Any] = field(default_factory=dict)


class _LocalSideEffect(enum.StrEnum):
    READ = "READ"
    WRITE_INTERNAL = "WRITE_INTERNAL"
    EXTERNAL_READ = "EXTERNAL_READ"
    SPEND = "SPEND"
    APPROVAL = "APPROVAL"


_registry_tool: Callable[..., Any] | None = None
_SideEffect: Any = _LocalSideEffect
if TYPE_CHECKING:
    ToolContext = Any
else:
    try:  # ai-core's registry
        from app.tools import registry as _registry
        _registry_tool = getattr(_registry, "tool", None)
        _SideEffect = getattr(_registry, "SideEffect", _LocalSideEffect)
        ToolContext = getattr(_registry, "ToolContext", _LocalToolContext)
    except ImportError:  # TEMP until ai-core lands app.tools.registry
        ToolContext = _LocalToolContext

TOOLS: dict[str, Callable[..., Any]] = {}


def tool(*, name: str, side_effect: str, roles: set[str], timeout_s: float, **extra: Any):
    """Register with the real registry when present; always record metadata locally."""
    se = getattr(_SideEffect, side_effect, None) or _LocalSideEffect[side_effect]

    def deco(fn: Callable[..., Any]) -> Callable[..., Any]:
        fn.__tool_meta__ = {"name": name, "side_effect": se, "roles": set(roles), "timeout_s": timeout_s,  # type: ignore[attr-defined]
                            **extra}
        TOOLS[name] = fn
        if _registry_tool is not None:
            try:
                return _registry_tool(name, side_effect=se, roles=set(roles), timeout_s=timeout_s, **extra)(fn) or fn
            except TypeError:  # registry signature differs; metadata stays available for manual wiring
                pass
        return fn
    return deco


# ------------------------------------------------------------------ context helpers
@asynccontextmanager
async def _session(ctx: Any) -> AsyncIterator[Any]:
    """The run's session when present, else a workspace-scoped unit of work (commits on success)."""
    db = getattr(ctx, "db", None)
    if db is not None:
        yield db
        return
    opener = getattr(ctx, "session", None)
    if callable(opener):
        async with opener() as s:  # pyright: ignore[reportGeneralTypeIssues]
            yield s
        return
    from app.core.db import session_scope
    async with session_scope(_ws(ctx)) as s:
        yield s


def _ws(ctx: Any) -> UUID:
    ws = getattr(ctx, "workspace_id", None)
    if ws is None:
        raise ProblemError(500, "tool_context_invalid", "Tool context has no workspace")
    return ws if isinstance(ws, UUID) else UUID(str(ws))


def _actor(ctx: Any) -> Any:
    from app.services.media_service import Actor
    uid = getattr(ctx, "user_id", None)
    role = getattr(ctx, "role", None)
    return Actor(workspace_id=_ws(ctx), user_id=(uid if isinstance(uid, UUID) else UUID(str(uid))) if uid else None,
                 role=str(getattr(role, "value", role)) if role else "editor", agent_id=getattr(ctx, "agent_id", None))


def _uuid(value: str | UUID | None, name: str = "id") -> UUID | None:
    if value is None or value == "":
        return None
    if isinstance(value, UUID):
        return value
    try:
        return UUID(str(value))
    except ValueError as e:
        raise ProblemError(422, "validation_error", "Validation failed", f"{name} is not a valid id") from e


def _req_uuid(value: str | UUID | None, name: str) -> UUID:
    out = _uuid(value, name)
    if out is None:
        raise ProblemError(422, "validation_error", "Validation failed", f"{name} is required")
    return out


def _brand(ctx: Any, brand_id: str | None) -> UUID | None:
    return _uuid(brand_id, "brand_id") or _uuid(getattr(ctx, "brand_id", None), "brand_id")


def _media_ref(a: Any, url: str | None = None) -> dict[str, Any]:
    return {"id": str(a.id), "kind": a.kind, "mime": a.mime, "width": a.width, "height": a.height,
            "bytes": a.bytes, "source": a.source, "ai_generated": a.ai_generated, "provider": a.provider,
            "model": a.model, "platform": a.platform_target,
            "derived_from_id": str(a.derived_from_id) if a.derived_from_id else None, "alt_text": a.alt_text,
            "url": url}


# ------------------------------------------------------------------ tools
@tool(name="media.generate_image", side_effect="SPEND", roles=WRITE_ROLES, timeout_s=180)
async def generate_image(ctx: ToolContext, prompt: str, size: str = "1024x1024", n: int = 1,
                         negative_prompt: str | None = None, style: str | None = None, brand_id: str | None = None,
                         provider: str | None = None, reference_asset_ids: list[str] | None = None,
                         alt_text: str | None = None) -> dict[str, Any]:
    """Generate 1–4 images from a prompt (put the brand palette/style in the prompt). Costs money (SPEND).

    size is WIDTHxHEIGHT (providers snap to their supported sizes); alt_text (≤125 chars) is stored on every image.
    Returns media ids, URLs and the cost."""
    from app.services.media_service import MediaService
    async with _session(ctx) as db:
        assets = await MediaService.generate_image(
            db, _actor(ctx), _brand(ctx, brand_id), prompt, provider, size, n, negative_prompt=negative_prompt,
            style=style, reference_asset_ids=[_req_uuid(r, "reference_asset_ids") for r in reference_asset_ids or []],
            ai_run_id=_uuid(getattr(ctx, "run_id", None)), alt_text=alt_text)
        urls = await MediaService.urls_for(assets)
    cost = sum(float((a.generation_params or {}).get("cost_usd") or 0) for a in assets)
    return {"media": [_media_ref(a, urls.get(a.id)) for a in assets], "cost_usd": round(cost, 6)}


@tool(name="media.edit", side_effect="SPEND", roles=WRITE_ROLES, timeout_s=180)
async def edit_image(ctx: ToolContext, asset_id: str, prompt: str, mask_asset_id: str | None = None, n: int = 1,
                     provider: str | None = None) -> dict[str, Any]:
    """Edit an existing image with a prompt (optionally only inside a PNG mask). Costs money (SPEND)."""
    from app.services.media_service import MediaService
    async with _session(ctx) as db:
        assets = await MediaService.edit_image(db, _actor(ctx), _req_uuid(asset_id, "asset_id"), prompt,
                                               provider=provider, mask_asset_id=_uuid(mask_asset_id, "mask_asset_id"),
                                               n=n, ai_run_id=_uuid(getattr(ctx, "run_id", None)))
        urls = await MediaService.urls_for(assets)
    cost = sum(float((a.generation_params or {}).get("cost_usd") or 0) for a in assets)
    return {"media": [_media_ref(a, urls.get(a.id)) for a in assets], "cost_usd": round(cost, 6)}


@tool(name="media.transform_for_platform", side_effect="WRITE_INTERNAL", roles=WRITE_ROLES, timeout_s=120)
async def transform_for_platform(ctx: ToolContext, asset_id: str, platform: str, format: str,
                                 aspect: str | None = None) -> dict[str, Any]:
    """Create (or reuse) a platform-compliant rendition of an image/video for (platform, format): crop/pad to the
    allowed aspect ratio, resize, re-encode under the size limit. Videos are processed asynchronously (status=queued)."""
    from app.services.media_service import MediaService
    actor = _actor(ctx)
    async with _session(ctx) as db:
        asset = await MediaService.get(db, actor.workspace_id, _req_uuid(asset_id, "asset_id"))
        if MediaService.needs_async(asset):
            from app.media.pipelines.video import require_ffmpeg
            require_ffmpeg()
            job_id = await MediaService.enqueue_transform(actor, asset.id, platform, format, aspect=aspect)
            return {"status": "queued", "job_id": job_id, "asset_id": str(asset.id), "platform": platform,
                    "format": format}
        rendition = await MediaService.transform_for_platform(db, actor, asset.id, platform, format, aspect=aspect)
        url, _public = await MediaService.public_url(rendition)
    return {"status": "ready", "rendition": _media_ref(rendition, url), "transform": rendition.transform}


@tool(name="media.attach", side_effect="WRITE_INTERNAL", roles=WRITE_ROLES, timeout_s=20)
async def attach(ctx: ToolContext, asset_id: str, variant_id: str | None = None, content_item_id: str | None = None,
                 role: str = "primary", position: int | None = None, alt_text: str | None = None) -> dict[str, Any]:
    """Attach a media asset to a content variant (or item) as primary | carousel_slide | thumbnail | cover | subtitle."""
    from app.services.media_service import MediaService
    async with _session(ctx) as db:
        ca = await MediaService.attach_to_content(db, _actor(ctx), _req_uuid(asset_id, "asset_id"),
                                                  variant_id=_uuid(variant_id, "variant_id"),
                                                  content_item_id=_uuid(content_item_id, "content_item_id"),
                                                  role=role, position=position, alt_text=alt_text)
        return {"content_asset_id": str(ca.id), "media_asset_id": str(ca.media_asset_id),
                "variant_id": str(ca.variant_id) if ca.variant_id else None,
                "content_item_id": str(ca.content_item_id) if ca.content_item_id else None, "role": ca.role,
                "position": ca.position, "alt_text": ca.alt_text}


@tool(name="media.compose_carousel", side_effect="WRITE_INTERNAL", roles=WRITE_ROLES, timeout_s=60)
async def compose_carousel(ctx: ToolContext, slides: list[dict[str, Any]], brand_id: str | None = None,
                           with_pdf: bool = False) -> dict[str, Any]:
    """Render text slides [{headline, body}] (1080×1350, brand colors, page counter) into carousel images; with_pdf
    also produces one PDF (LinkedIn document post)."""
    from app.services.media_service import MediaService
    async with _session(ctx) as db:
        assets = await MediaService.compose_carousel(db, _actor(ctx), _brand(ctx, brand_id), slides, with_pdf=with_pdf)
        urls = await MediaService.urls_for(assets)
    return {"carousel_group_id": str(assets[0].carousel_group_id),
            "media": [{**_media_ref(a, urls.get(a.id)), "position": a.position} for a in assets]}


@tool(name="brand.get_visual_identity", side_effect="READ", roles=READ_ROLES, timeout_s=10)
async def get_visual_identity(ctx: ToolContext, brand_id: str | None = None) -> dict[str, Any]:
    """Brand colors, fonts, imagery style, do/don't rules and logo asset ids."""
    from app.services.brand_service import BrandService
    bid = _brand(ctx, brand_id)
    if bid is None:
        raise ProblemError(422, "brand_required", "brand_id is required")
    async with _session(ctx) as db:
        return await BrandService.get_visual_identity(db, _ws(ctx), bid)

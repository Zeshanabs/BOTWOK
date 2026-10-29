"""brand.get_context — READ: the compact/full BrandContext string from BrandService (degrades when brand isn't built yet)."""
from __future__ import annotations

from typing import Literal

from app.tools.registry import SideEffect, ToolContext, tool

NOT_CONFIGURED = "BRAND: (not configured)"


async def build_brand_context(db, brand_id, mode: str = "compact") -> str:
    """Shared helper (used by ContextBuilder and the tool). Returns NOT_CONFIGURED when BrandService/brand is absent."""
    if brand_id is None or db is None:
        return NOT_CONFIGURED
    try:
        from app.services.brand_service import BrandService
    except ImportError:
        return NOT_CONFIGURED
    try:
        text = await BrandService().build_context(db, brand_id, mode=mode)
        return text or NOT_CONFIGURED
    except Exception as e:  # noqa: BLE001 - never let brand lookup break a run
        return f"{NOT_CONFIGURED} ({type(e).__name__})"


@tool("brand.get_context", side_effect=SideEffect.READ, timeout_s=10, idempotent=True)
async def brand_get_context(ctx: ToolContext, mode: Literal["compact", "full"] = "compact") -> dict:
    """Return the brand profile (name, audience, voice, pillars, forbidden topics, CTAs, hashtags) as text."""
    text = await build_brand_context(ctx.db, ctx.brand_id, mode=mode)
    return {"brand_id": str(ctx.brand_id) if ctx.brand_id else None, "mode": mode, "context": text}

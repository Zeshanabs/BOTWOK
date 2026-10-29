"""Trend tools for the ``trend`` / ``strategy`` agents: ``trends.signals`` (READ, deterministic burst detection),
``trends.list`` (READ), ``trends.save`` (WRITE_INTERNAL, the agent names/explains a trend)."""
from __future__ import annotations

from uuid import UUID

from app.research.toolkit import SideEffect, ToolContext, ctx_actor, ctx_workspace, tool, tool_db


def _brand(ctx: ToolContext, brand_id: str | None) -> UUID | None:
    if brand_id:
        try:
            return UUID(str(brand_id))
        except ValueError:
            return None
    return getattr(ctx, "brand_id", None)


@tool("trends.signals", side_effect=SideEffect.READ, timeout_s=30, idempotent=True)
async def trends_signals(ctx: ToolContext, term: str | None = None, window_days: int = 14, brand_id: str | None = None,
                         limit: int = 25) -> dict:
    """Term frequency over time from collected sources and competitor posts with burst detection: per term the daily
    series, z-score (last 3 days vs baseline), velocity, credibility, brand relevance and score."""
    from app.services.trend_service import TrendService
    bid = _brand(ctx, brand_id)
    if bid is None:
        return {"error": "brand_id required"}
    async with tool_db(ctx) as db:
        return await TrendService.signals_view(db, ctx_workspace(ctx), bid, term=term,
                                               window_days=max(7, min(60, int(window_days))), limit=max(1, min(100, int(limit))))


@tool("trends.list", side_effect=SideEffect.READ, timeout_s=15, idempotent=True)
async def trends_list(ctx: ToolContext, brand_id: str | None = None, status: str | None = None, limit: int = 20) -> dict:
    """Current trends for the brand (emerging/active/fading) with score, velocity, keywords and example source ids."""
    from app.services.trend_service import TrendService
    async with tool_db(ctx) as db:
        rows = await TrendService.list(db, ctx_workspace(ctx), brand_id=_brand(ctx, brand_id), status=status,
                                       limit=max(1, min(100, int(limit))))
        return {"trends": [{"trend_id": str(t.id), "label": t.label, "summary": t.summary, "score": float(t.score),
                            "velocity": float(t.velocity) if t.velocity is not None else None, "status": t.status,
                            "keywords": t.keywords, "platforms": [p.value for p in t.platforms or []],
                            "first_seen": t.first_seen.isoformat(), "last_seen": t.last_seen.isoformat(),
                            "example_source_ids": [str(s) for s in t.example_source_ids or []]} for t in rows]}


@tool("trends.save", side_effect=SideEffect.WRITE_INTERNAL, roles={"editor", "approver", "admin", "owner"}, timeout_s=15,
      idempotent=True)
async def trends_save(ctx: ToolContext, label: str, summary: str | None = None, keywords: list[str] | None = None,
                      source_ids: list[str] | None = None, status: str | None = None, brand_id: str | None = None) -> dict:
    """Save or update a named trend (upsert by label) with an explanation, keywords and supporting source ids."""
    from app.services.trend_service import TrendService
    bid = _brand(ctx, brand_id)
    if bid is None:
        return {"error": "brand_id required"}
    sids = []
    for s in source_ids or []:
        try:
            sids.append(UUID(str(s)))
        except ValueError:
            continue
    async with tool_db(ctx) as db:
        try:
            t, created = await TrendService.save(db, ctx_workspace(ctx), bid, label=label, summary=summary, keywords=keywords,
                                                 source_ids=sids, status=status, ai_run_id=getattr(ctx, "run_id", None),
                                                 actor=ctx_actor(ctx))
        except Exception as e:
            return {"error": f"{type(e).__name__}: {e}"[:300]}
        return {"trend_id": str(t.id), "created": created, "status": t.status, "score": float(t.score)}

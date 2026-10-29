"""Insight tools for the ``performance_analyst`` / ``strategy`` agents (doc 06, doc 13 §13.5).

``insights.save`` / ``recommendations.save`` (WRITE_INTERNAL) persist the analyst's findings for the run's brand (the
``AI_RUN_COMPLETED`` consumer skips runs that already saved); ``insights.list`` (READ) returns recent insights and open
recommendations so agents can build on earlier analyses.
"""
from __future__ import annotations

from typing import Any, Literal
from uuid import UUID

from pydantic import BaseModel, Field

from app.tools.registry import SideEffect, ToolContext, tool

AI_ROLES = {"approver", "editor", "admin", "owner"}


class InsightItem(BaseModel):
    statement: str = Field(description="Plain-language finding; quote the tool's numbers and n")
    kind: Literal["format", "pillar", "timing", "topic", "platform", "competitor", "audience"] | None = None
    metric: str | None = None
    effect: str | None = Field(default=None, description="e.g. '+34% engagement rate' or '2.1× average' (from a tool)")
    n: int | None = None
    confidence: float | None = Field(default=None, ge=0, le=1)
    evidence_ids: list[str] = Field(default_factory=list, description="post ids / tool result ids backing the statement")
    early_signal: bool = False
    platforms: list[str] = Field(default_factory=list)


class RecommendationItem(BaseModel):
    action: str
    rationale: str
    expected_impact: str | None = None
    priority: Literal["high", "medium", "low"] = "medium"
    links_to: Literal["pillar", "format", "time", "topic", "platform", "competitor"] | None = None
    target: str | None = Field(default=None, description="pillar id, format, time slot, topic, platform or competitor id")
    insight_id: str | None = Field(default=None, description="id returned by insights.save")


def _brand(ctx: ToolContext, brand_id: str | None) -> UUID | None:
    if brand_id:
        try:
            return UUID(str(brand_id))
        except ValueError:
            return None
    return ctx.brand_id


def _period(ctx: ToolContext) -> dict[str, Any] | None:
    return (ctx.extra or {}).get("period")


async def _run_period(ctx: ToolContext) -> dict[str, Any] | None:
    if _period(ctx):
        return _period(ctx)
    if ctx.db is None or ctx.run_id is None:
        return None
    from app.models.ai import AIRun
    run = await ctx.db.get(AIRun, ctx.run_id)
    return (((run.input or {}).get("inputs") or {}).get("period")) if run is not None else None


@tool("insights.save", side_effect=SideEffect.WRITE_INTERNAL, roles=AI_ROLES, timeout_s=20, idempotent=False)
async def insights_save(ctx: ToolContext, insights: list[InsightItem], brand_id: str | None = None) -> dict:
    """Store performance insights for the brand (statements with metric, effect, n, confidence and evidence ids).
    Statements with n < 8 are stored as early signals. Returns the new insight ids (use them in recommendations.save)."""
    from app.services.insight_service import InsightService
    bid = _brand(ctx, brand_id)
    if bid is None or ctx.db is None:
        return {"error": "brand_id required"}
    items = [i.model_dump() if hasattr(i, "model_dump") else dict(i) for i in insights or []]
    rows = await InsightService.save_insights(ctx.db, ctx.workspace_id, bid, items, ai_run_id=ctx.run_id,
                                              period=await _run_period(ctx))
    return {"insight_ids": [str(r.id) for r in rows], "saved": len(rows),
            "insights": [{"insight_id": str(r.id), "kind": r.kind, "confidence": r.confidence} for r in rows]}


@tool("recommendations.save", side_effect=SideEffect.WRITE_INTERNAL, roles=AI_ROLES, timeout_s=20, idempotent=False)
async def recommendations_save(ctx: ToolContext, recommendations: list[RecommendationItem], brand_id: str | None = None) -> dict:
    """Store recommended next actions (each with rationale, expected impact, priority and what it targets). They start as
    'proposed' and need a human decision."""
    from app.services.insight_service import InsightService
    bid = _brand(ctx, brand_id)
    if bid is None or ctx.db is None:
        return {"error": "brand_id required"}
    items = [r.model_dump() if hasattr(r, "model_dump") else dict(r) for r in recommendations or []]
    rows = await InsightService.save_recommendations(ctx.db, ctx.workspace_id, bid, items, ai_run_id=ctx.run_id)
    return {"recommendation_ids": [str(r.id) for r in rows], "saved": len(rows)}


@tool("insights.list", side_effect=SideEffect.READ, timeout_s=15, idempotent=True)
async def insights_list(ctx: ToolContext, brand_id: str | None = None, kind: str | None = None, limit: int = 15) -> dict:
    """Recent insights (statement, kind, confidence, n, status) and open recommendations for the brand."""
    from app.services.insight_service import InsightService
    bid = _brand(ctx, brand_id)
    if ctx.db is None:
        return {"error": "no session"}
    limit = max(1, min(int(limit), 50))
    ins, _ = await InsightService.list_insights(ctx.db, ctx.workspace_id, brand_id=bid, kind=kind, limit=limit)
    recs, _ = await InsightService.list_recommendations(ctx.db, ctx.workspace_id, brand_id=bid, status="proposed", limit=limit)
    return {"insights": [{"insight_id": str(i.id), "statement": i.statement, "kind": i.kind, "confidence": i.confidence,
                          "n": i.n, "status": i.status, "period_end": i.period_end.isoformat()} for i in ins
                         if i.status != "dismissed"],
            "recommendations": [{"recommendation_id": str(r.id), "action": r.action, "priority": r.priority,
                                 "insight_id": str(r.insight_id) if r.insight_id else None} for r in recs]}

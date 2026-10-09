"""research — ``ResearchService.start_run`` (EXTERNAL_READ) then yield until the research run completes (resumed by
RESEARCH_COMPLETED/RESEARCH_FAILED or the poll). Automation policy: injection-flagged sources are excluded upstream."""
from __future__ import annotations

from datetime import timedelta
from typing import Any

from sqlalchemy import select

from app.core.errors import ProblemError
from app.models.research import ResearchRun
from app.workflows.nodes.base import (
    AI_POLL,
    NodeContext,
    NodeError,
    NodeYield,
    as_uuid,
    parse_dt,
    problem_message,
    utcnow,
)

KEEP = ("summary", "findings", "topics", "gaps", "notes", "degraded", "key_points")


async def run(ctx: NodeContext, config: dict[str, Any]) -> dict[str, Any]:
    from app.services.research_service import ResearchService
    st = ctx.state
    if not st.get("research_run_id"):
        actor = ctx.require_actor()
        params = {"query": str(config.get("query") or "").strip(), "scope": config.get("scope") or ["web", "news"],
                  "depth": config.get("depth") or "standard", "recency_days": config.get("recency_days"),
                  "brand_id": ctx.brand_id, "domains_allow": config.get("domains_allow") or [],
                  "domains_deny": config.get("domains_deny") or []}
        if len(params["query"]) < 2:
            raise NodeError("research query rendered empty")
        try:
            rr = await ResearchService.start_run(ctx.db, actor, params, enqueue=False)   # commits
        except ProblemError as e:
            raise NodeError(f"could not start research: {problem_message(e)}") from e
        except ValueError as e:
            raise NodeError(f"invalid research parameters: {e}") from e
        st["research_run_id"] = str(rr.id)
        st["started_at"] = utcnow().isoformat()
        await ctx.checkpoint()
        await ResearchService.enqueue_run(ctx.db, rr)
        await ctx.checkpoint()
    rr = (await ctx.db.execute(select(ResearchRun).where(ResearchRun.id == as_uuid(st["research_run_id"]))
                               .execution_options(populate_existing=True))).scalar_one_or_none()
    if rr is None:
        raise NodeError("research run no longer exists")
    if rr.status == "completed":
        ctx.add_cost(float(rr.cost_usd or 0), f"research:{rr.id}")
        try:
            sources = await ResearchService.ranked_sources(ctx.db, rr, limit=10)
        except Exception:  # noqa: BLE001 - optional detail
            sources = []
        result = rr.result or {}
        return {"research_run_id": str(rr.id), "status": rr.status, "query": rr.query, "source_count": rr.source_count,
                "cost_usd": float(rr.cost_usd or 0), **{k: result.get(k) for k in KEEP if k in result},
                "sources": [{k: s.get(k) for k in ("id", "title", "url", "domain", "published_at", "relevance",
                                                   "credibility", "summary") if k in s} for s in sources]}
    if rr.status in ("failed", "cancelled"):
        raise NodeError(f"research {rr.status}: {(rr.error or 'no details')[:300]}", {"research_run_id": str(rr.id)})
    started = parse_dt(st.get("started_at")) or utcnow()
    if utcnow() - started > timedelta(minutes=int(config.get("timeout_minutes") or 60)):
        raise NodeError("research did not finish in time", {"research_run_id": str(rr.id)})
    raise NodeYield("waiting", reason="research_run", until=utcnow() + AI_POLL, info={"research_run_id": str(rr.id)})

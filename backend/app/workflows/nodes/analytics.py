"""analytics — ``query``: normalized post metrics (KPIs, or a breakdown by pillar/format/platform/…) via
app.analytics.queries; ``insights``: performance_analyst.analyze through the orchestrator (yields)."""
from __future__ import annotations

from datetime import timedelta
from typing import Any

from app.workflows.nodes.base import NodeContext, deliverable, utcnow


async def run(ctx: NodeContext, config: dict[str, Any]) -> dict[str, Any]:
    days = int(config.get("period_days") or 30)
    if (config.get("mode") or "query") == "insights":
        brand_id = ctx.require_brand()
        res = await ctx.ai_run("insights", agent="performance_analyst", action="analyze",
                               inputs={"brand_id": str(brand_id), "period": f"{days}d",
                                       "dimensions": config.get("dimensions") or ["pillar", "format", "platform", "hour"]},
                               message=f"Analyze performance for the last {days} days",
                               timeout_minutes=int(config.get("timeout_minutes") or 60))
        return {"mode": "insights", "insights": deliverable(res), "ai_run_id": res.get("ai_run_id"),
                "cost_usd": res.get("cost_usd")}
    from app.analytics.queries import brand_tz, breakdown, kpis, labels_for, post_rows
    since = utcnow() - timedelta(days=days)
    metric = config.get("metric") or "engagement_rate"
    rows = await post_rows(ctx.db, ctx.workspace_id, brand_id=ctx.brand_id, since=since, until=None,
                           platform=config.get("platform"), limit=2000)
    out: dict[str, Any] = {"mode": "query", "metric": metric, "period_days": days, "posts": len(rows),
                           "from": since.isoformat(), "to": utcnow().isoformat()}
    if config.get("group_by"):
        tz = await brand_tz(ctx.db, ctx.brand_id) if ctx.brand_id else None
        labels = await labels_for(ctx.db, ctx.workspace_id, config["group_by"])
        out.update(breakdown(rows, config["group_by"], metric, tz=tz, labels=labels))
    else:
        out["kpis"] = kpis(rows)
    return out

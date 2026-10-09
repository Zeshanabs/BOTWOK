"""ai_agent — one agent action through ``AIService.create_run(mode="tool", automation_run_id=…)``. The step yields
(``waiting`` with the ai_run_id on the step) and is resumed by the AI_RUN_COMPLETED/FAILED consumer (or the poll)."""
from __future__ import annotations

from typing import Any

from app.workflows.nodes.base import NodeContext, deliverable


async def run(ctx: NodeContext, config: dict[str, Any]) -> dict[str, Any]:
    agent, action = str(config["agent"]), str(config["action"])
    inputs = dict(config.get("inputs") or {})
    if ctx.brand_id and "brand_id" not in inputs:
        inputs["brand_id"] = str(ctx.brand_id)
    res = await ctx.ai_run("main", agent=agent, action=action, inputs=inputs,
                           message=config.get("message") or f"Automation {ctx.workflow.name}: {agent}.{action}",
                           budget_usd=config.get("budget_usd"), timeout_minutes=int(config.get("timeout_minutes") or 60))
    return {"ai_run_id": res.get("ai_run_id"), "output": deliverable(res), "deliverables": res.get("deliverables") or {},
            "reasoning_summary": res.get("reasoning_summary"), "sources": (res.get("sources") or [])[:20],
            "cost_usd": res.get("cost_usd")}

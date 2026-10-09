"""publish — publish already-approved variants now via ``SchedulingService.publish_now`` (APPROVAL by default;
requires the workflow's autonomous actions). The LLM never publishes: this is a deterministic engine action behind a
human approval, and SchedulingService refuses variants that are not ``approved``."""
from __future__ import annotations

from typing import Any
from uuid import UUID

from app.core.errors import ProblemError
from app.workflows.nodes.base import NodeContext, NodeError, problem_message
from app.workflows.nodes.schedule import gate, plan


async def run(ctx: NodeContext, config: dict[str, Any]) -> dict[str, Any]:
    if not ctx.workflow.autonomous_actions_enabled:
        raise NodeError("autonomous actions are disabled for this workflow; nothing was published")
    from app.services.scheduling_service import SchedulingService
    st = ctx.state
    if "plan" not in st:
        st["plan"] = await plan(ctx, config)
    items = st["plan"]
    if ctx.dry_run:
        return ctx.simulated(items=items, scheduled_post_ids=[])
    rejected = await gate(ctx, config, action="publish", items=items)
    if rejected is not None:
        return rejected
    actor = ctx.require_actor()
    ids = []
    for it in items:
        try:
            sp = await SchedulingService().publish_now(ctx.db, actor, UUID(it["variant_id"]), UUID(it["account_id"]))
        except ProblemError as e:
            raise NodeError(f"could not publish variant {it['variant_id']}: {problem_message(e)}") from e
        ids.append(str(sp.id))
    return {"scheduled_post_ids": ids, "items": items, "approval_id": st.get("approval_id")}

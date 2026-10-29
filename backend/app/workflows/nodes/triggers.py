"""trigger.cron / trigger.event / trigger.webhook / trigger.manual — the trigger step is recorded by
``AutomationEngine.start`` (output = the trigger context); re-running it just returns that context."""
from __future__ import annotations

from typing import Any

from app.workflows.nodes.base import NodeContext


async def run(ctx: NodeContext, config: dict[str, Any]) -> dict[str, Any]:
    return dict(ctx.scope.get("trigger") or {})

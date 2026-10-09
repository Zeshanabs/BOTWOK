"""Node executor registry: node type → ``async def run(ctx, config) -> dict``. Tests may swap entries (e.g. fake AI)."""
from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import Any

from app.workflows.nodes import (
    action,
    ai_agent,
    analytics,
    approve,
    condition,
    generate,
    notification,
    publish,
    research,
    schedule,
    transform,
    triggers,
    wait,
    webhook,
)
from app.workflows.nodes.base import NodeContext

Executor = Callable[[NodeContext, dict[str, Any]], Awaitable[dict[str, Any]]]

REGISTRY: dict[str, Executor] = {
    "trigger.cron": triggers.run, "trigger.event": triggers.run, "trigger.webhook": triggers.run,
    "trigger.manual": triggers.run, "condition": condition.run, "ai_agent": ai_agent.run, "research": research.run,
    "generate": generate.run, "transform": transform.run, "approve": approve.run, "schedule": schedule.run,
    "publish": publish.run, "wait": wait.run, "webhook": webhook.run, "notification": notification.run,
    "analytics": analytics.run, "action": action.run,
}


def get_executor(node_type: str) -> Executor | None:
    return REGISTRY.get(node_type)

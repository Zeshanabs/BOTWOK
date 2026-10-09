"""Event consumers owned by ai-core: AI_RUN_AWAITING_APPROVAL → notify approvers (NotificationService, lazy import)."""
from __future__ import annotations

from typing import Any
from uuid import UUID

from app.core.events import on_event
from app.core.logging import get_logger

log = get_logger("events.ai")


@on_event("AI_RUN_AWAITING_APPROVAL")
async def notify_approvers(envelope: dict[str, Any]) -> None:
    try:
        from app.services.notification_service import NotificationService
    except ImportError:
        log.info("notify.skipped", reason="NotificationService not available")
        return
    payload = envelope.get("payload") or {}
    ws = envelope.get("workspace_id")
    if not ws:
        return
    from app.core.db import session_scope
    run_id = payload.get("run_id")
    description = payload.get("description") or "An AI run proposed an action"
    link = f"/approvals?approval_id={payload.get('approval_id')}" if payload.get("approval_id") else f"/ai/runs/{run_id}"
    async with session_scope(UUID(ws)) as db:
        await NotificationService().notify(db, UUID(ws), "ai_run_awaiting_approval", "AI action needs approval",
                                           description, link, user_id=None, severity="warning")


@on_event("BUDGET_EXCEEDED")
async def notify_budget(envelope: dict[str, Any]) -> None:
    try:
        from app.services.notification_service import NotificationService
    except ImportError:
        return
    payload = envelope.get("payload") or {}
    ws = envelope.get("workspace_id")
    if not ws or payload.get("scope") == "run":
        return
    from app.core.db import session_scope
    async with session_scope(UUID(ws)) as db:
        await NotificationService().notify(db, UUID(ws), "budget_exceeded", "AI budget exceeded",
                                           f"The {payload.get('scope')} AI budget of ${payload.get('limit_usd', 0):.2f} was reached.",
                                           "/settings/ai", user_id=None, severity="error")

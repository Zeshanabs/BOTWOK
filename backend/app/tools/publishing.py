"""publishing.propose_schedule / publishing.propose_publish — APPROVAL class.

The ToolRunner never executes these: it stores a ProposedAction in `approvals` and pauses the run. After a human
approves, ApprovalGate calls the tool body, which executes through the deterministic SchedulingService/PublishingService
(when importable). No LLM path ever reaches a platform write API.
"""
from __future__ import annotations

from datetime import datetime
from typing import Any

from app.tools.registry import SideEffect, ToolContext, tool

APPROVER_ROLES = {"approver", "admin", "owner", "editor"}


def _not_available(what: str) -> dict[str, Any]:
    return {"executed": False, "error": f"{what} is not available in this deployment"}


@tool("publishing.propose_schedule", side_effect=SideEffect.APPROVAL, roles=APPROVER_ROLES, timeout_s=30)
async def propose_schedule(ctx: ToolContext, variant_id: str, scheduled_at: datetime, social_account_id: str | None = None,
                           platform: str | None = None, note: str | None = None) -> dict:
    """Propose scheduling an approved content variant at a time (creates an approval; a human must confirm)."""
    try:
        from app.services.scheduling_service import SchedulingService
    except ImportError:
        return _not_available("SchedulingService")
    svc = SchedulingService()
    kwargs: dict[str, Any] = {"variant_id": variant_id, "scheduled_at": scheduled_at, "social_account_id": social_account_id,
                              "platform": platform, "note": note, "actor": {"type": "agent", "id": ctx.agent_id,
                                                                            "run_id": str(ctx.run_id) if ctx.run_id else None}}
    for meth in ("schedule_from_proposal", "schedule"):
        fn = getattr(svc, meth, None)
        if fn is not None:
            result = await fn(ctx.db, ctx.workspace_id, **kwargs)
            return {"executed": True, "scheduled_post": _as_dict(result)}
    return _not_available("SchedulingService.schedule")


@tool("publishing.propose_publish", side_effect=SideEffect.APPROVAL, roles=APPROVER_ROLES, timeout_s=30)
async def propose_publish(ctx: ToolContext, variant_id: str, social_account_id: str | None = None,
                          platform: str | None = None, note: str | None = None) -> dict:
    """Propose publishing an approved content variant now (creates an approval; a human must confirm)."""
    try:
        from app.services.publishing_service import PublishingService
    except ImportError:
        return _not_available("PublishingService")
    svc = PublishingService()
    kwargs: dict[str, Any] = {"variant_id": variant_id, "social_account_id": social_account_id, "platform": platform,
                              "note": note, "actor": {"type": "agent", "id": ctx.agent_id,
                                                      "run_id": str(ctx.run_id) if ctx.run_id else None}}
    for meth in ("publish_from_proposal", "publish_now"):
        fn = getattr(svc, meth, None)
        if fn is not None:
            result = await fn(ctx.db, ctx.workspace_id, **kwargs)
            return {"executed": True, "result": _as_dict(result)}
    return _not_available("PublishingService.publish_now")


def _as_dict(obj: Any) -> Any:
    if obj is None:
        return None
    if hasattr(obj, "model_dump"):
        return obj.model_dump(mode="json")
    if hasattr(obj, "__table__"):
        return {c.name: (str(v) if not isinstance(v, str | int | float | bool | type(None)) else v)
                for c in obj.__table__.columns for v in [getattr(obj, c.name, None)]}
    if isinstance(obj, dict):
        return obj
    return str(obj)

"""approve — pauses the run for a human decision (APPROVAL; approval gates are on by default).

* with ``content_item_id``: ContentService.request_approval (kind ``content``) — approving moves the item and its
  variants to ``approved`` (what a downstream schedule/publish node needs); resumed by CONTENT_APPROVED/REJECTED.
* otherwise: ApprovalService.create(kind=``automation_step``, target ``automation_run``) — resumed through
  ``app.workflows.engine.on_approval_decided`` (called by ApprovalService on approve/reject/expire).

Output branch ``approved`` or ``rejected`` (rejected and expired both take the ``rejected`` branch)."""
from __future__ import annotations

from typing import Any

from sqlalchemy import select

from app.core.errors import ProblemError
from app.models.enums import ApprovalStatus, MemberRole
from app.models.platform import Approval
from app.workflows.nodes.base import (
    APPROVAL_POLL,
    NodeContext,
    NodeError,
    NodeYield,
    as_uuid,
    jsonable,
    problem_message,
    utcnow,
)

DEFAULT_ROLES = ["approver", "admin", "owner"]


def decision_output(ap: Approval) -> dict[str, Any]:
    status = getattr(ap.status, "value", ap.status)
    return {"decision": status, "branch": "approved" if status == "approved" else "rejected",
            "approved": status == "approved", "comment": ap.decision_comment, "approval_id": str(ap.id),
            "decided_by": str(ap.decided_by) if ap.decided_by else None,
            "decided_at": ap.decided_at.isoformat() if ap.decided_at else None}


async def request(ctx: NodeContext, *, title: str, description: str | None, payload: dict[str, Any],
                  roles: list[str] | None, timeout_hours: int | None, content_item_id: Any = None) -> Approval | None:
    """Create the approval once (id kept in ctx.state) or return the decided one; None while pending → caller yields."""
    st = ctx.state
    if st.get("approval_id"):
        ap = (await ctx.db.execute(select(Approval).where(Approval.id == as_uuid(st["approval_id"]))
                                   .execution_options(populate_existing=True))).scalar_one_or_none()
        if ap is None:
            raise NodeError("the approval request was deleted")
        if ap.status == ApprovalStatus.pending:
            return None
        return ap
    actor = ctx.require_actor()
    try:
        if content_item_id:
            from app.services.content_service import ContentService
            item_id = as_uuid(content_item_id, "content_item_id")
            st["content_item_id"] = str(item_id)
            item = await ContentService.get_item(ctx.db, ctx.workspace_id, item_id)
            if getattr(item.status, "value", item.status) == "approved":
                st["approval_id"] = None
                st["already_approved"] = True
                return None
            ap = await ContentService.request_approval(ctx.db, actor, item_id, comment=description or title,
                                                       expires_in_hours=int(timeout_hours or 72))
        else:
            from app.services.approval_service import ApprovalService
            ap = await ApprovalService.create(
                ctx.db, ctx.workspace_id, ctx.brand_id, "automation_step", "automation_run", ctx.run.id,
                jsonable({"title": title, "description": description, "comment": description,
                          "workflow_id": str(ctx.workflow.id), "workflow_name": ctx.workflow.name,
                          "run_id": str(ctx.run.id), "node_key": ctx.node_key, **payload}),
                actor.requested_by, [MemberRole(r) for r in (roles or DEFAULT_ROLES)],
                expires_in_hours=int(timeout_hours or 72), actor=actor)
    except ProblemError as e:
        raise NodeError(f"could not request approval: {problem_message(e)}") from e
    st["approval_id"] = str(ap.id)
    st["approval_kind"] = ap.kind
    return None


def pause(ctx: NodeContext) -> NodeYield:
    return NodeYield("awaiting_approval", reason="approval", approval_id=ctx.state.get("approval_id"),
                     until=utcnow() + APPROVAL_POLL)


async def run(ctx: NodeContext, config: dict[str, Any]) -> dict[str, Any]:
    title = str(config.get("title") or f"Approve automation step '{ctx.label or ctx.node_key}' of {ctx.workflow.name}")
    if ctx.dry_run:
        return {**ctx.simulated(title=title), "decision": "approved", "branch": "approved", "approved": True}
    roles = list((config.get("approvers") or {}).get("roles") or []) or None
    ap = await request(ctx, title=title[:300], description=config.get("description"),
                       payload={"show": config.get("show"), "approver_user_ids": (config.get("approvers") or {}).get("users")},
                       roles=roles, timeout_hours=config.get("timeout_hours"), content_item_id=config.get("content_item_id"))
    if ap is None:
        if ctx.state.get("already_approved"):
            return {"decision": "approved", "branch": "approved", "approved": True, "approval_id": None,
                    "comment": "content was already approved"}
        raise pause(ctx)
    return decision_output(ap)

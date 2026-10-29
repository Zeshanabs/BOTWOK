"""notification — NotificationService.notify (in-app + the workspace's configured channels, or explicit ones) to the
workspace, specific users or every member with a role."""
from __future__ import annotations

from typing import Any
from uuid import UUID

from sqlalchemy import select

from app.workflows.nodes.base import NodeContext, NodeError, as_uuid_list


async def run(ctx: NodeContext, config: dict[str, Any]) -> dict[str, Any]:
    title = str(config.get("title") or "").strip()
    if not title:
        raise NodeError("notification title rendered empty")
    body = config.get("body")
    body = None if body is None else str(body)
    link = config.get("link") or f"/automations/{ctx.workflow.id}/runs/{ctx.run.id}"
    severity = config.get("severity") or "info"
    channels = config.get("channels") or None
    if ctx.dry_run:
        return ctx.simulated(title=title, body=body, channels=channels or ["in_app"], severity=severity)
    from app.models.identity import WorkspaceMember
    from app.services.notification_service import NotificationService
    targets: list[UUID | None] = []
    wanted = as_uuid_list(config.get("user_ids"), "user_ids")
    roles = [str(r) for r in config.get("roles") or []]
    if wanted or roles:
        q = select(WorkspaceMember.user_id).where(WorkspaceMember.workspace_id == ctx.workspace_id)
        rows = (await ctx.db.execute(q.where(WorkspaceMember.user_id.in_(wanted)))).scalars().all() if wanted else []
        targets += list(rows)
        if roles:
            targets += list((await ctx.db.execute(q.where(WorkspaceMember.role.in_(roles)))).scalars().all())
        if not targets:
            raise NodeError("no workspace member matches the notification's users/roles")
    else:
        targets = [None]
    ids = []
    for uid in dict.fromkeys(targets):
        n = await NotificationService.notify(ctx.db, ctx.workspace_id, "automation", title[:500], body, link, user_id=uid,
                                             severity=severity, channels=channels,
                                             payload={"workflow_id": str(ctx.workflow.id), "run_id": str(ctx.run.id),
                                                      "node_key": ctx.node_key})
        ids.append(str(n.id))
    return {"notification_ids": ids, "count": len(ids), "title": title}

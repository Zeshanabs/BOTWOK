"""Identity event consumers: NOTIFICATION_CREATED → enqueue external delivery (email/Slack/webhook)."""
from __future__ import annotations

from typing import Any

from app.core.events import on_event
from app.core.logging import get_logger

log = get_logger("events.identity")

DELIVER_TASK = "jobs.notifications.deliver"


async def enqueue_delivery(notification_id: str, workspace_id: str | None) -> str:
    """Defer `jobs.notifications.deliver`; falls back to inline delivery when the queue is unavailable.

    Returns "queued", "already_queued" or "inline".
    """
    from procrastinate import exceptions as pexc

    from app.workers.app import procrastinate_app

    kwargs = {"notification_id": str(notification_id), "workspace_id": str(workspace_id) if workspace_id else None}
    try:
        deferrer = procrastinate_app.configure_task(name=DELIVER_TASK, queue="notifications",
                                                    queueing_lock=f"notify:{notification_id}")
        try:
            await deferrer.defer_async(**kwargs)
        except pexc.AppNotOpen:  # e.g. inside the scheduler process, where the app isn't opened
            async with procrastinate_app.open_async():
                await deferrer.defer_async(**kwargs)
        return "queued"
    except pexc.AlreadyEnqueued:
        return "already_queued"
    except Exception as e:  # queue schema missing / DB hiccup → best-effort inline delivery
        log.warning("notifications.enqueue_failed", error=str(e), notification_id=str(notification_id))
        from app.workers.jobs.notifications import deliver_notification
        try:
            await deliver_notification(str(notification_id), kwargs["workspace_id"])
        except Exception as e2:
            log.warning("notifications.inline_delivery_failed", error=str(e2), notification_id=str(notification_id))
        return "inline"


@on_event("NOTIFICATION_CREATED")
async def on_notification_created(envelope: dict[str, Any]) -> None:
    payload = envelope.get("payload") or {}
    nid = payload.get("notification_id")
    channels = payload.get("channels") or []
    if not nid or not any(c != "in_app" for c in channels):
        return
    await enqueue_delivery(nid, envelope.get("workspace_id"))

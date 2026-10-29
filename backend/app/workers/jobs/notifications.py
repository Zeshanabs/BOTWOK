"""Jobs: notifications — deliver external channels (email / Slack / webhook) for one notification."""
from __future__ import annotations

from uuid import UUID

import procrastinate

import app.events.consumers_identity  # noqa: F401  (registers the NOTIFICATION_CREATED consumer when workers load)
from app.core.db import session_scope
from app.core.logging import get_logger
from app.services.notification_service import NotificationService
from app.workers.app import procrastinate_app

log = get_logger("jobs.notifications")


class DeliveryIncomplete(Exception):
    """Raised so procrastinate retries channels that failed (delivered ones are skipped on retry)."""


async def deliver_notification(notification_id: str, workspace_id: str | None = None) -> dict:
    async with session_scope(UUID(workspace_id) if workspace_id else None) as db:
        return await NotificationService.deliver(db, UUID(notification_id))


@procrastinate_app.task(name="jobs.notifications.deliver", queue="notifications",
                        retry=procrastinate.RetryStrategy(max_attempts=4, exponential_wait=10))
async def deliver(notification_id: str, workspace_id: str | None = None) -> None:
    result = await deliver_notification(notification_id, workspace_id)
    log.info("notifications.delivered", notification_id=notification_id, sent=result.get("sent"), failed=result.get("failed"))
    if result.get("failed"):
        raise DeliveryIncomplete(f"failed channels: {', '.join(result['failed'])}")

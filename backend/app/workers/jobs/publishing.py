"""Jobs: publishing (doc 11 §11.3).

* ``jobs.publishing.publish_post(scheduled_post_id, attempt_no, workspace_id)`` — one attempt of the state machine.
  No library retries: the ledger (``scheduled_posts.next_attempt_at`` + scheduler) drives retries, so a crashed job is
  recovered by ``expire_leases`` → reconciliation, never by a blind re-run.
* ``jobs.publishing.reconcile(scheduled_post_id, workspace_id)`` — lease expiry / manual reconciliation.
"""
from __future__ import annotations

from app.core.logging import get_logger
from app.services.publishing_service import PublishingService
from app.workers.app import procrastinate_app

log = get_logger("jobs.publishing")


@procrastinate_app.task(name="jobs.publishing.publish_post", queue="publishing", lock=None, retry=0)
async def publish_post(scheduled_post_id: str, attempt_no: int, workspace_id: str | None = None) -> dict:
    outcome = await PublishingService().run_attempt(scheduled_post_id, int(attempt_no), workspace_id)
    log.info("publish.attempt", scheduled_post_id=scheduled_post_id, attempt_no=attempt_no, outcome=outcome)
    return {"scheduled_post_id": scheduled_post_id, "attempt_no": attempt_no, "outcome": outcome}


@procrastinate_app.task(name="jobs.publishing.reconcile", queue="publishing", retry=2)
async def reconcile(scheduled_post_id: str, workspace_id: str | None = None) -> dict:
    outcome = await PublishingService().reconcile_post(scheduled_post_id, workspace_id)
    log.info("publish.reconcile", scheduled_post_id=scheduled_post_id, outcome=outcome)
    return {"scheduled_post_id": scheduled_post_id, "outcome": outcome}


__all__ = ["publish_post", "reconcile"]

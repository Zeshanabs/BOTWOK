"""Jobs: automation — ``jobs.automation.execute(run_id, workspace_id)`` (queue ``automation``).

Enqueued by ``app.workflows.engine.enqueue_execute`` with queueing lock ``automation:{workflow_id}`` and Procrastinate
lock ``automation-run:{run_id}``. The engine checkpoints every step, so a retried job resumes where it stopped; only
infrastructure errors propagate (node failures are recorded on the step and handled by the workflow's on_error).
"""
from __future__ import annotations

from uuid import UUID

from procrastinate import RetryStrategy
from sqlalchemy.exc import DBAPIError, InterfaceError, OperationalError

from app.core.db import SessionLocal, set_workspace
from app.core.logging import get_logger
from app.workers.app import procrastinate_app

log = get_logger("jobs.automation")
INFRA_ERRORS = (OperationalError, InterfaceError, DBAPIError, ConnectionError, TimeoutError, OSError)
RETRY = RetryStrategy(max_attempts=3, wait=5, exponential_wait=3, retry_exceptions=INFRA_ERRORS)


@procrastinate_app.task(name="jobs.automation.execute", queue="automation", retry=RETRY)
async def execute(run_id: str, workspace_id: str) -> None:
    from app.workflows.engine import AutomationEngine
    log.info("jobs.automation.execute", run_id=run_id)
    async with SessionLocal() as db:
        await set_workspace(db, UUID(workspace_id))
        run = await AutomationEngine.execute(db, UUID(run_id))
        await db.commit()
    if run is not None:
        log.info("jobs.automation.executed", run_id=run_id, status=getattr(run.status, "value", run.status))

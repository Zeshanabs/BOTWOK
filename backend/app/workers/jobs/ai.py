"""Jobs: ai — `jobs.ai.run` and `jobs.ai.resume` (queue `ai`) call the Orchestrator inside session_scope(workspace_id).

Retry policy (doc 05 §5.4): agent/provider failures are handled inside the orchestrator (run → failed with a readable
message); only infrastructure errors (DB/queue connectivity) propagate so Procrastinate retries (3 attempts, exponential)
and the executor resumes from the ledger (succeeded tasks are not re-run).
"""
from __future__ import annotations

from uuid import UUID

from procrastinate import RetryStrategy
from sqlalchemy.exc import DBAPIError, InterfaceError, OperationalError

from app.core.db import session_scope
from app.core.logging import get_logger
from app.workers.app import procrastinate_app

log = get_logger("jobs.ai")
INFRA_ERRORS = (OperationalError, InterfaceError, DBAPIError, ConnectionError, TimeoutError, OSError)
RETRY = RetryStrategy(max_attempts=3, wait=5, exponential_wait=3, retry_exceptions=INFRA_ERRORS)

try:  # register event consumers in the worker process
    import app.events.consumers_ai  # noqa: F401
except Exception as e:  # noqa: BLE001
    log.warning("consumers_ai.import_failed", error=str(e)[:200])


async def _run(run_id: str, workspace_id: str, *, resume: bool) -> None:
    from app.agents.orchestrator.orchestrator import Orchestrator
    ws = UUID(workspace_id)
    async with session_scope(ws) as db:
        orch = Orchestrator()
        if resume:
            await orch.resume(db, UUID(run_id))
        else:
            await orch.run(db, UUID(run_id))


@procrastinate_app.task(name="jobs.ai.run", queue="ai", retry=RETRY)
async def run_ai(run_id: str, workspace_id: str) -> None:
    log.info("jobs.ai.run", run_id=run_id)
    await _run(run_id, workspace_id, resume=False)


@procrastinate_app.task(name="jobs.ai.resume", queue="ai", retry=RETRY)
async def resume_ai(run_id: str, workspace_id: str) -> None:
    log.info("jobs.ai.resume", run_id=run_id)
    await _run(run_id, workspace_id, resume=True)

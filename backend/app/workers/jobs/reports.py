"""Jobs: reports — ``jobs.reports.generate`` (queue ``analytics``): build the data pack, render, store, deliver.

Report-level failures are recorded on the row (``content.status = "failed"``) by ``ReportService.generate``; only
infrastructure errors propagate so Procrastinate retries (3 attempts).
"""
from __future__ import annotations

from uuid import UUID

from procrastinate import RetryStrategy
from sqlalchemy.exc import DBAPIError, InterfaceError, OperationalError

from app.core.db import session_scope
from app.core.logging import get_logger
from app.workers.app import procrastinate_app

log = get_logger("jobs.reports")
RETRY = RetryStrategy(max_attempts=3, wait=5, exponential_wait=3,
                      retry_exceptions=(OperationalError, InterfaceError, DBAPIError, ConnectionError, TimeoutError))

try:  # AI_RUN_COMPLETED / AI_RUN_FAILED → narrative merge, insight persistence (scheduler relay loads these too)
    import app.events.consumers_insights  # noqa: F401
    import app.events.consumers_reports  # noqa: F401
except Exception as e:  # noqa: BLE001
    log.warning("consumers_reports.import_failed", error=str(e)[:200])


@procrastinate_app.task(name="jobs.reports.generate", queue="analytics", retry=RETRY)
async def generate_report(report_id: str, workspace_id: str, force: bool = False) -> dict:
    from app.services.report_service import ReportService
    async with session_scope(UUID(workspace_id)) as db:
        res = await ReportService.generate(db, UUID(report_id), workspace_id=UUID(workspace_id), force=force)
    log.info("reports.generated", report_id=report_id, status=res.get("status"))
    return {k: v for k, v in res.items() if k in ("status", "report_id", "skipped", "error")}


__all__ = ["generate_report"]

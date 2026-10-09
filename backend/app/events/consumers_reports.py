"""Report consumers (doc 13 §13.6, doc 18).

- ``AI_RUN_COMPLETED`` (agent ``report``) → merge the narrative into the ``reports`` row named by ``inputs.report_id``
  (or the ``competitor_reports`` row named by ``inputs.competitor_report_id``) via ``ReportService.apply_agent_output``.
- ``AI_RUN_FAILED`` (agent ``report``) → ``narrative_status = "failed"``; the deterministic report stays ready.
"""
from __future__ import annotations

from typing import Any
from uuid import UUID

from app.core.db import session_scope
from app.core.events import on_event
from app.core.logging import get_logger

log = get_logger("consumers.reports")


def _uuid(v: Any) -> UUID | None:
    try:
        return UUID(str(v))
    except (TypeError, ValueError):
        return None


async def _report_run(db: Any, envelope: dict[str, Any]) -> Any:
    from app.models.ai import AIRun
    payload = envelope.get("payload") or {}
    ws, run_id = _uuid(envelope.get("workspace_id")), _uuid(payload.get("run_id"))
    if not ws or not run_id:
        return None
    run = await db.get(AIRun, run_id)
    if run is None or run.workspace_id != ws:
        return None
    inp = run.input or {}
    inputs = inp.get("inputs") or {}
    if inp.get("agent") != "report" or not (inputs.get("report_id") or inputs.get("competitor_report_id")):
        return None
    return run


@on_event("AI_RUN_COMPLETED")
async def merge_report_narrative(envelope: dict[str, Any]) -> None:
    ws = _uuid(envelope.get("workspace_id"))
    if not ws:
        return
    from app.services.report_service import ReportService
    async with session_scope(ws) as db:
        run = await _report_run(db, envelope)
        if run is None:
            return
        res = await ReportService.apply_agent_output(db, run)
        log.info("reports.narrative_applied", run_id=str(run.id), **{k: v for k, v in res.items() if k != "applied"})


@on_event("AI_RUN_FAILED")
async def report_narrative_failed(envelope: dict[str, Any]) -> None:
    ws = _uuid(envelope.get("workspace_id"))
    if not ws:
        return
    from app.services.report_service import ReportService
    async with session_scope(ws) as db:
        run = await _report_run(db, envelope)
        if run is None:
            return
        await ReportService.narrative_failed(db, run, (envelope.get("payload") or {}).get("error"))

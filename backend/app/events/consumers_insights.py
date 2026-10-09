"""Insight consumers (doc 13 §13.5, doc 18).

- ``AI_RUN_COMPLETED`` → persist a ``performance_analyst`` ``Insights`` output (``InsightService.apply_agent_output``;
  idempotent per run, so outputs already stored by the ``insights.save`` / ``recommendations.save`` tools are kept).
- ``AI_RUN_FAILED`` → for analyses started by ``POST /insights/analyze``, fall back to the deterministic insights from the
  evidence pack stored in the run inputs.
"""
from __future__ import annotations

from typing import Any
from uuid import UUID

from app.core.db import session_scope
from app.core.events import on_event
from app.core.logging import get_logger

log = get_logger("consumers.insights")


def _uuid(v: Any) -> UUID | None:
    try:
        return UUID(str(v))
    except (TypeError, ValueError):
        return None


async def _load_run(db: Any, run_id: UUID, ws: UUID) -> Any:
    from app.models.ai import AIRun
    run = await db.get(AIRun, run_id)
    return run if run is not None and run.workspace_id == ws else None


def _is_analysis(run: Any) -> bool:
    inp = run.input or {}
    if inp.get("agent") == "performance_analyst":
        return True
    tasks = (run.result or {}).get("tasks") or []
    return any(isinstance(t, dict) and t.get("agent") == "performance_analyst" and t.get("status") == "succeeded" for t in tasks)


@on_event("AI_RUN_COMPLETED")
async def persist_analysis(envelope: dict[str, Any]) -> None:
    payload = envelope.get("payload") or {}
    ws, run_id = _uuid(envelope.get("workspace_id")), _uuid(payload.get("run_id"))
    if not ws or not run_id:
        return
    from app.services.insight_service import InsightService
    async with session_scope(ws) as db:
        run = await _load_run(db, run_id, ws)
        if run is None or not _is_analysis(run):
            return
        try:
            res = await InsightService.apply_agent_output(db, run)
            log.info("insights.applied", run_id=str(run_id), **{k: v for k, v in res.items() if k != "applied"})
        except Exception as e:  # noqa: BLE001 - never break the relay
            log.warning("insights.apply_failed", run_id=str(run_id), error=str(e)[:300])
            raise


@on_event("AI_RUN_FAILED")
async def analysis_fallback(envelope: dict[str, Any]) -> None:
    payload = envelope.get("payload") or {}
    ws, run_id = _uuid(envelope.get("workspace_id")), _uuid(payload.get("run_id"))
    if not ws or not run_id or payload.get("cancelled"):
        return
    from app.services.insight_service import InsightService
    async with session_scope(ws) as db:
        run = await _load_run(db, run_id, ws)
        if run is None or (run.input or {}).get("agent") != "performance_analyst":
            return
        res = await InsightService.fallback_after_failed_run(db, run)
        if res.get("insights_created") is not None:
            log.info("insights.fallback_applied", run_id=str(run_id), insights=res.get("insights_created"))

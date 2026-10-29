"""Trigger dispatch (doc 14 §14.4): cron, waiting-run resumption, platform events, webhooks.

Scheduler wiring (called every tick with a fresh session; both commit their own work and return a count):
    await dispatch_cron(db)       # active workflows whose next_run_at is due → start a run, advance next_run_at
    await dispatch_waiting(db)    # waiting / awaiting_approval runs whose waiting_until passed (+ stale running
                                  # runs whose lease expired) → re-enqueue jobs.automation.execute
Event triggers are dispatched by ``app/events/consumers_automation.py`` (``handle_event``).
"""
from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import ProblemError
from app.core.logging import get_logger
from app.models.ai import AIRun
from app.models.brand import Brand
from app.models.enums import AutomationStatus
from app.models.platform import AutomationRun, AutomationRunStep, AutomationWorkflow, WorkflowNode
from app.workflows import cron
from app.workflows.expressions import ExpressionError, compile_expression

log = get_logger("automation.triggers")
WAKE_LEASE = timedelta(minutes=2)
MAX_CHAIN_DEPTH = 3
BATCH = 50


def utcnow() -> datetime:
    return datetime.now(UTC)


# ============================================================================================ cron

async def dispatch_cron(db: AsyncSession, now: datetime | None = None, *, workspace_id: UUID | None = None) -> int:
    """Start runs for active ``trigger.cron`` workflows whose ``next_run_at`` is due. A slot missed by more than
    ``misfire_grace_minutes`` (default 60) is skipped, not replayed. Commits; returns the number of runs started."""
    from app.workflows.engine import AutomationEngine, enqueue_execute
    now = now or utcnow()
    q = select(AutomationWorkflow).where(AutomationWorkflow.status == "active", AutomationWorkflow.next_run_at.is_not(None),
                                         AutomationWorkflow.next_run_at <= now)
    if workspace_id is not None:
        q = q.where(AutomationWorkflow.workspace_id == workspace_id)
    wfs = (await db.execute(q.order_by(AutomationWorkflow.next_run_at).with_for_update(skip_locked=True)
                            .limit(BATCH))).scalars().all()
    started: list[tuple[UUID, UUID, UUID]] = []
    for wf in wfs:
        node = (await db.execute(select(WorkflowNode).where(WorkflowNode.workflow_id == wf.id,
                                                            WorkflowNode.type == "trigger.cron"))).scalar_one_or_none()
        if node is None:
            wf.next_run_at = None
            continue
        cfg = node.config or {}
        brand_tz = (await db.execute(select(Brand.timezone).where(Brand.id == wf.brand_id))).scalar_one_or_none() \
            if wf.brand_id else None
        slot = wf.next_run_at
        try:
            wf.next_run_at = cron.next_run_at(cfg, max(now, slot), brand_tz)
        except cron.CronError as e:
            log.warning("automation.cron_invalid", workflow_id=str(wf.id), error=str(e))
            wf.next_run_at = None
            continue
        grace = timedelta(minutes=int(cfg.get("misfire_grace_minutes") or 60))
        if now - slot > grace:
            log.info("automation.cron_misfire_skipped", workflow_id=str(wf.id), slot=slot.isoformat())
            continue
        try:
            async with db.begin_nested():
                run = await AutomationEngine.start(db, wf, "cron", {}, defer=False, trigger_extra={
                    "scheduled_for": slot.isoformat(), "timezone": cfg.get("timezone") or brand_tz or "UTC"})
            started.append((run.id, wf.workspace_id, wf.id))
        except ProblemError as e:
            log.info("automation.cron_skipped", workflow_id=str(wf.id), reason=e.type, detail=str(e.detail)[:200])
    await db.commit()
    for rid, ws, wid in started:
        await enqueue_execute(rid, ws, wid)
    return len(started)


# ============================================================================================ waiting runs

async def dispatch_waiting(db: AsyncSession, now: datetime | None = None, *, workspace_id: UUID | None = None) -> int:
    """Re-enqueue runs that are due: ``waiting``/``awaiting_approval`` with ``waiting_until <= now`` (timers, AI/research
    polls, approval polls) and ``running`` runs whose execution lease expired (lost job). Commits; returns the count."""
    from app.workflows.engine import enqueue_execute
    now = now or utcnow()
    q = select(AutomationRun).where(
        AutomationRun.status.in_((AutomationStatus.waiting, AutomationStatus.awaiting_approval, AutomationStatus.running)),
        AutomationRun.waiting_until.is_not(None), AutomationRun.waiting_until <= now)
    if workspace_id is not None:
        q = q.where(AutomationRun.workspace_id == workspace_id)
    runs = (await db.execute(q.order_by(AutomationRun.waiting_until).with_for_update(skip_locked=True)
                             .limit(BATCH * 2))).scalars().all()
    due = []
    for r in runs:
        r.waiting_until = now + WAKE_LEASE
        due.append((r.id, r.workspace_id, r.workflow_id))
    await db.commit()
    for rid, ws, wid in due:
        await enqueue_execute(rid, ws, wid)
    return len(due)


# ============================================================================================ events

def filter_matches(config: dict[str, Any], payload: dict[str, Any]) -> bool:
    """``filter``: ``min_<f>``/``max_<f>`` bounds, list → any-of (payload scalar or list), scalar → equality; then the
    optional ``condition`` expression over ``{**payload, trigger: payload, event}``."""
    flt = config.get("filter") or {}
    if isinstance(flt, dict):
        for key, want in flt.items():
            if key.startswith(("min_", "max_")):
                field = key[4:]
                got = payload.get(field)
                try:
                    g, w = float(got), float(want)
                except (TypeError, ValueError):
                    return False
                if (key.startswith("min_") and g < w) or (key.startswith("max_") and g > w):
                    return False
                continue
            got = payload.get(key)
            if isinstance(want, list):
                vals = got if isinstance(got, list) else [got]
                if not any(v in want for v in vals):
                    return False
            elif got != want:
                return False
    cond = config.get("condition")
    if cond:
        try:
            return bool(compile_expression(str(cond)).evaluate({**payload, "trigger": payload, "event": payload.get("event")}))
        except ExpressionError as e:
            log.info("automation.event_condition_error", error=str(e))
            return False
    return True


def event_trigger_payload(envelope: dict[str, Any]) -> dict[str, Any]:
    name = str(envelope.get("name") or "")
    payload = dict(envelope.get("payload") or {})
    entity = name.split("_", 1)[0].lower()
    return {**payload, "event": name, "event_id": envelope.get("event_id"), "occurred_at": envelope.get("occurred_at"),
            "payload": payload, entity: payload}


async def dispatch_event(envelope: dict[str, Any]) -> int:
    """Start runs of active workflows whose ``trigger.event`` matches this event (deduped by event_id)."""
    from app.core.db import session_scope
    from app.workflows.engine import AutomationEngine, enqueue_execute
    name = str(envelope.get("name") or "")
    ws = envelope.get("workspace_id")
    if not ws or not name:
        return 0
    payload = dict(envelope.get("payload") or {})
    depth = int(payload.get("chain_depth") or 0)
    started: list[tuple[UUID, UUID, UUID]] = []
    async with session_scope(UUID(str(ws))) as db:
        rows = (await db.execute(select(AutomationWorkflow, WorkflowNode).join(
            WorkflowNode, WorkflowNode.workflow_id == AutomationWorkflow.id).where(
            AutomationWorkflow.workspace_id == UUID(str(ws)), AutomationWorkflow.status == "active",
            WorkflowNode.type == "trigger.event", WorkflowNode.config["event"].astext == name))).all()
        for wf, node in rows:
            if name.startswith("AUTOMATION_") and (payload.get("workflow_id") == str(wf.id) or depth >= MAX_CHAIN_DEPTH):
                continue
            if wf.brand_id and payload.get("brand_id") and str(payload["brand_id"]) != str(wf.brand_id):
                continue
            if not filter_matches(node.config or {}, payload):
                continue
            eid = envelope.get("event_id")
            if eid:
                dup = (await db.execute(select(AutomationRun.id).where(
                    AutomationRun.workflow_id == wf.id, AutomationRun.trigger_payload["event_id"].astext == str(eid))
                    .limit(1))).scalar_one_or_none()
                if dup is not None:
                    continue
            trig = event_trigger_payload(envelope)
            trig["chain_depth"] = depth + 1 if name.startswith("AUTOMATION_") else depth
            try:
                async with db.begin_nested():
                    run = await AutomationEngine.start(db, wf, "event", {"event_id": eid, "event": name, **payload},
                                                       defer=False, trigger_extra=trig)
                started.append((run.id, wf.workspace_id, wf.id))
            except ProblemError as e:
                log.info("automation.event_skipped", workflow_id=str(wf.id), event=name, reason=e.type)
    for rid, wsid, wid in started:
        await enqueue_execute(rid, wsid, wid)
    return len(started)


# ============================================================================================ resume on events

async def _runs_with_state(db: AsyncSession, field: str, value: str, statuses: tuple[str, ...]) -> list[UUID]:
    rows = (await db.execute(select(AutomationRunStep.run_id).where(
        AutomationRunStep.status.in_(statuses),
        AutomationRunStep.output["_state"][field].astext == value))).scalars().all()
    return list(dict.fromkeys(rows))


async def resume_from_event(envelope: dict[str, Any]) -> int:
    """Wake automation runs waiting on the AI run / research run / approval / content this event is about."""
    from app.core.db import session_scope
    from app.workflows.engine import wake_and_enqueue
    name = str(envelope.get("name") or "")
    ws = envelope.get("workspace_id")
    payload = envelope.get("payload") or {}
    if not ws:
        return 0
    wsid = UUID(str(ws))
    run_ids: list[UUID] = []
    async with session_scope(wsid) as db:
        if name in ("AI_RUN_COMPLETED", "AI_RUN_FAILED") and payload.get("run_id"):
            ar = await db.get(AIRun, UUID(str(payload["run_id"])))
            if ar is not None and ar.automation_run_id:
                run_ids.append(ar.automation_run_id)
        elif name in ("RESEARCH_COMPLETED", "RESEARCH_FAILED") and payload.get("run_id"):
            run_ids += await _runs_with_state(db, "research_run_id", str(payload["run_id"]), ("waiting", "running"))
        elif name in ("CONTENT_APPROVED", "CONTENT_REJECTED") and payload.get("approval_id"):
            run_ids += await _runs_with_state(db, "approval_id", str(payload["approval_id"]), ("awaiting_approval",))
        elif name == "CONTENT_STATUS_CHANGED" and payload.get("content_item_id"):
            run_ids += await _runs_with_state(db, "content_item_id", str(payload["content_item_id"]), ("awaiting_approval",))
    if not run_ids:
        return 0
    return await wake_and_enqueue(run_ids, wsid)


RESUME_EVENTS = frozenset({"AI_RUN_COMPLETED", "AI_RUN_FAILED", "RESEARCH_COMPLETED", "RESEARCH_FAILED",
                           "CONTENT_APPROVED", "CONTENT_REJECTED", "CONTENT_STATUS_CHANGED"})


async def handle_event(envelope: dict[str, Any]) -> None:
    """Single consumer entry point per event name: resume waiting runs, then dispatch event triggers."""
    name = str(envelope.get("name") or "")
    if name in RESUME_EVENTS:
        try:
            await resume_from_event(envelope)
        except Exception as e:  # noqa: BLE001 - polling (dispatch_waiting) is the fallback
            log.warning("automation.resume_failed", event=name, error=str(e)[:300])
    try:
        await dispatch_event(envelope)
    except Exception as e:  # noqa: BLE001
        log.warning("automation.event_dispatch_failed", event=name, error=str(e)[:300])


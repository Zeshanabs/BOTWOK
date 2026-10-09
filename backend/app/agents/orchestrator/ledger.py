"""RunLedger helpers (doc 05 §5.2.12): ai_runs / ai_tasks / ai_tool_calls / ai_calls writes + AI_RUN_* events.

Run totals are incremented with atomic UPDATEs (parallel tasks use their own sessions) and mirrored on the in-memory run.
"""
from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime
from typing import Any
from uuid import UUID

from sqlalchemy import update

from app.core.events import emit
from app.core.logging import get_logger
from app.core.ports.ai_provider import Completion, Message
from app.core.pricing import estimate_cost
from app.models.ai import AICall, AIRun, AITask
from app.models.enums import RunStatus, TaskStatus

log = get_logger("ai.ledger")


def utcnow() -> datetime:
    return datetime.now(UTC)


def prompt_hash(messages: list[Message]) -> str:
    sys_text = "\n".join(str(m.content) for m in messages if m.role == "system")
    return hashlib.sha256(sys_text.encode("utf-8", errors="ignore")).hexdigest()[:32]


async def safe_commit(db: Any) -> None:
    if db is None:
        return
    try:
        await db.commit()
    except Exception as e:  # noqa: BLE001
        log.warning("ledger.commit_failed", error=str(e)[:200])
        try:
            await db.rollback()
        except Exception:  # noqa: BLE001
            pass


async def _emit(db: Any, run: AIRun, name: str, payload: dict[str, Any]) -> None:
    if db is None:
        return
    try:
        actor = {"type": "user", "id": str(run.user_id)} if run.user_id else {"type": "system"}
        await emit(db, name, {"run_id": str(run.id), "brand_id": str(run.brand_id) if run.brand_id else None,
                              "mode": run.mode, **payload}, workspace_id=run.workspace_id, actor=actor,
                   correlation_id=str(run.id))
    except Exception as e:  # noqa: BLE001
        log.warning("ledger.emit_failed", event=name, error=str(e)[:200])


def _ms(start: datetime | None, end: datetime | None) -> int | None:
    if not start or not end:
        return None
    return int((end - start).total_seconds() * 1000)


def _f(v: Any) -> float:
    return float(v or 0)


# ----------------------------------------------------------------------------- run lifecycle

async def run_started(db: Any, run: AIRun) -> None:
    run.status = RunStatus.running
    run.started_at = run.started_at or utcnow()
    run.error = None
    await _emit(db, run, "AI_RUN_STARTED", {"message": (run.input or {}).get("message", "")[:200]})
    await safe_commit(db)


async def run_planning(db: Any, run: AIRun) -> None:
    run.status = RunStatus.planning
    await safe_commit(db)


async def run_running(db: Any, run: AIRun) -> None:
    run.status = RunStatus.running
    await safe_commit(db)


async def run_completed(db: Any, run: AIRun, result: dict[str, Any], reasoning_summary: str | None = None) -> None:
    run.status = RunStatus.completed
    run.result = result
    run.reasoning_summary = reasoning_summary
    run.finished_at = utcnow()
    await _emit(db, run, "AI_RUN_COMPLETED", {"cost_usd": _f(run.cost_usd), "tokens_in": int(run.tokens_in or 0),
                                              "tokens_out": int(run.tokens_out or 0),
                                              "duration_ms": _ms(run.started_at, run.finished_at),
                                              "sources_count": len(result.get("sources", []) or []),
                                              "deliverables": list((result.get("deliverables") or {}).keys())[:20]})
    await safe_commit(db)


async def run_failed(db: Any, run: AIRun, error: str, *, partial_result: dict[str, Any] | None = None) -> None:
    run.status = RunStatus.failed
    run.error = error[:2000]
    run.finished_at = utcnow()
    if partial_result:
        run.result = partial_result
    await _emit(db, run, "AI_RUN_FAILED", {"error": error[:500], "cost_usd": _f(run.cost_usd),
                                           "duration_ms": _ms(run.started_at, run.finished_at)})
    await safe_commit(db)


async def run_cancelled(db: Any, run: AIRun, *, partial_result: dict[str, Any] | None = None) -> None:
    run.status = RunStatus.cancelled
    run.finished_at = utcnow()
    if partial_result:
        run.result = partial_result
    await _emit(db, run, "AI_RUN_FAILED", {"error": "cancelled", "cancelled": True, "cost_usd": _f(run.cost_usd)})
    await safe_commit(db)


async def run_awaiting_approval(db: Any, run: AIRun, task: AITask | None, approval_id: UUID | str, description: str,
                                *, kind: str = "ai_action") -> None:
    run.status = RunStatus.awaiting_approval
    if task is not None:
        task.status = TaskStatus.awaiting_approval
    await _emit(db, run, "AI_RUN_AWAITING_APPROVAL", {"approval_id": str(approval_id), "kind": kind, "description": description[:300],
                                                      "task_key": task.task_key if task else None,
                                                      "step": task.label if task else None, "cost_usd": _f(run.cost_usd)})
    await safe_commit(db)


# ----------------------------------------------------------------------------- tasks

async def task_started(db: Any, task: AITask) -> None:
    task.status = TaskStatus.running
    task.started_at = utcnow()
    task.heartbeat_at = task.started_at
    task.error = None
    await safe_commit(db)


async def heartbeat(db: Any, task: AITask) -> None:
    task.heartbeat_at = utcnow()
    await safe_commit(db)


async def task_succeeded(db: Any, run: AIRun, task: AITask, output: dict[str, Any], *, sources_count: int = 0) -> None:
    task.status = TaskStatus.succeeded
    task.output = output
    task.finished_at = utcnow()
    await _emit(db, run, "AI_RUN_STEP_COMPLETED", {"task_key": task.task_key, "step": task.label, "agent": task.agent_id,
                                                   "action": task.action, "status": "succeeded",
                                                   "duration_ms": _ms(task.started_at, task.finished_at),
                                                   "cost_usd": _f(task.cost_usd), "sources_count": sources_count})
    await safe_commit(db)


async def task_failed(db: Any, run: AIRun, task: AITask, error: str) -> None:
    task.status = TaskStatus.failed
    task.error = error[:2000]
    task.finished_at = utcnow()
    await _emit(db, run, "AI_RUN_STEP_COMPLETED", {"task_key": task.task_key, "step": task.label, "agent": task.agent_id,
                                                   "action": task.action, "status": "failed", "error": error[:300],
                                                   "duration_ms": _ms(task.started_at, task.finished_at),
                                                   "cost_usd": _f(task.cost_usd), "sources_count": 0})
    await safe_commit(db)


async def task_skipped(db: Any, task: AITask, reason: str) -> None:
    task.status = TaskStatus.skipped
    task.error = reason[:500]
    task.finished_at = utcnow()
    await safe_commit(db)


async def task_cancelled(db: Any, task: AITask) -> None:
    task.status = TaskStatus.cancelled
    task.finished_at = utcnow()
    await safe_commit(db)


# ----------------------------------------------------------------------------- LLM calls

async def record_call(db: Any, *, run: AIRun | None, task: AITask | None, agent_id: str | None, completion: Completion,
                      prompt_version: int | None = None, prompt_hash_: str | None = None, temperature: float | None = None,
                      error: str | None = None, workspace_id: UUID | None = None, budget_guard: Any = None) -> AICall:
    """Every LLM call writes an ai_calls row with cost (pricing table at call time) and increments run/task totals."""
    u = completion.usage
    cost = estimate_cost(completion.provider, completion.model, u)
    ws = workspace_id or (run.workspace_id if run is not None else None)
    row = AICall(workspace_id=ws, run_id=run.id if run is not None else None, task_id=task.id if task is not None else None,
                 agent_id=agent_id, provider=completion.provider, model=completion.model, prompt_version=prompt_version,
                 prompt_hash=prompt_hash_, tokens_in=int(u.tokens_in), tokens_out=int(u.tokens_out),
                 cached_tokens=int(u.cached_tokens), cost_usd=cost, latency_ms=completion.latency_ms,
                 finish_reason=completion.finish_reason, temperature=temperature, error=error, created_at=utcnow())
    if db is not None:
        db.add(row)
    if task is not None:
        task.tokens_in = int(task.tokens_in or 0) + int(u.tokens_in)
        task.tokens_out = int(task.tokens_out or 0) + int(u.tokens_out)
        task.cost_usd = _f(task.cost_usd) + cost
    if run is not None:
        run.tokens_in = int(run.tokens_in or 0) + int(u.tokens_in)
        run.tokens_out = int(run.tokens_out or 0) + int(u.tokens_out)
        run.cached_tokens = int(run.cached_tokens or 0) + int(u.cached_tokens)
        run.cost_usd = _f(run.cost_usd) + cost
        if db is not None:
            try:
                # atomic increment; synchronize_session=False keeps the in-memory run (possibly owned by another
                # session) from being expired, which would force a sync lazy-load outside the greenlet context
                await db.execute(update(AIRun).where(AIRun.id == run.id).values(
                    tokens_in=AIRun.tokens_in + int(u.tokens_in), tokens_out=AIRun.tokens_out + int(u.tokens_out),
                    cached_tokens=AIRun.cached_tokens + int(u.cached_tokens), cost_usd=AIRun.cost_usd + cost)
                                 .execution_options(synchronize_session=False))
            except Exception as e:  # noqa: BLE001
                log.warning("ledger.run_increment_failed", error=str(e)[:200])
    if budget_guard is not None and ws is not None and db is not None:
        try:
            await budget_guard.record(db, ws, cost, int(u.tokens_in) + int(u.tokens_out), run.id if run is not None else None,
                                      provider=completion.provider, model=completion.model)
        except Exception as e:  # noqa: BLE001
            log.warning("ledger.usage_record_failed", error=str(e)[:200])
    await safe_commit(db)
    log.info("ai.call", agent=agent_id, provider=completion.provider, model=completion.model, tokens_in=u.tokens_in,
             tokens_out=u.tokens_out, cached=u.cached_tokens, cost_usd=round(cost, 6), latency_ms=completion.latency_ms,
             finish=completion.finish_reason)
    return row


def dumps(obj: Any) -> str:
    return json.dumps(obj, default=str, ensure_ascii=False)

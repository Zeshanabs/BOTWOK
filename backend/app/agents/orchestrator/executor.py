"""Executor (doc 05 §5.2.5): persists ai_tasks, resolves `tX.path` input references, runs ready tasks concurrently
(asyncio.TaskGroup, ≤ max_parallel) with fan-out/fan-in, cooperative cancellation, crash-safe resume and heartbeats."""
from __future__ import annotations

import asyncio
import re
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import UUID

from sqlalchemy import select

from app.agents.base import CanaryLeakError
from app.agents.orchestrator import ledger
from app.agents.orchestrator.approval_gate import ApprovalGate
from app.agents.orchestrator.citations import CitationTracker
from app.agents.orchestrator.context import RunContext
from app.agents.orchestrator.plan_templates import MAX_FAN_OUT
from app.agents.orchestrator.runtime import AgentRuntime, TaskFailed, TaskOutcome
from app.agents.registry import get_spec
from app.agents.schemas.orchestrator import Plan, PlanTask
from app.config import settings
from app.core.ids import new_id
from app.core.logging import get_logger
from app.models.ai import AIRun, AITask
from app.models.enums import TaskStatus
from app.services.budget_guard import BudgetExceeded
from app.tools.runner import AwaitingApproval

log = get_logger("ai.executor")
_REF_RE = re.compile(r"^(t\d+(?:\.\d+)?)(?:\.(.+))?$")
STALE_HEARTBEAT = timedelta(minutes=2)
DONE = {TaskStatus.succeeded, TaskStatus.failed, TaskStatus.skipped, TaskStatus.cancelled}


@dataclass
class ExecutionResult:
    status: str                                   # completed | failed | awaiting_approval | cancelled
    outputs: dict[str, Any] = field(default_factory=dict)
    errors: dict[str, str] = field(default_factory=dict)
    reasoning: dict[str, list[str]] = field(default_factory=dict)
    tracker: CitationTracker = field(default_factory=CitationTracker)
    awaiting: AwaitingApproval | None = None
    awaiting_task_key: str | None = None
    error: str | None = None


@asynccontextmanager
async def _same_session(db: Any):
    yield db


# ----------------------------------------------------------------------------- reference resolution

def _get_path(obj: Any, path: str | None) -> Any:
    if not path:
        return obj
    cur: Any = obj
    for part in path.split("."):
        if part == "":
            continue
        star = part.endswith("[*]")
        key = part[:-3] if star else part
        if key:
            if isinstance(cur, list):
                cur = [c.get(key) if isinstance(c, dict) else None for c in cur]
            elif isinstance(cur, dict):
                cur = cur.get(key)
            else:
                return None
        if star and not isinstance(cur, list):
            cur = [cur] if cur is not None else []
    return cur


def resolve_ref(ref: str, outputs: dict[str, Any], ctx: RunContext | None = None, inputs: dict[str, Any] | None = None,
                fan_item: Any = None, fan_root: str | None = None) -> Any:
    if ref == "$brand":
        return ctx.brand if ctx else None
    if ref == "$message":
        return ctx.message if ctx else None
    if ref.startswith("$entities."):
        return _get_path((ctx.intent or {}).get("entities", {}) if ctx else {}, ref[len("$entities."):])
    if ref.startswith("$inputs."):
        return _get_path(inputs or {}, ref[len("$inputs."):])
    m = _REF_RE.match(ref)
    if not m:
        return ref
    task_id, path = m.group(1), m.group(2)
    if fan_root and task_id == fan_root and fan_item is not None:
        return fan_item if not path else _get_path(fan_item, path) if isinstance(fan_item, dict) else fan_item
    if task_id not in outputs:
        return None
    return _get_path(outputs[task_id], path)


def resolve_inputs(inputs: dict[str, Any], outputs: dict[str, Any], ctx: RunContext | None = None, *, fan_item: Any = None,
                   fan_index: int | None = None, fan_root: str | None = None, depth: int = 0) -> dict[str, Any]:
    """Resolve `tX.path` strings, `$brand`/`$message`/`$entities.*`, `*_from` keys and fan-out placeholders."""
    out: dict[str, Any] = {}
    for k, v in (inputs or {}).items():
        if k.startswith("_"):
            continue
        if (k.endswith("_from") or k == "from") and isinstance(v, str | list):
            refs = [v] if isinstance(v, str) else v
            resolved = [resolve_ref(r, outputs, ctx, inputs, fan_item, fan_root) if isinstance(r, str) else r for r in refs]
            key = k[:-5] if k.endswith("_from") else "inputs_from_tasks"
            out[key] = resolved[0] if isinstance(v, str) else dict(zip([str(r) for r in refs], resolved, strict=False))
            continue
        out[k] = _resolve_value(v, outputs, ctx, inputs, fan_item, fan_index, fan_root, depth)
    if fan_item is not None:
        out.setdefault("item", fan_item)
        out.setdefault("index", fan_index)
    return out


def _resolve_value(v: Any, outputs, ctx, inputs, fan_item, fan_index, fan_root, depth: int) -> Any:
    if depth > 8:
        return v
    if isinstance(v, str):
        if fan_item is not None and v == "item":
            return fan_item
        if fan_index is not None and v == "index":
            return fan_index
        if v.startswith("$") or _REF_RE.match(v):
            r = resolve_ref(v, outputs, ctx, inputs, fan_item, fan_root)
            return r if r is not None or v.startswith("$") or _REF_RE.match(v) else v
        return v
    if isinstance(v, dict):
        return {k2: _resolve_value(v2, outputs, ctx, inputs, fan_item, fan_index, fan_root, depth + 1) for k2, v2 in v.items()}
    if isinstance(v, list):
        return [_resolve_value(x, outputs, ctx, inputs, fan_item, fan_index, fan_root, depth + 1) for x in v]
    return v


# ----------------------------------------------------------------------------- executor

class Executor:
    def __init__(self, runtime: AgentRuntime | None = None, *, max_parallel: int | None = None, session_factory: Any = None,
                 gate: ApprovalGate | None = None, max_fan_out: int = MAX_FAN_OUT):
        self.runtime = runtime or AgentRuntime()
        self.max_parallel = max(1, int(max_parallel or settings.max_parallel_tasks))
        self.session_factory = session_factory
        self.gate = gate or ApprovalGate()
        self.max_fan_out = max_fan_out
        self.tasks: list[AITask] = []
        self.plan_tasks: dict[str, PlanTask] = {}

    # -- persistence --------------------------------------------------------------------------------------------------
    async def _materialize(self, db: Any, run: AIRun, plan: Plan) -> list[AITask]:
        existing: list[AITask] = []
        try:
            existing = list((await db.execute(select(AITask).where(AITask.run_id == run.id).order_by(AITask.task_key))).scalars().all() or [])
        except Exception as e:  # noqa: BLE001
            log.warning("executor.load_tasks_failed", error=str(e)[:200])
        if not existing:
            existing = [t for t in (getattr(run, "tasks", None) or [])]
        by_key = {t.task_key: t for t in existing}
        for pt in plan.tasks:
            if pt.id in by_key:
                continue
            label = pt.label or get_spec(pt.agent).actions[pt.action].label if pt.agent in _spec_ids() and pt.action in get_spec(pt.agent).actions else (pt.label or f"{pt.agent}.{pt.action}")
            inputs = dict(pt.inputs)
            if pt.budget:
                inputs["_budget"] = pt.budget.model_dump(exclude_none=True)
            if pt.fan_out:
                inputs["_fan_out"] = pt.fan_out
            if pt.optional:
                inputs["_optional"] = True
            row = AITask(id=new_id(), workspace_id=run.workspace_id, run_id=run.id, task_key=pt.id, parent_key=None, agent_id=pt.agent,
                         action=pt.action, label=label, inputs=inputs, depends_on=list(pt.depends_on),
                         requires_approval=pt.requires_approval, status=TaskStatus.pending, tokens_in=0, tokens_out=0, cost_usd=0)
            db.add(row)
            existing.append(row)
            by_key[pt.id] = row
        await ledger.safe_commit(db)
        return existing

    async def _reload(self, db: Any, run: AIRun) -> None:
        try:
            rows = list((await db.execute(select(AITask).where(AITask.run_id == run.id).order_by(AITask.task_key))).scalars().all() or [])
            if rows:
                self.tasks = rows
            await db.refresh(run)
        except Exception as e:  # noqa: BLE001
            log.info("executor.reload_skipped", error=str(e)[:120])

    def _session(self, db: Any, workspace_id: UUID):
        if self.session_factory is not None:
            return self.session_factory(workspace_id)
        from app.core.db import session_scope
        return session_scope(workspace_id)

    # -- cancellation -------------------------------------------------------------------------------------------------
    async def _cancelled(self, db: Any, run: AIRun) -> bool:
        if getattr(run, "cancel_requested", False):
            return True
        try:
            from app.core.redis import get_redis
            flag = await asyncio.wait_for(get_redis().get(f"botwok:run:{run.id}:cancel"), timeout=1.0)
            if flag:
                run.cancel_requested = True
                return True
        except Exception:  # noqa: BLE001 - redis optional
            pass
        return False

    # -- readiness ----------------------------------------------------------------------------------------------------
    def _by_key(self) -> dict[str, AITask]:
        return {t.task_key: t for t in self.tasks}

    def _children(self, key: str) -> list[AITask]:
        return [t for t in self.tasks if t.parent_key == key]

    def _deps_ok(self, t: AITask, by_key: dict[str, AITask]) -> tuple[bool, str | None]:
        """(ready, blocked_reason). Optional failed deps provide null; required failed deps block (skip)."""
        for d in t.depends_on or []:
            dep = by_key.get(d)
            if dep is None:
                return False, f"missing dependency {d}"
            if dep.status == TaskStatus.succeeded:
                continue
            if dep.status in (TaskStatus.failed, TaskStatus.skipped, TaskStatus.cancelled):
                if (dep.inputs or {}).get("_optional"):
                    continue
                return False, f"dependency {d} {dep.status.value}"
            return False, None
        return True, None

    def _runnable(self, t: AITask) -> bool:
        if t.status in (TaskStatus.pending, TaskStatus.ready, TaskStatus.awaiting_approval):
            return True
        if t.status == TaskStatus.running:
            hb = t.heartbeat_at or t.started_at
            if hb is None or datetime.now(UTC) - hb > STALE_HEARTBEAT:
                return True
            log.warning("executor.rerun_running_task", task=t.task_key)
            return True
        return False

    # -- main ---------------------------------------------------------------------------------------------------------
    async def run(self, db: Any, run: AIRun, plan: Plan, ctx: RunContext) -> ExecutionResult:
        self.plan_tasks = {t.id: t for t in plan.tasks}
        self.tasks = await self._materialize(db, run, plan)
        result = ExecutionResult(status="completed")
        for t in self.tasks:
            if t.status == TaskStatus.succeeded and t.output is not None:
                result.outputs[t.task_key] = t.output
        while True:
            if await self._cancelled(db, run):
                for t in self.tasks:
                    if t.status not in DONE:
                        await ledger.task_cancelled(db, t)
                result.status = "cancelled"
                return result
            by_key = self._by_key()
            batch: list[AITask] = []
            for t in self.tasks:
                if not self._runnable(t):
                    continue
                ok, reason = self._deps_ok(t, by_key)
                if reason and not ok:
                    await ledger.task_skipped(db, t, reason)
                    result.errors[t.task_key] = reason
                    continue
                if not ok:
                    continue
                if t.parent_key is None and (t.inputs or {}).get("_fan_out"):
                    children = self._children(t.task_key)
                    if not children:
                        children = await self._fan_out(db, run, t, result.outputs, ctx)
                        if children is None:          # could not resolve → treat task as plain
                            batch.append(t)
                            continue
                    if all(c.status in DONE for c in children):
                        await self._fan_in(db, run, t, children, result)
                    continue
                batch.append(t)
            if not batch:
                break
            batch = batch[: self.max_parallel]
            outcomes: dict[str, TaskOutcome | BaseException] = {}
            sem = asyncio.Semaphore(self.max_parallel)
            async with asyncio.TaskGroup() as tg:
                for t in batch:
                    tg.create_task(self._guarded(db, run, t, ctx, result.outputs, outcomes, sem))
            await self._reload(db, run)
            by_key = self._by_key()
            for key, outcome in outcomes.items():
                t = by_key.get(key)
                if t is None:
                    continue
                if isinstance(outcome, TaskOutcome):
                    result.outputs[key] = outcome.output
                    result.reasoning[key] = outcome.reasoning
                    if outcome.tracker is not None:
                        result.tracker.source_ids.update(outcome.sources)
                        result.tracker.tool_sources.extend(outcome.tracker.tool_sources)
                        result.tracker.urls.update(outcome.tracker.urls)
                elif isinstance(outcome, AwaitingApproval):
                    result.status = "awaiting_approval"
                    result.awaiting = outcome
                    result.awaiting_task_key = key
                    return result
                elif isinstance(outcome, _Pending):
                    result.status = "awaiting_approval"
                    result.awaiting_task_key = key
                    return result
                else:
                    err = getattr(outcome, "error", None) or str(outcome)
                    result.errors[key] = err
                    optional = bool((t.inputs or {}).get("_optional"))
                    if isinstance(outcome, BudgetExceeded):
                        result.status, result.error = "failed", f"budget exceeded at step {t.label}: {err}"
                        optional = False
                    elif isinstance(outcome, CanaryLeakError):
                        result.status, result.error = "failed", f"security: {err}"
                        optional = False
                    elif isinstance(outcome, TaskFailed) and outcome.kind == "cancelled":
                        result.status = "cancelled"
                        return result
                    if not optional and result.status != "failed":
                        result.status, result.error = "failed", f"step '{t.label}' failed: {err}"
            if result.status == "failed":
                for t in self.tasks:
                    if t.status not in DONE and t.status != TaskStatus.awaiting_approval:
                        await ledger.task_skipped(db, t, "run failed")
                return result
        if result.status == "completed" and any(t.status in (TaskStatus.pending, TaskStatus.ready) for t in self.tasks):
            stuck = [t.task_key for t in self.tasks if t.status in (TaskStatus.pending, TaskStatus.ready)]
            result.status, result.error = "failed", f"tasks could not be scheduled: {', '.join(stuck)}"
        return result

    async def _guarded(self, db: Any, run: AIRun, t: AITask, ctx: RunContext, outputs: dict[str, Any],
                       outcomes: dict[str, Any], sem: asyncio.Semaphore) -> None:
        async with sem:
            try:
                outcomes[t.task_key] = await self._run_one(db, run, t, ctx, outputs)
            except (AwaitingApproval, _Pending, BudgetExceeded, TaskFailed, CanaryLeakError) as e:
                outcomes[t.task_key] = e
            except asyncio.CancelledError:
                raise
            except Exception as e:  # noqa: BLE001 - never let one task take the group down
                log.exception("executor.task_crashed", task=t.task_key)
                outcomes[t.task_key] = TaskFailed(f"{type(e).__name__}: {str(e)[:300]}", kind="crash")

    async def _run_one(self, db: Any, run: AIRun, t: AITask, ctx: RunContext, outputs: dict[str, Any]) -> TaskOutcome:
        approval_results: dict[str, Any] = {}
        if t.status == TaskStatus.awaiting_approval or t.requires_approval:
            approval_results, pending = await self.gate.approval_results_for_task(db, run.id, t.id)
            if pending:
                raise _Pending(t.task_key)
        parent = self._by_key().get(t.parent_key) if t.parent_key else None
        fan_root = (parent.inputs or {}).get("_fan_out", "").split(".", 1)[0] if parent is not None else None
        raw_inputs = t.inputs or {}
        inputs = resolve_inputs(raw_inputs, outputs, ctx, fan_item=raw_inputs.get("_item"), fan_index=raw_inputs.get("_index"),
                                fan_root=fan_root if fan_root and fan_root.startswith("t") else None)
        async with self._session(db, run.workspace_id) as tdb:
            task = await tdb.merge(t) if hasattr(tdb, "merge") else t
            await ledger.task_started(tdb, task)
            try:
                outcome = await self.runtime.run_task(tdb, run, task, ctx, inputs=inputs, approval_results=approval_results,
                                                      check_cancel=lambda: self._cancelled(tdb, run))
            except AwaitingApproval as e:
                task.status = TaskStatus.awaiting_approval
                await ledger.safe_commit(tdb)
                raise e
            except (BudgetExceeded, TaskFailed, CanaryLeakError) as e:
                await ledger.task_failed(tdb, run, task, getattr(e, "error", None) or getattr(e, "detail", None) or str(e))
                raise
            await ledger.task_succeeded(tdb, run, task, outcome.output, sources_count=len(outcome.sources))
            if task is not t:
                t.status, t.output, t.finished_at = task.status, task.output, task.finished_at
                t.tokens_in, t.tokens_out, t.cost_usd = task.tokens_in, task.tokens_out, task.cost_usd
            return outcome

    # -- fan-out / fan-in ---------------------------------------------------------------------------------------------
    async def _fan_out(self, db: Any, run: AIRun, t: AITask, outputs: dict[str, Any], ctx: RunContext) -> list[AITask] | None:
        ref = (t.inputs or {}).get("_fan_out")
        items = resolve_ref(ref, outputs, ctx, t.inputs)
        if items is None:
            log.warning("executor.fan_out_unresolved", task=t.task_key, ref=ref)
            return None
        if isinstance(items, dict):
            items = items.get("items") or list(items.values())
        if not isinstance(items, list):
            items = [items]
        if len(items) > self.max_fan_out:
            log.warning("executor.fan_out_truncated", task=t.task_key, n=len(items), cap=self.max_fan_out)
            items = items[: self.max_fan_out]
        children: list[AITask] = []
        base_inputs = {k: v for k, v in (t.inputs or {}).items() if k not in ("_fan_out",)}
        for i, item in enumerate(items):
            child = AITask(id=new_id(), workspace_id=run.workspace_id, run_id=run.id, task_key=f"{t.task_key}.{i + 1}", parent_key=t.task_key,
                           agent_id=t.agent_id, action=t.action, label=f"{t.label} ({i + 1}/{len(items)})",
                           inputs={**base_inputs, "_item": item, "_index": i, "_fan_out_total": len(items)},
                           depends_on=list(t.depends_on or []), requires_approval=t.requires_approval, status=TaskStatus.pending,
                           tokens_in=0, tokens_out=0, cost_usd=0)
            db.add(child)
            children.append(child)
            self.tasks.append(child)
        if not items:
            await ledger.task_succeeded(db, run, t, {"items": []}, sources_count=0)
        await ledger.safe_commit(db)
        return children

    async def _fan_in(self, db: Any, run: AIRun, t: AITask, children: list[AITask], result: ExecutionResult) -> None:
        if t.status in DONE:
            return
        failed = [c for c in children if c.status != TaskStatus.succeeded]
        optional = bool((t.inputs or {}).get("_optional"))
        items = [c.output for c in children if c.status == TaskStatus.succeeded]
        if failed and not optional and not items:
            await ledger.task_failed(db, run, t, f"{len(failed)} of {len(children)} fan-out items failed")
            result.errors[t.task_key] = f"fan-out failed: {[c.task_key for c in failed]}"
            result.status, result.error = "failed", f"step '{t.label}' failed for all items"
            return
        output = {"items": items, "failed": [{"task_key": c.task_key, "error": c.error} for c in failed]}
        t.tokens_in = sum(int(c.tokens_in or 0) for c in children)
        t.tokens_out = sum(int(c.tokens_out or 0) for c in children)
        t.cost_usd = sum(float(c.cost_usd or 0) for c in children)
        await ledger.task_succeeded(db, run, t, output, sources_count=0)
        result.outputs[t.task_key] = output
        for c in children:
            if c.task_key in result.reasoning:
                result.reasoning.setdefault(t.task_key, []).extend(result.reasoning[c.task_key][:2])


class _Pending(Exception):
    """A task is still waiting on a pending approval (resume attempted too early)."""

    def __init__(self, task_key: str):
        super().__init__(f"task {task_key} awaiting approval")
        self.task_key = task_key


def _spec_ids() -> set[str]:
    from app.agents.specs import SPECS
    return set(SPECS)

"""Node executor runtime: ``NodeContext`` (what every executor gets), ``NodeYield`` (pause the run), ``NodeError``.

Executor contract: ``async def run(ctx: NodeContext, config: dict) -> dict``. ``config`` is already rendered over the
run context (templates resolved). Executors are re-run on resume and after crashes, so they must be idempotent per
``(run_id, node_key)``: anything with side effects is recorded in ``ctx.state`` (persisted on the step) and reused —
e.g. an AI run id, an approval id, generated idea ids. To pause, raise :class:`NodeYield` (``waiting`` with a
deadline, or ``awaiting_approval``); the engine persists ``ctx.state`` and re-runs the executor when resumed.
"""
from __future__ import annotations

import json
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import ProblemError
from app.core.logging import get_logger
from app.models.enums import ROLE_RANK, MemberRole
from app.workflows.expressions import ExpressionError, compile_expression, render_value

log = get_logger("automation.nodes")

AI_POLL = timedelta(minutes=5)
APPROVAL_POLL = timedelta(minutes=30)
STALE_QUEUED = timedelta(minutes=2)


def utcnow() -> datetime:
    return datetime.now(UTC)


def parse_dt(v: Any) -> datetime | None:
    if v is None or v == "":
        return None
    if isinstance(v, datetime):
        return v if v.tzinfo else v.replace(tzinfo=UTC)
    s = str(v).strip()
    if s.endswith("Z"):
        s = s[:-1] + "+00:00"
    try:
        dt = datetime.fromisoformat(s)
    except ValueError as e:
        raise NodeError(f"invalid date/time {v!r}") from e
    return dt if dt.tzinfo else dt.replace(tzinfo=UTC)


def jsonable(value: Any) -> Any:
    from app.services.audit_service import jsonable as _j
    return _j(value)


def as_uuid(v: Any, what: str = "id") -> UUID:
    if isinstance(v, UUID):
        return v
    if isinstance(v, dict) and v.get("id"):
        v = v["id"]
    try:
        return UUID(str(v).strip())
    except (TypeError, ValueError, AttributeError) as e:
        raise NodeError(f"{what} is missing or not a valid id ({v!r})") from e


def as_uuid_list(v: Any, what: str = "ids") -> list[UUID]:
    if v is None or v == "":
        return []
    if isinstance(v, str) and "," in v:
        v = [x for x in v.split(",") if x.strip()]
    items = v if isinstance(v, list | tuple) else [v]
    return [as_uuid(x, what) for x in items if x not in (None, "")]


class NodeError(Exception):
    """A step failure with a readable message (stored on the step; the workflow's on_error policy applies)."""

    def __init__(self, message: str, details: Any = None) -> None:
        super().__init__(message)
        self.message = message
        self.details = details


class NodeYield(Exception):  # noqa: N818 - control flow, not an error
    """Pause the run: ``status`` is ``waiting`` (resume at ``until`` or on an event) or ``awaiting_approval``."""

    def __init__(self, status: str, *, reason: str, until: datetime | None = None, approval_id: UUID | str | None = None,
                 info: dict[str, Any] | None = None) -> None:
        super().__init__(reason)
        assert status in ("waiting", "awaiting_approval")
        self.status = status
        self.reason = reason
        self.until = until
        self.approval_id = str(approval_id) if approval_id else None
        self.info = info or {}


def problem_message(e: BaseException) -> str:
    if isinstance(e, ProblemError):
        msg = f"{e.title}: {e.detail}" if e.detail and e.detail != e.title else e.title
        if e.errors:
            msg += " — " + "; ".join(str(x.get("message") or x) for x in e.errors[:5])
        return msg
    if isinstance(e, NodeError | ExpressionError):
        return str(e)
    return f"{type(e).__name__}: {str(e)[:500]}"


@dataclass
class AutomationActor:
    """The identity automation steps act as: the workflow's owner with their *current* workspace role (duck-types
    ``app.api.deps.Member``: ``.user``, ``.workspace_id``, ``.role``, ``.has()``)."""

    user: Any
    workspace_id: UUID
    role: MemberRole
    workflow_id: UUID | None = None
    run_id: UUID | None = None

    def has(self, role: str) -> bool:
        return ROLE_RANK[self.role.value] >= ROLE_RANK[role]

    @property
    def user_id(self) -> UUID:
        return self.user.id

    @property
    def event_actor(self) -> dict[str, Any]:
        return {"type": "system", "id": f"automation:{self.workflow_id}", "on_behalf_of": str(self.user.id)}

    @property
    def audit_actor(self) -> Any:
        return self

    @property
    def requested_by(self) -> str:
        return f"automation:{self.workflow_id}"


Callback = Callable[[], Awaitable[Any]]


@dataclass
class NodeContext:
    db: AsyncSession
    run: Any                       # AutomationRun
    workflow: Any                  # AutomationWorkflow
    node_key: str
    node_type: str
    label: str | None
    step: Any                      # AutomationRunStep
    actor: AutomationActor | None
    scope: dict[str, Any]
    state: dict[str, Any]
    dry_run: bool = False
    commit: Callable[[], Awaitable[None]] | None = None      # engine checkpoint (commit + post-commit callbacks)
    post_commit: list[Callback] = field(default_factory=list)
    add_run_cost: Callable[[float], None] | None = None

    # -- identity / scope --------------------------------------------------------------------------------------------
    @property
    def workspace_id(self) -> UUID:
        return self.run.workspace_id

    @property
    def brand_id(self) -> UUID | None:
        return self.workflow.brand_id

    @property
    def brand(self) -> dict[str, Any] | None:
        return self.scope.get("brand")

    def require_actor(self) -> AutomationActor:
        if self.actor is None:
            raise NodeError("the workflow owner is no longer a member of this workspace; reassign the workflow")
        return self.actor

    def require_brand(self) -> UUID:
        if self.brand_id is None:
            raise NodeError("this node needs the workflow to be attached to a brand")
        return self.brand_id

    def render(self, value: Any) -> Any:
        return render_value(value, {**self.scope, "now": utcnow().isoformat()})

    def evaluate(self, expression: str) -> Any:
        return compile_expression(expression).evaluate({**self.scope, "now": utcnow().isoformat()})

    def simulated(self, **info: Any) -> dict[str, Any]:
        return {"simulated": True, "dry_run": True, **jsonable(info)}

    # -- persistence -------------------------------------------------------------------------------------------------
    def defer(self, fn: Callback) -> None:
        """Run ``fn`` after the next successful commit (e.g. enqueue a job that must see committed rows)."""
        self.post_commit.append(fn)

    async def checkpoint(self) -> None:
        """Persist ``state`` on the step and commit now (use before/after non-transactional side effects)."""
        self.step.output = jsonable({**(self.step.output or {}), "_state": self.state})
        if self.commit is not None:
            await self.commit()

    def add_cost(self, amount: float | None, key: str) -> None:
        """Book a cost on the run exactly once per ``key`` (idempotent across resumes)."""
        if not amount:
            return
        booked = self.state.setdefault("costs", {})
        if key in booked:
            return
        booked[key] = round(float(amount), 6)
        if self.add_run_cost is not None:
            self.add_run_cost(float(amount))

    def remaining_budget(self, requested: float | None) -> float | None:
        cap = (self.workflow.settings or {}).get("max_cost_usd")
        if cap is None:
            return requested
        left = float(cap) - float(self.run.cost_usd or 0)
        if left <= 0:
            raise NodeError(f"the workflow's cost budget (${float(cap):.2f}) is exhausted")
        return min(left, requested) if requested else left

    # -- AI runs ------------------------------------------------------------------------------------------------------
    async def ai_runs(self, specs: dict[str, dict[str, Any]], *, timeout_minutes: int = 60) -> dict[str, dict[str, Any]]:
        """Start (once) and await several AI tool-mode runs: ``{label: {agent, action, inputs, message?, budget_usd?}}``.
        Returns ``{label: ai_run.result}`` when all completed; raises NodeYield while any is in progress and NodeError
        when one failed. Runs are created with ``automation_run_id`` so AI_RUN_COMPLETED resumes this run."""
        from app.agents.orchestrator.service import AIService
        from app.models.ai import AIRun
        actor = self.require_actor()
        runs: dict[str, str] = self.state.setdefault("ai_runs", {})
        created = False
        for label, spec in specs.items():
            if label in runs:
                continue
            budget = self.remaining_budget(spec.get("budget_usd"))
            try:
                run = await AIService().create_run(
                    self.db, actor, message=str(spec.get("message") or f"{spec['agent']}.{spec['action']}")[:4000],
                    brand_id=self.brand_id, mode="tool", agent=spec["agent"], action=spec["action"],
                    inputs=jsonable(spec.get("inputs") or {}), budget_usd=budget, automation_run_id=self.run.id,
                    enqueue=False)
            except ProblemError as e:
                raise NodeError(f"could not start AI {spec['agent']}.{spec['action']}: {problem_message(e)}") from e
            runs[label] = str(run.id)
            self.state.setdefault("ai_started", {})[label] = utcnow().isoformat()
            if self.step.ai_run_id is None:
                self.step.ai_run_id = run.id
            self.defer(_enqueue_ai(run.id, self.workspace_id))
            created = True
        if created:
            await self.checkpoint()
        results: dict[str, dict[str, Any]] = {}
        pending: list[str] = []
        for label, rid in runs.items():
            if label not in specs:
                continue
            airun = (await self.db.execute(
                _select_airun(AIRun, UUID(rid)).execution_options(populate_existing=True))).scalar_one_or_none()
            if airun is None:
                raise NodeError(f"AI run {rid} no longer exists")
            status = getattr(airun.status, "value", airun.status)
            if status == "completed":
                self.add_cost(float(airun.cost_usd or 0), f"ai:{rid}")
                results[label] = {**(airun.result or {}), "ai_run_id": rid, "cost_usd": float(airun.cost_usd or 0)}
                continue
            if status in ("failed", "cancelled"):
                self.add_cost(float(airun.cost_usd or 0), f"ai:{rid}")
                spec = specs[label]
                raise NodeError(f"AI {spec['agent']}.{spec['action']} {status}: {(airun.error or 'no details')[:300]}",
                                {"ai_run_id": rid})
            started = parse_dt((self.state.get("ai_started") or {}).get(label)) or utcnow()
            if utcnow() - started > timedelta(minutes=timeout_minutes):
                raise NodeError(f"AI run {rid} did not finish within {timeout_minutes} minutes", {"ai_run_id": rid})
            if status == "queued" and airun.queued_at and utcnow() - airun.queued_at > STALE_QUEUED:
                self.defer(_enqueue_ai(airun.id, self.workspace_id))     # self-heal a lost job (queueing lock dedups)
            pending.append(rid)
        if pending:
            raise NodeYield("waiting", reason="ai_run", until=utcnow() + AI_POLL, info={"ai_run_ids": pending})
        return results

    async def ai_run(self, label: str, *, agent: str, action: str, inputs: dict[str, Any], message: str | None = None,
                     budget_usd: float | None = None, timeout_minutes: int = 60) -> dict[str, Any]:
        res = await self.ai_runs({label: {"agent": agent, "action": action, "inputs": inputs, "message": message,
                                          "budget_usd": budget_usd}}, timeout_minutes=timeout_minutes)
        return res[label]


def _select_airun(model: Any, rid: UUID) -> Any:
    from sqlalchemy import select
    return select(model).where(model.id == rid)


def _enqueue_ai(run_id: UUID, workspace_id: UUID) -> Callback:
    async def go() -> None:
        try:
            from app.agents.orchestrator.service import enqueue_job
            await enqueue_job("jobs.ai.run", run_id, workspace_id)
        except Exception as e:  # noqa: BLE001 - the AI step's poll re-enqueues stale queued runs
            log.warning("automation.ai_enqueue_failed", ai_run_id=str(run_id), error=str(e)[:200])
    return go


def deliverable(result: dict[str, Any]) -> Any:
    """The main output of a tool-mode AI run (single task ``t1``) or all deliverables."""
    d = (result or {}).get("deliverables") or {}
    if "t1" in d:
        return d["t1"]
    if len(d) == 1:
        return next(iter(d.values()))
    return d or None


def truncate_json(value: Any, limit: int = 200_000) -> Any:
    try:
        size = len(json.dumps(value, default=str))
    except (TypeError, ValueError):
        return {"_unserializable": True}
    if size <= limit:
        return value
    if isinstance(value, dict):
        return {"_truncated": True, "size": size, "keys": list(value)[:50]}
    return {"_truncated": True, "size": size}

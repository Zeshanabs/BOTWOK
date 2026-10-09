"""AutomationEngine (doc 14 §14.3–14.4): workflow definitions, runs, and the resumable per-step state machine.

Execution model
* ``start`` creates ``automation_runs(status=running)`` with context ``{trigger, brand, workspace, env, steps}`` and a
  pinned snapshot of the definition (``context._workflow``), records the trigger step, emits AUTOMATION_TRIGGERED,
  commits, then enqueues ``jobs.automation.execute`` (queueing lock ``automation:{workflow_id}``; one active run per
  workflow unless ``settings.concurrency == "parallel"``).
* ``execute`` (under a per-run advisory lock) re-checks yielded steps, then repeatedly runs every *ready* node — all
  forward in-edges resolved and at least one active (edge branch matches the source's output branch, ``error`` edges
  are active when the source failed); nodes whose in-edges are all inactive are ``skipped`` (dead-path elimination).
  Back edges (bounded ``wait`` loops) reset the loop body for another iteration. Steps are checkpointed (committed)
  before and after each node; executors are idempotent per ``(run_id, node_key)`` through ``step.output._state``.
* Yields: AI/research nodes → ``waiting`` (resumed by AI_RUN_COMPLETED/RESEARCH_COMPLETED consumers or the poll),
  ``approve``/``schedule``/``publish`` → ``awaiting_approval`` (resumed by ``on_approval_decided``), ``wait`` →
  ``waiting`` + ``waiting_until`` (resumed by ``triggers.dispatch_waiting``). ``waiting_until`` is also a lease for
  ``running`` runs so a lost job is re-enqueued.
* Errors: an outgoing ``error`` edge handles the failure; otherwise ``on_error`` (node or workflow setting):
  ``stop`` → run failed + AUTOMATION_FAILED + notify the owner, ``notify`` → same + workspace notification,
  ``continue`` → keep running other branches, run ends ``failed``.
* ``dry_run``: AI/research/generate/transform/analytics run; side-effect nodes (approve, schedule, publish, webhook,
  notification, action, wait) are simulated.
"""
from __future__ import annotations

import asyncio
import base64
import hashlib
import hmac
import secrets
from collections.abc import AsyncIterator, Awaitable, Callable
from contextlib import asynccontextmanager
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import UUID

from sqlalchemy import and_, delete, event, func, or_, select, text, update
from sqlalchemy.exc import InvalidRequestError
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.core.db import set_workspace
from app.core.errors import ProblemError, conflict, forbidden, not_found, validation
from app.core.events import emit
from app.core.ids import new_id
from app.core.logging import get_logger
from app.core.pagination import decode_cursor, encode_cursor
from app.models.brand import Brand
from app.models.enums import AccountStatus, ApprovalStatus, AutomationStatus
from app.models.identity import User, Workspace, WorkspaceMember
from app.models.platform import (
    Approval,
    AutomationRun,
    AutomationRunStep,
    AutomationWorkflow,
    WorkflowEdge,
    WorkflowNode,
)
from app.models.social import SocialAccount
from app.workflows import cron
from app.workflows.catalog import NODE_TYPES, TRIGGER_TYPES
from app.workflows.expressions import ExpressionError, render_value
from app.workflows.graph import Edge, Graph
from app.workflows.nodes import get_executor
from app.workflows.nodes.base import (
    AutomationActor,
    NodeContext,
    NodeError,
    NodeYield,
    jsonable,
    parse_dt,
    problem_message,
    truncate_json,
    utcnow,
)
from app.workflows.validation import (
    normalize_definition,
    raise_if_invalid,
    schema_errors,
    validate_definition,
)

log = get_logger("automation.engine")

EXECUTE_TASK = "jobs.automation.execute"
ACTIVE = (AutomationStatus.running, AutomationStatus.waiting, AutomationStatus.awaiting_approval)
TERMINAL = (AutomationStatus.succeeded, AutomationStatus.failed, AutomationStatus.cancelled)
STEP_TERMINAL = {"succeeded", "failed", "skipped"}
STEP_OPEN = {"waiting", "awaiting_approval"}
LEASE = timedelta(minutes=10)
MAX_EXECUTIONS = 500
MAX_CRASH_ATTEMPTS = 3
PUBLIC_SETTINGS = ("on_error", "max_cost_usd", "timeout_minutes", "concurrency", "notify_user_ids")
_tasks: set[asyncio.Task[Any]] = set()
_open_lock: asyncio.Lock | None = None


# ============================================================================================ queue helpers

async def _defer(cfg: dict[str, Any], **kwargs: Any) -> None:
    global _open_lock
    from procrastinate import exceptions as pexc

    from app.workers.app import procrastinate_app
    try:
        await procrastinate_app.configure_task(name=EXECUTE_TASK, **cfg).defer_async(**kwargs)
    except pexc.AppNotOpen:
        if _open_lock is None:
            _open_lock = asyncio.Lock()
        async with _open_lock:
            try:
                await procrastinate_app.open_async()
            except Exception as e:  # noqa: BLE001 - already open from another coroutine
                log.debug("queue.open_failed", error=str(e)[:200])
        await procrastinate_app.configure_task(name=EXECUTE_TASK, **cfg).defer_async(**kwargs)


async def enqueue_execute(run_id: UUID | str, workspace_id: UUID | str, workflow_id: UUID | str | None = None, *,
                          exclusive: bool = True, delay_s: int | None = None) -> bool:
    """Enqueue ``jobs.automation.execute``. Queueing lock ``automation:{workflow_id}`` (one queued execution per
    workflow); if that lock is held by another queued job, fall back to a per-run lock. Procrastinate ``lock``
    ``automation-run:{run_id}`` serializes executions of the same run. Returns False only on infrastructure failure."""
    from procrastinate import exceptions as pexc
    base: dict[str, Any] = {"queue": "automation", "lock": f"automation-run:{run_id}"}
    if delay_s:
        base["schedule_in"] = {"seconds": int(delay_s)}
    locks = ([f"automation:{workflow_id}"] if exclusive and workflow_id else []) + [f"automation:{workflow_id}:{run_id}"]
    try:
        for lk in locks:
            try:
                await _defer({**base, "queueing_lock": lk}, run_id=str(run_id), workspace_id=str(workspace_id))
                return True
            except pexc.AlreadyEnqueued:
                continue
        return True       # an execution of this run is already queued
    except Exception as e:  # noqa: BLE001 - dispatch_waiting re-enqueues when the lease expires
        log.warning("automation.enqueue_failed", run_id=str(run_id), error=str(e)[:300])
        return False


def after_commit(db: AsyncSession, fn: Callable[[], Awaitable[Any]]) -> None:
    """Schedule ``fn`` (coroutine factory) to run once the session's current transaction commits."""
    sync = db.sync_session
    pending: list[Callable[[], Awaitable[Any]]] = sync.info.setdefault("automation_after_commit", [])
    pending.append(fn)
    if sync.info.get("automation_after_commit_hooked"):
        return
    sync.info["automation_after_commit_hooked"] = True

    def _fire(session: Any) -> None:
        fns = list(session.info.get("automation_after_commit", []))
        session.info["automation_after_commit"] = []
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            return
        for f in fns:
            t = loop.create_task(f())
            _tasks.add(t)
            t.add_done_callback(_tasks.discard)

    def _clear(session: Any, *a: Any) -> None:
        session.info["automation_after_commit"] = []

    event.listen(sync, "after_commit", _fire)
    event.listen(sync, "after_rollback", _clear)


@asynccontextmanager
async def _run_lock(run_id: UUID, wait_s: float = 20.0) -> AsyncIterator[bool]:
    """Postgres advisory lock on a dedicated connection: one executor per run at a time."""
    from app.core.db import engine as sa_engine
    key = int.from_bytes(hashlib.sha256(f"automation-run:{run_id}".encode()).digest()[:8], "big", signed=True)
    conn = await sa_engine.connect()
    got = False
    try:
        waited = 0.0
        while True:
            got = bool((await conn.execute(text("SELECT pg_try_advisory_lock(:k)"), {"k": key})).scalar())
            await conn.commit()
            if got or waited >= wait_s:
                break
            await asyncio.sleep(0.5)
            waited += 0.5
        yield got
    finally:
        try:
            if got:
                await conn.execute(text("SELECT pg_advisory_unlock(:k)"), {"k": key})
                await conn.commit()
        except Exception:  # noqa: BLE001 - drop the connection so the session lock dies with it
            await conn.invalidate()
        await conn.close()


# ============================================================================================ small helpers

def _key() -> bytes:
    return hashlib.sha256(f"{settings.botwok_master_key}:{settings.jwt_secret}".encode()).digest()


def _public_settings(s: dict[str, Any] | None) -> dict[str, Any]:
    return {k: v for k, v in (s or {}).items() if k in PUBLIC_SETTINGS}


def _status(v: Any) -> str:
    return getattr(v, "value", v)


async def load_actor(db: AsyncSession, wf: AutomationWorkflow, run: AutomationRun | None = None) -> AutomationActor | None:
    user = await db.get(User, wf.created_by)
    if user is None or not getattr(user, "is_active", True):
        return None
    role = (await db.execute(select(WorkspaceMember.role).where(WorkspaceMember.workspace_id == wf.workspace_id,
                                                                WorkspaceMember.user_id == user.id))).scalar_one_or_none()
    if role is None:
        return None
    return AutomationActor(user=user, workspace_id=wf.workspace_id, role=role, workflow_id=wf.id,
                           run_id=run.id if run else None)


async def brand_context(db: AsyncSession, brand_id: UUID | None) -> dict[str, Any] | None:
    if brand_id is None:
        return None
    b = await db.get(Brand, brand_id)
    if b is None:
        return None
    accounts = (await db.execute(select(SocialAccount).where(SocialAccount.brand_id == b.id,
                                                             SocialAccount.status == AccountStatus.active)
                                 .order_by(SocialAccount.created_at))).scalars().all()
    defaults: dict[str, str] = {}
    for a in accounts:
        defaults.setdefault(_status(a.platform), str(a.id))
    return jsonable({"id": b.id, "name": b.name, "industry": b.industry, "sub_industry": b.sub_industry,
                     "website": b.website, "timezone": b.timezone or "UTC", "languages": b.languages or [],
                     "geography": b.geography or [], "description": b.description, "default_accounts": defaults,
                     "accounts": [{"id": a.id, "platform": _status(a.platform), "name": a.display_name,
                                   "handle": a.handle} for a in accounts]})


def _trigger_node(nodes: list[dict[str, Any]]) -> dict[str, Any] | None:
    return next((n for n in nodes if str(n.get("type")) in TRIGGER_TYPES), None)


def trigger_summary(node: dict[str, Any] | None, brand_tz: str | None = None) -> str | None:
    if node is None:
        return None
    cfg = node.get("config") or {}
    t = node.get("type")
    if t == "trigger.cron":
        return cron.describe(cfg, brand_tz)
    if t == "trigger.event":
        flt = cfg.get("filter") or {}
        extra = ", ".join(f"{k}={v}" for k, v in flt.items()) if isinstance(flt, dict) else ""
        return f"When {cfg.get('event')}" + (f" ({extra})" if extra else "") + (" if " + cfg["condition"] if cfg.get("condition") else "")
    if t == "trigger.webhook":
        return "On webhook call"
    return "Manual"


def _cursor_filter(q: Any, cursor: str | None, col: Any, id_col: Any) -> Any:
    if not cursor:
        return q
    try:
        c = decode_cursor(cursor) or {}
        t = datetime.fromisoformat(c["t"])
        cid = UUID(c["id"])
    except (ValueError, KeyError, TypeError) as e:
        raise validation("Invalid cursor") from e
    return q.where(or_(col < t, and_(col == t, id_col < cid)))


# ============================================================================================ engine

class AutomationEngine:
    # ------------------------------------------------------------------------------------------ secrets
    @staticmethod
    def webhook_secret(wf: AutomationWorkflow) -> str:
        nonce = (wf.settings or {}).get("_webhook_nonce") or ""
        mac = hmac.new(_key(), f"automation-webhook:{wf.id}:{nonce}".encode(), hashlib.sha256).digest()
        return base64.urlsafe_b64encode(mac[:24]).decode().rstrip("=")

    @staticmethod
    def verify_webhook_secret(wf: AutomationWorkflow, provided: str) -> bool:
        return hmac.compare_digest(AutomationEngine.webhook_secret(wf).encode(), (provided or "").encode())

    @staticmethod
    def signing_secret(wf: AutomationWorkflow) -> str:
        mac = hmac.new(_key(), f"automation-signing:{wf.id}".encode(), hashlib.sha256).digest()
        return "whsec_" + base64.urlsafe_b64encode(mac[:24]).decode().rstrip("=")

    # ------------------------------------------------------------------------------------------ queries
    @staticmethod
    async def get(db: AsyncSession, workspace_id: UUID, workflow_id: Any, *, for_update: bool = False) -> AutomationWorkflow:
        try:
            wid = UUID(str(workflow_id))
        except ValueError as e:
            raise not_found("Automation") from e
        q = select(AutomationWorkflow).where(AutomationWorkflow.id == wid, AutomationWorkflow.workspace_id == workspace_id)
        if for_update:
            q = q.with_for_update()
        wf = (await db.execute(q)).scalar_one_or_none()
        if wf is None:
            raise not_found("Automation")
        return wf

    @staticmethod
    async def definition(db: AsyncSession, wf: AutomationWorkflow) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
        nodes = (await db.execute(select(WorkflowNode).where(WorkflowNode.workflow_id == wf.id)
                                  .order_by(WorkflowNode.key))).scalars().all()
        edges = (await db.execute(select(WorkflowEdge).where(WorkflowEdge.workflow_id == wf.id)
                                  .order_by(WorkflowEdge.from_node_key, WorkflowEdge.to_node_key))).scalars().all()
        return ([{"key": n.key, "type": n.type, "config": n.config or {}, "label": n.label, "position": n.position}
                 for n in nodes],
                [{"from": e.from_node_key, "to": e.to_node_key, "branch": e.branch, "condition": e.condition} for e in edges])

    @staticmethod
    async def list_workflows(db: AsyncSession, workspace_id: UUID, *, brand_id: UUID | None = None, status: str | None = None,
                             limit: int = 50, cursor: str | None = None) -> tuple[list[AutomationWorkflow], str | None]:
        q = select(AutomationWorkflow).where(AutomationWorkflow.workspace_id == workspace_id)
        if brand_id:
            q = q.where(AutomationWorkflow.brand_id == brand_id)
        q = q.where(AutomationWorkflow.status == status) if status else q.where(AutomationWorkflow.status != "archived")
        q = _cursor_filter(q, cursor, AutomationWorkflow.created_at, AutomationWorkflow.id)
        rows = list((await db.execute(q.order_by(AutomationWorkflow.created_at.desc(), AutomationWorkflow.id.desc())
                                      .limit(limit + 1))).scalars())
        nxt = None
        if len(rows) > limit:
            rows = rows[:limit]
            nxt = encode_cursor({"t": rows[-1].created_at.isoformat(), "id": str(rows[-1].id)})
        return rows, nxt

    @staticmethod
    async def list_runs(db: AsyncSession, workspace_id: UUID, workflow_id: UUID, *, status: str | None = None, limit: int = 50,
                        cursor: str | None = None) -> tuple[list[AutomationRun], str | None]:
        q = select(AutomationRun).where(AutomationRun.workspace_id == workspace_id, AutomationRun.workflow_id == workflow_id)
        if status:
            try:
                q = q.where(AutomationRun.status == AutomationStatus(status))
            except ValueError as e:
                raise validation(f"invalid status {status!r}") from e
        q = _cursor_filter(q, cursor, AutomationRun.started_at, AutomationRun.id)
        rows = list((await db.execute(q.order_by(AutomationRun.started_at.desc(), AutomationRun.id.desc())
                                      .limit(limit + 1))).scalars())
        nxt = None
        if len(rows) > limit:
            rows = rows[:limit]
            nxt = encode_cursor({"t": rows[-1].started_at.isoformat(), "id": str(rows[-1].id)})
        return rows, nxt

    @staticmethod
    async def get_run(db: AsyncSession, workspace_id: UUID, run_id: Any, *, for_update: bool = False) -> AutomationRun:
        try:
            rid = UUID(str(run_id))
        except ValueError as e:
            raise not_found("Automation run") from e
        q = select(AutomationRun).where(AutomationRun.id == rid, AutomationRun.workspace_id == workspace_id)
        if for_update:
            q = q.with_for_update()
        run = (await db.execute(q.execution_options(populate_existing=True))).scalar_one_or_none()
        if run is None:
            raise not_found("Automation run")
        return run

    @staticmethod
    async def steps(db: AsyncSession, run: AutomationRun) -> list[AutomationRunStep]:
        rows = (await db.execute(select(AutomationRunStep).where(AutomationRunStep.run_id == run.id)
                                 .execution_options(populate_existing=True))).scalars().all()
        return sorted(rows, key=lambda s: (s.started_at or s.finished_at or datetime.max.replace(tzinfo=UTC), s.node_key))

    # ------------------------------------------------------------------------------------------ save / lifecycle
    @classmethod
    async def save(cls, db: AsyncSession, member: Any, workflow_id: Any, definition: dict[str, Any]) -> AutomationWorkflow:
        """Create (``workflow_id=None``) or replace a workflow definition: validate, bump version, store nodes/edges."""
        if not member.has("admin"):
            raise forbidden("Editing automations requires admin or owner")
        nodes, edges = normalize_definition(definition.get("nodes") or [], definition.get("edges") or [])
        wf = await cls.get(db, member.workspace_id, workflow_id, for_update=True) if workflow_id else None
        if wf is not None and wf.status == "archived":
            raise conflict("automation_archived", "Archived automations cannot be edited")
        autonomous = definition.get("autonomous_actions_enabled")
        if autonomous is None:
            autonomous = bool(wf.autonomous_actions_enabled) if wf else False
        user_settings = definition.get("settings")
        merged = {**_public_settings(wf.settings if wf else {}),
                  **(_public_settings(user_settings) if isinstance(user_settings, dict) else {})}
        if isinstance(user_settings, dict):
            unknown = sorted(set(user_settings) - set(PUBLIC_SETTINGS))
            if unknown:
                raise validation(f"unknown settings: {', '.join(unknown)}",
                                 [{"node_key": None, "message": f"unknown setting {k!r}", "code": "invalid_settings"}
                                  for k in unknown])
        raise_if_invalid(validate_definition(nodes, edges, autonomous_actions_enabled=bool(autonomous), settings=merged))
        name = (definition.get("name") or (wf.name if wf else "") or "").strip()
        if not name:
            raise validation("name is required", [{"node_key": None, "message": "name is required", "code": "required"}])
        brand_id = definition.get("brand_id", wf.brand_id if wf else None)
        if brand_id is not None:
            brand_id = UUID(str(brand_id))
            ok = (await db.execute(select(Brand.id).where(Brand.id == brand_id, Brand.workspace_id == member.workspace_id)))\
                .scalar_one_or_none()
            if ok is None:
                raise validation("brand_id does not belong to this workspace")
        internal = {k: v for k, v in ((wf.settings if wf else {}) or {}).items() if k.startswith("_")}
        internal.setdefault("_webhook_nonce", secrets.token_urlsafe(9))
        before = cls.audit_snapshot(wf) if wf else None
        if wf is None:
            wf = AutomationWorkflow(id=new_id(), workspace_id=member.workspace_id, brand_id=brand_id, name=name[:200],
                                    description=definition.get("description"), status="draft", version=1,
                                    autonomous_actions_enabled=bool(autonomous), settings={**merged, **internal},
                                    created_by=member.user.id)
            db.add(wf)
            await db.flush()
        else:
            wf.version = int(wf.version or 1) + 1
            wf.name = name[:200]
            if "description" in definition:
                wf.description = definition.get("description")
            wf.brand_id = brand_id
            wf.autonomous_actions_enabled = bool(autonomous)
            wf.settings = {**merged, **internal}
            await db.execute(delete(WorkflowEdge).where(WorkflowEdge.workflow_id == wf.id))
            await db.execute(delete(WorkflowNode).where(WorkflowNode.workflow_id == wf.id))
        for n in nodes:
            db.add(WorkflowNode(workspace_id=wf.workspace_id, workflow_id=wf.id, key=n["key"], type=n["type"],
                                label=n.get("label"), config=jsonable(n.get("config") or {}),
                                position=jsonable(n.get("position") or {"x": 0, "y": 0})))
        for e in edges:
            db.add(WorkflowEdge(workspace_id=wf.workspace_id, workflow_id=wf.id, from_node_key=e["from"], to_node_key=e["to"],
                                branch=e.get("branch"), condition=e.get("condition")))
        brand = await db.get(Brand, brand_id) if brand_id else None
        trig = _trigger_node(nodes)
        wf.trigger_summary = trigger_summary(trig, brand.timezone if brand else None)
        wf.next_run_at = cls._next_run(trig, brand.timezone if brand else None) if wf.status == "active" else None
        wf.updated_at = utcnow()
        await db.flush()
        await cls._audit(db, member, "automation.create" if before is None else "automation.update", wf,
                         before=before, after=cls.audit_snapshot(wf))
        if before is not None and before.get("autonomous_actions_enabled") != wf.autonomous_actions_enabled:
            await cls._audit(db, member, "automation.autonomous_actions", wf,
                             before={"enabled": before.get("autonomous_actions_enabled")},
                             after={"enabled": wf.autonomous_actions_enabled})
        return wf

    @staticmethod
    def _next_run(trig: dict[str, Any] | None, brand_tz: str | None, after: datetime | None = None) -> datetime | None:
        if not trig or trig.get("type") != "trigger.cron":
            return None
        try:
            return cron.next_run_at(trig.get("config") or {}, after or utcnow(), brand_tz)
        except cron.CronError:
            return None

    @staticmethod
    def audit_snapshot(wf: AutomationWorkflow | None) -> dict[str, Any] | None:
        if wf is None:
            return None
        return {"name": wf.name, "status": wf.status, "version": wf.version, "brand_id": str(wf.brand_id) if wf.brand_id else None,
                "autonomous_actions_enabled": wf.autonomous_actions_enabled, "settings": _public_settings(wf.settings),
                "trigger_summary": wf.trigger_summary}

    @staticmethod
    async def _audit(db: AsyncSession, member: Any, action: str, wf: AutomationWorkflow, *, target_type: str = "automation",
                     target_id: Any = None, before: Any = None, after: Any = None) -> None:
        try:
            from app.services.audit_service import audit
            async with db.begin_nested():
                await audit(db, member, action, target_type, target_id or wf.id, before=before, after=after)
        except Exception as e:  # noqa: BLE001 - auditing never breaks the mutation
            log.warning("automation.audit_failed", action=action, error=str(e)[:200])

    @classmethod
    async def enable(cls, db: AsyncSession, member: Any, workflow_id: Any) -> AutomationWorkflow:
        if not member.has("admin"):
            raise forbidden("Enabling automations requires admin or owner")
        wf = await cls.get(db, member.workspace_id, workflow_id, for_update=True)
        if wf.status == "archived":
            raise conflict("automation_archived", "Archived automations cannot be enabled")
        nodes, edges = await cls.definition(db, wf)
        raise_if_invalid(validate_definition(nodes, edges, autonomous_actions_enabled=wf.autonomous_actions_enabled,
                                             settings=_public_settings(wf.settings)))
        if await load_actor(db, wf) is None:
            raise conflict("automation_owner_missing", "The automation's owner is no longer a member; re-save it as an admin")
        before = wf.status
        wf.status = "active"
        brand = await db.get(Brand, wf.brand_id) if wf.brand_id else None
        wf.next_run_at = cls._next_run(_trigger_node(nodes), brand.timezone if brand else None)
        wf.updated_at = utcnow()
        await db.flush()
        await cls._audit(db, member, "automation.enable", wf, before={"status": before}, after={"status": "active"})
        return wf

    @classmethod
    async def disable(cls, db: AsyncSession, member: Any, workflow_id: Any) -> AutomationWorkflow:
        if not member.has("admin"):
            raise forbidden("Disabling automations requires admin or owner")
        wf = await cls.get(db, member.workspace_id, workflow_id, for_update=True)
        if wf.status == "archived":
            raise conflict("automation_archived", "Archived automations cannot be changed")
        before = wf.status
        wf.status = "paused"
        wf.next_run_at = None
        wf.updated_at = utcnow()
        await db.flush()
        await cls._audit(db, member, "automation.disable", wf, before={"status": before}, after={"status": "paused"})
        return wf

    @classmethod
    async def delete(cls, db: AsyncSession, member: Any, workflow_id: Any) -> str:
        """Cancel active runs; hard-delete a never-run workflow, otherwise archive it (run history is kept)."""
        if not member.has("admin"):
            raise forbidden("Deleting automations requires admin or owner")
        wf = await cls.get(db, member.workspace_id, workflow_id, for_update=True)
        active = (await db.execute(select(AutomationRun.id).where(AutomationRun.workflow_id == wf.id,
                                                                 AutomationRun.status.in_(ACTIVE)))).scalars().all()
        for rid in active:
            await cls.cancel(db, member, rid, reason="automation deleted")
        n = (await db.execute(select(func.count()).select_from(AutomationRun).where(AutomationRun.workflow_id == wf.id))).scalar_one()
        await cls._audit(db, member, "automation.delete", wf, before=cls.audit_snapshot(wf), after={"archived": bool(n)})
        if n:
            wf.status = "archived"
            wf.next_run_at = None
            await db.flush()
            return "archived"
        await db.delete(wf)
        await db.flush()
        return "deleted"

    # ------------------------------------------------------------------------------------------ runs
    @classmethod
    async def start(cls, db: AsyncSession, workflow: AutomationWorkflow, trigger_type: str, payload: dict[str, Any] | None,
                    *, dry_run: bool = False, user_id: UUID | None = None, defer: bool = True,
                    trigger_extra: dict[str, Any] | None = None) -> AutomationRun:
        """Create a run and (with ``defer``) commit + enqueue its execution. Raises 409 ``automation_run_active`` when
        another run of a single-concurrency workflow is still active (dry runs are exempt)."""
        wf = workflow
        if wf.status == "archived":
            raise conflict("automation_archived", "Archived automations cannot run")
        nodes, edges = await cls.definition(db, wf)
        raise_if_invalid(validate_definition(nodes, edges, autonomous_actions_enabled=wf.autonomous_actions_enabled,
                                             settings=_public_settings(wf.settings)))
        trig = _trigger_node(nodes)
        assert trig is not None
        payload = jsonable(payload or {})
        if trigger_type == "manual" and trig["type"] == "trigger.manual":
            schema = (trig.get("config") or {}).get("input_schema")
            if isinstance(schema, dict) and schema:
                errs = schema_errors(payload, schema, "payload", allow_templates=False)
                if errs:
                    raise validation("payload does not match the trigger's input_schema",
                                     [{"node_key": trig["key"], "message": m, "code": "invalid_payload"} for m in errs])
        single = (wf.settings or {}).get("concurrency", "single") != "parallel"
        if single and not dry_run:
            await db.execute(select(AutomationWorkflow.id).where(AutomationWorkflow.id == wf.id).with_for_update())
            active = (await db.execute(select(AutomationRun.id).where(
                AutomationRun.workflow_id == wf.id, AutomationRun.status.in_(ACTIVE), AutomationRun.dry_run.is_(False))
                .limit(1))).scalar_one_or_none()
            if active is not None:
                raise conflict("automation_run_active", f"Run {active} of this automation is still active; wait for it "
                                                        "to finish or cancel it")
        ws = await db.get(Workspace, wf.workspace_id)
        brand = await brand_context(db, wf.brand_id)
        now = utcnow()
        trigger_ctx: dict[str, Any] = {}
        if isinstance(payload, dict):
            trigger_ctx.update({k: v for k, v in payload.items() if isinstance(k, str) and not k.startswith("_")})
        trigger_ctx.update(trigger_extra or {})
        trigger_ctx.update({"type": trigger_type, "fired_at": now.isoformat()})
        if trigger_type == "manual":
            trigger_ctx.update({"input": payload, "user_id": str(user_id) if user_id else None})
        workspace = {"id": str(wf.workspace_id), "name": ws.name if ws else None, "slug": getattr(ws, "slug", None)}
        run_id = new_id()
        context = {"trigger": trigger_ctx, "brand": brand, "workspace": workspace,
                   "env": {"workspace": workspace, "dry_run": dry_run, "workflow": {"id": str(wf.id), "name": wf.name}},
                   "steps": {trig["key"]: trigger_ctx}, "_loops": {}, "_exec_count": 0,
                   "_workflow": {"version": wf.version, "nodes": nodes, "edges": edges}}
        run = AutomationRun(id=run_id, workspace_id=wf.workspace_id, workflow_id=wf.id, workflow_version=wf.version,
                            trigger_type=trigger_type, trigger_payload=payload if isinstance(payload, dict) else {"value": payload},
                            status=AutomationStatus.running, context=jsonable(context), dry_run=dry_run, started_at=now,
                            current_node_key=trig["key"], waiting_until=now + LEASE, cost_usd=0)
        db.add(run)
        await db.flush()
        db.add(AutomationRunStep(workspace_id=wf.workspace_id, run_id=run.id, node_key=trig["key"], status="succeeded",
                                 input={"config": jsonable(trig.get("config") or {})}, output=jsonable(trigger_ctx),
                                 attempts=1, started_at=now, finished_at=now))
        if not dry_run:
            wf.last_run_at = now
        await emit(db, "AUTOMATION_TRIGGERED", {"workflow_id": str(wf.id), "run_id": str(run.id), "trigger_type": trigger_type,
                                                "dry_run": dry_run, "workflow_name": wf.name,
                                                "brand_id": str(wf.brand_id) if wf.brand_id else None},
                   workspace_id=wf.workspace_id,
                   actor={"type": "user", "id": str(user_id)} if user_id else {"type": "system", "id": f"automation:{wf.id}"})
        await db.flush()
        if defer:
            await db.commit()
            await set_workspace(db, wf.workspace_id)
            await enqueue_execute(run.id, wf.workspace_id, wf.id, exclusive=single and not dry_run)
        return run

    @classmethod
    async def execute(cls, db: AsyncSession, run_id: UUID | str) -> AutomationRun | None:
        """Advance a run as far as possible (worker entry point; safe to call repeatedly)."""
        rid = UUID(str(run_id))
        async with _run_lock(rid) as got:
            if not got:
                run = await db.get(AutomationRun, rid)
                if run is not None and run.status in ACTIVE:
                    await enqueue_execute(run.id, run.workspace_id, run.workflow_id, delay_s=15)
                return run
            return await _Execution(db, rid).go()

    @classmethod
    async def cancel(cls, db: AsyncSession, member: Any, run_id: Any, *, reason: str | None = None) -> AutomationRun:
        if not member.has("editor"):
            raise forbidden("Cancelling automation runs requires editor or higher")
        run = await cls.get_run(db, member.workspace_id, run_id, for_update=True)
        if run.status in TERMINAL:
            raise conflict("automation_run_finished", f"Run already {_status(run.status)}")
        now = utcnow()
        before = _status(run.status)
        run.status = AutomationStatus.cancelled
        run.finished_at = now
        run.waiting_until = None
        run.error = reason or f"cancelled by {getattr(member.user, 'email', 'a user')}"
        ai_ids: list[str] = []
        for s in await cls.steps(db, run):
            if s.status not in STEP_TERMINAL:
                ai_ids += list((((s.output or {}).get("_state") or {}).get("ai_runs") or {}).values())
                s.status = "skipped"
                s.error = "run cancelled"
                s.finished_at = now
        await db.execute(update(Approval).where(Approval.target_type == "automation_run", Approval.target_id == run.id,
                                                Approval.status == ApprovalStatus.pending)
                         .values(status=ApprovalStatus.expired, decided_at=now, decision_comment="automation run cancelled"))
        for aid in ai_ids:
            try:
                from app.agents.orchestrator.service import AIService
                async with db.begin_nested():
                    await AIService().cancel_run(db, member, UUID(str(aid)))
            except Exception:  # noqa: BLE001 - best effort (already finished, …)
                pass
        await emit(db, "AUTOMATION_FAILED", {"workflow_id": str(run.workflow_id), "run_id": str(run.id), "cancelled": True,
                                             "error": run.error, "dry_run": run.dry_run},
                   workspace_id=run.workspace_id, actor={"type": "user", "id": str(member.user.id)})
        wf = await db.get(AutomationWorkflow, run.workflow_id)
        if wf is not None:
            await cls._audit(db, member, "automation.run_cancel", wf, target_type="automation_run", target_id=run.id,
                             before={"status": before}, after={"status": "cancelled"})
        await db.flush()
        return run


# ============================================================================================ resume hooks

async def wake_run(db: AsyncSession, run_id: UUID) -> AutomationRun | None:
    """Mark a yielded run due now (status waiting, waiting_until=now). Caller commits, then enqueues."""
    run = (await db.execute(select(AutomationRun).where(AutomationRun.id == run_id).with_for_update()
                            .execution_options(populate_existing=True))).scalar_one_or_none()
    if run is None or run.status not in (AutomationStatus.waiting, AutomationStatus.awaiting_approval,
                                         AutomationStatus.running):
        return None
    if run.status != AutomationStatus.running:
        run.status = AutomationStatus.waiting
    run.waiting_until = utcnow()
    return run


async def on_approval_decided(db: AsyncSession, approval: Approval) -> None:
    """Hook called by ApprovalService after an ``automation_step`` approval is approved, rejected or expired (inside the
    deciding transaction): the run is marked due and re-enqueued after commit; the approve/schedule/publish executor
    then reads the decision from the approval row."""
    if approval.target_type != "automation_run":
        return
    run = await wake_run(db, approval.target_id)
    if run is None or run.workspace_id != approval.workspace_id:
        return
    rid, ws, wid = run.id, run.workspace_id, run.workflow_id
    after_commit(db, lambda: enqueue_execute(rid, ws, wid))


async def wake_and_enqueue(run_ids: list[UUID], workspace_id: UUID) -> int:
    """Used by event consumers (own transaction): wake runs, commit, enqueue."""
    from app.core.db import session_scope
    woken: list[tuple[UUID, UUID]] = []
    async with session_scope(workspace_id) as db:
        for rid in dict.fromkeys(run_ids):
            run = await wake_run(db, rid)
            if run is not None and run.workspace_id == workspace_id:
                woken.append((run.id, run.workflow_id))
    for rid, wid in woken:
        await enqueue_execute(rid, workspace_id, wid)
    return len(woken)


# ============================================================================================ execution

class _Execution:
    def __init__(self, db: AsyncSession, run_id: UUID) -> None:
        self.db = db
        self.run_id = run_id
        self.post_commit: list[Callable[[], Awaitable[Any]]] = []
        self.stopped = False
        self.steps: dict[str, AutomationRunStep] = {}

    # -- persistence --------------------------------------------------------------------------------------------------
    async def commit(self) -> None:
        await self.db.commit()
        await set_workspace(self.db, self.ws)
        fns, self.post_commit[:] = list(self.post_commit), []
        for fn in fns:
            try:
                await fn()
            except Exception as e:  # noqa: BLE001
                log.warning("automation.post_commit_failed", error=str(e)[:200])

    async def reload(self) -> None:
        await self.db.rollback()
        self.post_commit.clear()
        await set_workspace(self.db, self.ws)
        for obj in (self.run, self.wf):
            await self.db.refresh(obj)
        for key, s in list(self.steps.items()):
            try:
                await self.db.refresh(s)
            except InvalidRequestError:
                self.steps.pop(key, None)

    def chain_depth(self) -> int:
        try:
            return int(((self.run.context or {}).get("trigger") or {}).get("chain_depth") or 0)
        except (TypeError, ValueError):
            return 0

    def ctx_update(self, **kw: Any) -> None:
        self.run.context = jsonable({**(self.run.context or {}), **kw})

    # -- entry --------------------------------------------------------------------------------------------------------
    async def go(self) -> AutomationRun | None:
        db = self.db
        run = (await db.execute(select(AutomationRun).where(AutomationRun.id == self.run_id)
                                .execution_options(populate_existing=True))).scalar_one_or_none()
        if run is None:
            log.warning("automation.run_missing", run_id=str(self.run_id))
            return None
        self.run = run
        self.ws = run.workspace_id
        if run.status in TERMINAL:
            return run
        await set_workspace(db, run.workspace_id)
        wf = await db.get(AutomationWorkflow, run.workflow_id, populate_existing=True)
        if wf is None:
            return None
        self.wf = wf
        snap = (run.context or {}).get("_workflow") or {}
        if not snap.get("nodes"):
            nodes, edges = await AutomationEngine.definition(db, wf)
            snap = {"nodes": nodes, "edges": edges}
        self.graph = Graph.build(snap["nodes"], snap.get("edges") or [])
        self.order = self._topo_order()
        for s in await AutomationEngine.steps(db, run):
            self.steps[s.node_key] = s
        self.actor = await load_actor(db, wf, run)
        self.settings = _public_settings(wf.settings)
        claimed = (await db.execute(
            update(AutomationRun).where(AutomationRun.id == run.id, AutomationRun.status.in_(ACTIVE))
            .values(status=AutomationStatus.running, waiting_until=utcnow() + LEASE)
            .returning(AutomationRun.id).execution_options(synchronize_session=False))).scalar_one_or_none()
        await self.commit()
        await db.refresh(run)
        if claimed is None:          # cancelled / finished meanwhile
            return run
        if await self._limits_exceeded():
            return run
        for key in self.order:
            if self.stopped:
                break
            s = self.steps.get(key)
            if s is not None and (s.status in STEP_OPEN or s.status == "running"):
                await self.run_node(key)
        while not self.stopped:
            if not await self.advance():
                break
        await self.finalize()
        return run

    def _topo_order(self) -> list[str]:
        indeg = {k: 0 for k in self.graph.nodes}
        for e in self.graph.edges:
            if e.index not in self.graph.back_edges and e.dst in indeg and e.src in indeg:
                indeg[e.dst] += 1
        ready = sorted(k for k, d in indeg.items() if d == 0)
        out: list[str] = []
        while ready:
            k = ready.pop(0)
            out.append(k)
            for e in self.graph.forward_out(k):
                indeg[e.dst] -= 1
                if indeg[e.dst] == 0:
                    ready.append(e.dst)
                    ready.sort()
        out += sorted(set(self.graph.nodes) - set(out))
        return out

    async def _limits_exceeded(self) -> bool:
        tmo = self.settings.get("timeout_minutes")
        if tmo and utcnow() - self.run.started_at > timedelta(minutes=int(tmo)):
            await self.fail_run(f"run exceeded the workflow timeout of {tmo} minutes")
            await self.commit()
            return True
        cap = self.settings.get("max_cost_usd")
        if cap is not None and float(self.run.cost_usd or 0) > float(cap):
            await self.fail_run(f"run cost ${float(self.run.cost_usd or 0):.2f} exceeded the workflow budget ${float(cap):.2f}")
            await self.commit()
            return True
        return False

    # -- graph state --------------------------------------------------------------------------------------------------
    def edge_state(self, e: Edge) -> str:
        s = self.steps.get(e.src)
        if s is None or s.status not in STEP_TERMINAL:
            return "pending"
        if s.status == "skipped":
            return "inactive"
        if s.status == "failed":
            return "active" if e.branch == "error" else "inactive"
        if e.branch == "error":
            return "inactive"
        nt = NODE_TYPES.get(str(self.graph.nodes[e.src].get("type")))
        branch = (s.output or {}).get("branch") if nt is not None and None not in nt.branches else None
        return "active" if (e.branch or None) == (branch if isinstance(branch, str) else None) else "inactive"

    def readiness(self, key: str) -> str:
        ins = self.graph.forward_in(key)
        if not ins:
            return "skip"
        states = [self.edge_state(e) for e in ins]
        if "pending" in states:
            return "wait"
        return "ready" if "active" in states else "skip"

    def handled(self, key: str) -> bool:
        return any(e.branch == "error" for e in self.graph.out_edges.get(key, []))

    async def advance(self) -> bool:
        changed = False
        for key in self.order:
            if self.stopped:
                break
            if key == self.graph.trigger:
                continue
            s = self.steps.get(key)
            if s is not None and s.status != "pending":
                continue
            r = self.readiness(key)
            if r == "skip":
                self.mark_skipped(key)
                changed = True
            elif r == "ready":
                await self.run_node(key)
                changed = True
        return changed

    def _step(self, key: str) -> AutomationRunStep:
        s = self.steps.get(key)
        if s is None:
            s = AutomationRunStep(id=new_id(), workspace_id=self.run.workspace_id, run_id=self.run.id, node_key=key,
                                  status="pending", attempts=0)
            self.db.add(s)
            self.steps[key] = s
        return s

    def mark_skipped(self, key: str) -> None:
        s = self._step(key)
        s.status = "skipped"
        s.finished_at = utcnow()

    def check_loops(self, key: str) -> None:
        for e in self.graph.out_edges.get(key, []):
            if e.index not in self.graph.back_edges or self.edge_state(e) != "active":
                continue
            body = self.graph.loop_body(e.dst)
            reset = set(body) | {k for k in self.graph.downstream(body) if (s := self.steps.get(k)) is not None
                                 and s.status == "skipped"}
            for k in reset:
                s = self.steps.get(k)
                if s is None:
                    continue
                s.status = "pending"
                s.output = None
                s.error = None
                s.attempts = 0
                s.ai_run_id = None
                s.started_at = None
                s.finished_at = None
            log.info("automation.loop_iteration", run_id=str(self.run.id), head=e.dst, nodes=sorted(reset))

    # -- node execution -----------------------------------------------------------------------------------------------
    def scope(self) -> dict[str, Any]:
        c = self.run.context or {}
        return {"trigger": c.get("trigger") or {}, "brand": c.get("brand"), "workspace": c.get("workspace") or {},
                "steps": c.get("steps") or {}, "env": c.get("env") or {}, "now": utcnow().isoformat(),
                "run": {"id": str(self.run.id), "dry_run": self.run.dry_run, "workflow_id": str(self.wf.id)}}

    def add_cost(self, amount: float) -> None:
        self.run.cost_usd = round(float(self.run.cost_usd or 0) + float(amount), 6)

    async def run_node(self, key: str) -> None:
        node = self.graph.nodes[key]
        ntype = str(node.get("type"))
        nt = NODE_TYPES[ntype]
        step = self._step(key)
        resuming = step.status in STEP_OPEN
        if not resuming:
            if step.status == "running" and step.attempts >= MAX_CRASH_ATTEMPTS:
                await self.fail_step(key, f"step was interrupted {step.attempts} times; giving up")
                return
            count = int((self.run.context or {}).get("_exec_count") or 0) + 1
            if count > MAX_EXECUTIONS:
                await self.fail_run(f"run exceeded {MAX_EXECUTIONS} node executions")
                await self.commit()
                return
            self.ctx_update(_exec_count=count)
            step.attempts = int(step.attempts or 0) + 1
            step.status = "running"
            step.started_at = utcnow()
            step.finished_at = None
            step.error = None
            self.run.current_node_key = key
            try:
                cfg = render_value(node.get("config") or {}, self.scope(), skip_keys=set(nt.raw_fields))
            except ExpressionError as e:
                await self.commit()
                await self.fail_step(key, f"config: {e}")
                return
            errs = schema_errors(cfg, nt.config_schema, allow_templates=False)
            step.input = jsonable({"config": cfg})
            await self.commit()
            if errs:
                await self.fail_step(key, "config after rendering: " + "; ".join(errs[:5]))
                return
        else:
            cfg = (step.input or {}).get("config") or {}
        state = dict(((step.output or {}).get("_state")) or {})
        nctx = NodeContext(db=self.db, run=self.run, workflow=self.wf, node_key=key, node_type=ntype,
                           label=node.get("label"), step=step, actor=self.actor, scope=self.scope(), state=state,
                           dry_run=bool(self.run.dry_run), commit=self.commit, post_commit=self.post_commit,
                           add_run_cost=self.add_cost)
        executor = get_executor(ntype)
        if executor is None:
            await self.fail_step(key, f"no executor for node type {ntype}")
            return
        started = step.started_at or utcnow()
        try:
            out = await executor(nctx, cfg)
        except NodeYield as y:
            step.status = y.status
            step.output = jsonable({"_state": nctx.state, "_wait": {
                "reason": y.reason, "until": y.until.isoformat() if y.until else None, "approval_id": y.approval_id,
                **y.info}})
            self.run.current_node_key = key
            await self.commit()
            return
        except Exception as e:  # noqa: BLE001 - every executor failure becomes a step failure
            if not isinstance(e, NodeError | ProblemError | ExpressionError):
                log.exception("automation.node_crashed", run_id=str(self.run.id), node_key=key, node_type=ntype)
            details = getattr(e, "details", None)
            await self.reload()
            await self.fail_step(key, problem_message(e), details=details)
            return
        out = out if isinstance(out, dict) else {"value": out}
        public = truncate_json(jsonable({k: v for k, v in out.items() if not str(k).startswith("_")}))
        step.status = "succeeded"
        step.finished_at = utcnow()
        step.output = jsonable({**public, **({"_state": nctx.state} if nctx.state else {})})
        steps_ctx = dict((self.run.context or {}).get("steps") or {})
        steps_ctx[key] = public
        self.ctx_update(steps=steps_ctx)
        await self._emit_step(key, ntype, "succeeded", started)
        self.check_loops(key)
        await self.commit()
        await self._limits_exceeded()

    async def fail_step(self, key: str, message: str, *, details: Any = None) -> None:
        step = self._step(key)
        node = self.graph.nodes[key]
        step.status = "failed"
        step.error = message[:2000]
        step.finished_at = utcnow()
        step.output = jsonable({**(step.output or {}), "_error": {"message": message[:2000], "details": details}})
        await self._emit_step(key, str(node.get("type")), "failed", step.started_at or utcnow(), error=message)
        if self.handled(key):
            self.check_loops(key)
        else:
            policy = (node.get("config") or {}).get("on_error") or self.settings.get("on_error") or "stop"
            if policy != "continue":
                await self.fail_run(f"step {key!r} failed: {message}", node_key=key, notify=policy)
        await self.commit()

    async def _emit_step(self, key: str, ntype: str, status: str, started: datetime, error: str | None = None) -> None:
        ms = int((utcnow() - started).total_seconds() * 1000) if started else None
        await emit(self.db, "AUTOMATION_STEP_COMPLETED", {"workflow_id": str(self.wf.id), "run_id": str(self.run.id),
                                                         "node_key": key, "node_type": ntype, "status": status,
                                                         "duration_ms": ms, "error": (error or "")[:300] or None,
                                                         "dry_run": self.run.dry_run},
                   workspace_id=self.run.workspace_id, actor={"type": "system", "id": f"automation:{self.wf.id}"})

    # -- terminal states ----------------------------------------------------------------------------------------------
    async def _cancelled(self) -> bool:
        cur = (await self.db.execute(select(AutomationRun.status).where(AutomationRun.id == self.run.id)
                                     .with_for_update())).scalar_one_or_none()
        return cur == AutomationStatus.cancelled

    async def fail_run(self, error: str, *, node_key: str | None = None, notify: str = "stop") -> None:
        self.stopped = True
        if await self._cancelled():
            self.run.status = AutomationStatus.cancelled
            return
        now = utcnow()
        self.run.status = AutomationStatus.failed
        self.run.error = error[:2000]
        self.run.finished_at = now
        self.run.waiting_until = None
        for s in self.steps.values():
            if s.status in STEP_OPEN or s.status in ("pending", "running"):
                s.status = "skipped"
                s.finished_at = now
                s.error = s.error or "run failed"
        await self.db.execute(update(Approval).where(
            Approval.target_type == "automation_run", Approval.target_id == self.run.id, Approval.status == ApprovalStatus.pending)
            .values(status=ApprovalStatus.expired, decided_at=now, decision_comment="automation run failed"))
        await emit(self.db, "AUTOMATION_FAILED", {"workflow_id": str(self.wf.id), "run_id": str(self.run.id), "error": error[:500],
                                                  "node_key": node_key, "dry_run": self.run.dry_run,
                                                  "workflow_name": self.wf.name, "cost_usd": float(self.run.cost_usd or 0),
                                                  "chain_depth": self.chain_depth()},
                   workspace_id=self.run.workspace_id, actor={"type": "system", "id": f"automation:{self.wf.id}"})
        if not self.run.dry_run:
            await self._notify_failure(error, notify)

    async def _notify_failure(self, error: str, policy: str) -> None:
        try:
            from app.services.notification_service import NotificationService
            link = f"/automations/{self.wf.id}/runs/{self.run.id}"
            title = f"Automation '{self.wf.name}' failed"
            async with self.db.begin_nested():
                if policy == "notify":
                    await NotificationService.notify(self.db, self.run.workspace_id, "automation_failed", title, error[:1000],
                                                     link, user_id=None, severity="error")
                else:
                    await NotificationService.notify(self.db, self.run.workspace_id, "automation_failed", title, error[:1000],
                                                     link, user_id=self.wf.created_by, severity="error", channels=["in_app"])
        except Exception as e:  # noqa: BLE001
            log.warning("automation.notify_failed", error=str(e)[:200])

    async def finalize(self) -> None:
        if self.stopped:
            await self.commit()
            return
        if await self._cancelled():
            self.run.status = AutomationStatus.cancelled
            await self.commit()
            return
        open_steps = [s for k in self.order if (s := self.steps.get(k)) is not None and s.status in STEP_OPEN]
        if open_steps:
            awaiting = [s for s in open_steps if s.status == "awaiting_approval"]
            untils = [d for s in open_steps if (d := parse_dt(((s.output or {}).get("_wait") or {}).get("until")))]
            self.run.status = AutomationStatus.awaiting_approval if awaiting else AutomationStatus.waiting
            self.run.waiting_until = min(untils) if untils else utcnow() + LEASE
            self.run.current_node_key = (awaiting or open_steps)[0].node_key
            ap_id = ((awaiting[0].output or {}).get("_wait") or {}).get("approval_id") if awaiting else None
            self.run.approval_id = UUID(ap_id) if ap_id else self.run.approval_id
            await self.commit()
            return
        stuck = [k for k in self.order if k != self.graph.trigger
                 and ((s := self.steps.get(k)) is None or s.status in ("pending", "running"))]
        failed = [s for s in self.steps.values() if s.status == "failed" and not self.handled(s.node_key)]
        if stuck:
            await self.fail_run(f"workflow could not make progress; nodes never became ready: {', '.join(stuck[:10])}")
        elif failed:
            names = ", ".join(f"{s.node_key} ({(s.error or '')[:120]})" for s in failed[:5])
            await self.fail_run(f"{len(failed)} step(s) failed: {names}", node_key=failed[0].node_key,
                                notify=self.settings.get("on_error") or "stop")
        else:
            self.run.status = AutomationStatus.succeeded
            self.run.finished_at = utcnow()
            self.run.waiting_until = None
            self.run.current_node_key = None
            n = sum(1 for s in self.steps.values() if s.status == "succeeded")
            await emit(self.db, "AUTOMATION_COMPLETED", {"workflow_id": str(self.wf.id), "run_id": str(self.run.id),
                                                         "workflow_name": self.wf.name, "steps_succeeded": n,
                                                         "steps_skipped": sum(1 for s in self.steps.values() if s.status == "skipped"),
                                                         "cost_usd": float(self.run.cost_usd or 0), "dry_run": self.run.dry_run,
                                                         "chain_depth": self.chain_depth()},
                       workspace_id=self.run.workspace_id, actor={"type": "system", "id": f"automation:{self.wf.id}"})
        await self.commit()


# Register automation event consumers (event triggers + AI/research/approval resumes) in every process that imports
# the engine (API, worker, scheduler). Imported last: the consumers module imports this one lazily.
import app.events.consumers_automation  # noqa: E402,F401

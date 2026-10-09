"""AIService (doc 05 §5.2.1): create/cancel/resume/get/list runs, conversations & messages, run views (doc 17), enqueue."""
from __future__ import annotations

from datetime import UTC, datetime
from typing import Any
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.agents.registry import get_spec, has_agent
from app.config import settings
from app.core.errors import ProblemError, forbidden, not_found, validation
from app.core.ids import new_id
from app.core.logging import get_logger
from app.core.pagination import decode_cursor, encode_cursor
from app.models.ai import AIConversation, AIMessage, AIRun, AITask, AIToolCall
from app.models.enums import ROLE_RANK, RunStatus

log = get_logger("ai.service")
MODES = ("chat", "task", "tool", "automation")
_queue_opened = False


async def enqueue_job(name: str, run_id: UUID, workspace_id: UUID, *, queue: str = "ai") -> None:
    """Enqueue jobs.ai.run / jobs.ai.resume via Procrastinate (opens the connector once per process)."""
    global _queue_opened
    from app.workers.app import procrastinate_app
    if not _queue_opened:
        try:
            await procrastinate_app.open_async()
        except Exception as e:  # noqa: BLE001 - already open / in-worker
            log.info("queue.open_skipped", error=str(e)[:120])
        _queue_opened = True
    await procrastinate_app.configure_task(name=name, queue=queue, queueing_lock=f"ai:{run_id}").defer_async(
        run_id=str(run_id), workspace_id=str(workspace_id))


class AIService:
    # -- runs ---------------------------------------------------------------------------------------------------------
    async def create_run(self, db: AsyncSession, member: Any, *, message: str, brand_id: UUID | None = None,
                         conversation_id: UUID | None = None, mode: str = "chat", agent: str | None = None,
                         action: str | None = None, inputs: dict[str, Any] | None = None, budget_usd: float | None = None,
                         automation_run_id: UUID | None = None, enqueue: bool = True) -> AIRun:
        if mode not in MODES:
            raise validation(f"mode must be one of {', '.join(MODES)}")
        role = getattr(getattr(member, "role", None), "value", getattr(member, "role", "editor")) or "editor"
        if ROLE_RANK.get(str(role), 0) < ROLE_RANK["approver"]:
            raise forbidden("Viewers cannot run the AI assistant")
        if mode == "tool":
            if not agent or not action:
                raise validation("tool mode requires agent and action")
            if not has_agent(agent):
                raise validation(f"unknown agent {agent!r}")
            if action not in get_spec(agent).actions:
                raise validation(f"agent {agent!r} has no action {action!r}")
        elif not (message or "").strip():
            raise validation("message is required")
        ws = member.workspace_id
        user_id = getattr(getattr(member, "user", None), "id", None)
        budget = await self._budget(db, ws, budget_usd)
        conv = None
        if mode in ("chat", "task"):
            conv = await self._conversation(db, ws, user_id, brand_id, conversation_id, message)
        run = AIRun(id=new_id(), workspace_id=ws, brand_id=brand_id, user_id=user_id, conversation_id=conv.id if conv else conversation_id,
                    mode=mode, input={"message": message, "agent": agent, "action": action, "inputs": inputs or {}, "role": str(role),
                                      "confirmed_spend": bool((inputs or {}).get("confirmed_spend"))},
                    status=RunStatus.queued, budget=budget, cancel_requested=False, tokens_in=0, tokens_out=0, cached_tokens=0,
                    cost_usd=0, automation_run_id=automation_run_id, queued_at=datetime.now(UTC))
        db.add(run)
        if conv is not None:
            db.add(AIMessage(workspace_id=ws, conversation_id=conv.id, role="user", content={"text": message, "inputs": inputs or {}},
                             run_id=run.id))
            conv.updated_at = datetime.now(UTC)
        await db.flush()
        await self._audit(db, member, "ai_run.create", run)
        if enqueue:
            try:
                await enqueue_job("jobs.ai.run", run.id, ws)
            except Exception as e:  # noqa: BLE001 - run stays queued; maintenance may re-enqueue
                log.error("ai_run.enqueue_failed", run_id=str(run.id), error=str(e)[:300])
        return run

    async def _budget(self, db: AsyncSession, workspace_id: UUID, budget_usd: float | None) -> dict[str, Any]:
        per_run = settings.default_run_budget_usd
        try:
            from app.services.ai_settings_service import AISettingsService
            per_run = float((await AISettingsService().get(db, workspace_id))["budgets"].get("per_run_usd", per_run))
        except Exception:  # noqa: BLE001
            pass
        cap = float(budget_usd) if budget_usd is not None else per_run
        if cap <= 0:
            raise validation("budget_usd must be positive")
        return {"max_cost_usd": cap, "max_tool_calls": 120, "max_wall_seconds": 900}

    async def _conversation(self, db: AsyncSession, ws: UUID, user_id: UUID | None, brand_id: UUID | None,
                            conversation_id: UUID | None, message: str) -> AIConversation:
        if conversation_id is not None:
            conv = await db.get(AIConversation, conversation_id)
            if conv is None or conv.workspace_id != ws:
                raise not_found("Conversation")
            return conv
        conv = AIConversation(id=new_id(), workspace_id=ws, brand_id=brand_id, user_id=user_id, title=(message or "")[:80] or "New conversation")
        db.add(conv)
        await db.flush()
        return conv

    async def get_run(self, db: AsyncSession, workspace_id: UUID, run_id: UUID) -> AIRun:
        run = await db.get(AIRun, run_id)
        if run is None or run.workspace_id != workspace_id:
            raise not_found("Run")
        return run

    async def cancel_run(self, db: AsyncSession, member: Any, run_id: UUID) -> AIRun:
        run = await self.get_run(db, member.workspace_id, run_id)
        if run.status in (RunStatus.completed, RunStatus.failed, RunStatus.cancelled):
            raise ProblemError(409, "conflict", "Run already finished", f"status={run.status.value}")
        run.cancel_requested = True
        if run.status in (RunStatus.queued, RunStatus.awaiting_approval, RunStatus.paused):
            run.status = RunStatus.cancelled
            run.finished_at = datetime.now(UTC)
        try:
            from app.core.redis import get_redis
            await get_redis().setex(f"botwok:run:{run.id}:cancel", 3600, "1")
        except Exception as e:  # noqa: BLE001
            log.info("cancel.redis_unavailable", error=str(e)[:120])
        await db.flush()
        await self._audit(db, member, "ai_run.cancel", run)
        return run

    async def resume_run(self, db: AsyncSession, member: Any, run_id: UUID, *, resume_from: str | None = None) -> AIRun:
        run = await self.get_run(db, member.workspace_id, run_id)
        if run.status not in (RunStatus.awaiting_approval, RunStatus.paused, RunStatus.failed):
            raise ProblemError(409, "conflict", "Run cannot be resumed", f"status={run.status.value}")
        if run.status == RunStatus.failed:
            # "retry from this step": reset the failed/skipped tasks (and optionally everything from resume_from)
            tasks = (await db.execute(select(AITask).where(AITask.run_id == run.id))).scalars().all()
            for t in tasks:
                if t.status.value in ("failed", "skipped", "cancelled") or (resume_from and t.task_key.startswith(resume_from)):
                    t.status = "pending"  # type: ignore[assignment]
                    t.error = None
                    t.output = None
            run.error = None
            run.finished_at = None
        run.status = RunStatus.paused
        run.cancel_requested = False
        await db.flush()
        await self._audit(db, member, "ai_run.resume", run)
        try:
            await enqueue_job("jobs.ai.resume", run.id, run.workspace_id)
        except Exception as e:  # noqa: BLE001
            log.error("ai_run.resume_enqueue_failed", run_id=str(run.id), error=str(e)[:300])
        return run

    async def list_runs(self, db: AsyncSession, workspace_id: UUID, *, limit: int = 25, cursor: str | None = None,
                        status: str | None = None, brand_id: UUID | None = None, mode: str | None = None) -> tuple[list[AIRun], str | None]:
        q = select(AIRun).where(AIRun.workspace_id == workspace_id)
        if status:
            q = q.where(AIRun.status == status)
        if brand_id:
            q = q.where(AIRun.brand_id == brand_id)
        if mode:
            q = q.where(AIRun.mode == mode)
        c = decode_cursor(cursor)
        if c and c.get("created_at"):
            q = q.where(AIRun.created_at < datetime.fromisoformat(c["created_at"]))
        rows = list((await db.execute(q.order_by(AIRun.created_at.desc()).limit(limit + 1))).scalars().all())
        nxt = encode_cursor({"created_at": rows[limit - 1].created_at.isoformat()}) if len(rows) > limit else None
        return rows[:limit], nxt

    # -- views (doc 17) -----------------------------------------------------------------------------------------------
    @staticmethod
    def task_view(t: AITask) -> dict[str, Any]:
        dur = int((t.finished_at - t.started_at).total_seconds() * 1000) if t.started_at and t.finished_at else None
        out = t.output or {}
        sources_count = len(out.get("sources") or []) if isinstance(out, dict) else 0
        return {"key": t.task_key, "parent_key": t.parent_key, "label": t.label, "agent": t.agent_id, "action": t.action,
                "status": t.status.value if hasattr(t.status, "value") else str(t.status), "duration_ms": dur,
                "cost_usd": float(t.cost_usd or 0), "tokens_in": int(t.tokens_in or 0), "tokens_out": int(t.tokens_out or 0),
                "sources_count": sources_count, "depends_on": list(t.depends_on or []), "requires_approval": bool(t.requires_approval),
                "error": t.error, "started_at": t.started_at, "finished_at": t.finished_at}

    def run_view(self, run: AIRun, *, include_outputs: bool = False) -> dict[str, Any]:
        tasks = sorted(run.tasks or [], key=lambda t: _task_sort_key(t.task_key))
        plan = {"goal": (run.plan or {}).get("goal"), "tasks": [self.task_view(t) for t in tasks],
                "deliverables": (run.plan or {}).get("deliverables", []), "approval_points": (run.plan or {}).get("approval_points", [])}
        result = run.result
        if result and not include_outputs:
            result = {k: v for k, v in result.items() if k != "tasks"}
        return {"id": run.id, "status": run.status.value, "mode": run.mode, "brand_id": run.brand_id, "conversation_id": run.conversation_id,
                "message": (run.input or {}).get("message"), "intent": run.intent, "plan": plan, "result": result,
                "cost_usd": float(run.cost_usd or 0), "tokens": {"in": int(run.tokens_in or 0), "out": int(run.tokens_out or 0),
                                                                 "cached": int(run.cached_tokens or 0)},
                "budget": run.budget or {}, "error": run.error, "reasoning_summary": run.reasoning_summary,
                "cancel_requested": bool(run.cancel_requested), "created_at": run.created_at, "started_at": run.started_at,
                "finished_at": run.finished_at}

    async def steps_view(self, db: AsyncSession, run: AIRun) -> list[dict[str, Any]]:
        rows = (await db.execute(select(AITask).where(AITask.run_id == run.id))).scalars().all()
        return [self.task_view(t) for t in sorted(rows, key=lambda t: _task_sort_key(t.task_key))]

    async def tool_calls_view(self, db: AsyncSession, run: AIRun, *, limit: int = 50, cursor: str | None = None
                              ) -> tuple[list[dict[str, Any]], str | None]:
        q = select(AIToolCall).where(AIToolCall.run_id == run.id).order_by(AIToolCall.started_at, AIToolCall.call_index)
        c = decode_cursor(cursor)
        if c and c.get("offset"):
            q = q.offset(int(c["offset"]))
        rows = list((await db.execute(q.limit(limit + 1))).scalars().all())
        offset = (int(c["offset"]) if c and c.get("offset") else 0)
        nxt = encode_cursor({"offset": offset + limit}) if len(rows) > limit else None
        tasks = {t.id: t.task_key for t in (run.tasks or [])}
        items = []
        for r in rows[:limit]:
            res = r.result or {}
            data = res.get("data") if isinstance(res, dict) else res
            items.append({"id": r.id, "task_key": tasks.get(r.task_id), "call_index": r.call_index, "tool_name": r.tool_name,
                          "side_effect": r.side_effect, "args_summary": _summary(r.args), "result_summary": _summary(data),
                          "status": r.status, "duration_ms": r.duration_ms, "error": r.error, "approval_id": r.approval_id,
                          "started_at": r.started_at, "finished_at": r.finished_at})
        return items, nxt

    # -- conversations ------------------------------------------------------------------------------------------------
    async def list_conversations(self, db: AsyncSession, workspace_id: UUID, *, user_id: UUID | None = None, brand_id: UUID | None = None,
                                 limit: int = 25, cursor: str | None = None) -> tuple[list[AIConversation], str | None]:
        q = select(AIConversation).where(AIConversation.workspace_id == workspace_id)
        if user_id:
            q = q.where(AIConversation.user_id == user_id)
        if brand_id:
            q = q.where(AIConversation.brand_id == brand_id)
        c = decode_cursor(cursor)
        if c and c.get("updated_at"):
            q = q.where(AIConversation.updated_at < datetime.fromisoformat(c["updated_at"]))
        rows = list((await db.execute(q.order_by(AIConversation.updated_at.desc()).limit(limit + 1))).scalars().all())
        nxt = encode_cursor({"updated_at": rows[limit - 1].updated_at.isoformat()}) if len(rows) > limit else None
        return rows[:limit], nxt

    async def create_conversation(self, db: AsyncSession, member: Any, *, title: str | None = None, brand_id: UUID | None = None,
                                  context_ref: dict[str, Any] | None = None) -> AIConversation:
        conv = AIConversation(id=new_id(), workspace_id=member.workspace_id, brand_id=brand_id, user_id=member.user.id,
                              title=title or "New conversation", context_ref=context_ref)
        db.add(conv)
        await db.flush()
        return conv

    async def get_conversation(self, db: AsyncSession, workspace_id: UUID, conversation_id: UUID) -> AIConversation:
        conv = await db.get(AIConversation, conversation_id)
        if conv is None or conv.workspace_id != workspace_id:
            raise not_found("Conversation")
        return conv

    async def list_messages(self, db: AsyncSession, workspace_id: UUID, conversation_id: UUID, *, limit: int = 50,
                            cursor: str | None = None) -> tuple[list[AIMessage], str | None]:
        await self.get_conversation(db, workspace_id, conversation_id)
        q = select(AIMessage).where(AIMessage.conversation_id == conversation_id, AIMessage.workspace_id == workspace_id)
        c = decode_cursor(cursor)
        if c and c.get("created_at"):
            q = q.where(AIMessage.created_at > datetime.fromisoformat(c["created_at"]))
        rows = list((await db.execute(q.order_by(AIMessage.created_at.asc()).limit(limit + 1))).scalars().all())
        nxt = encode_cursor({"created_at": rows[limit - 1].created_at.isoformat()}) if len(rows) > limit else None
        return rows[:limit], nxt

    async def conversation_message_counts(self, db: AsyncSession, conversation_ids: list[UUID]) -> dict[UUID, int]:
        if not conversation_ids:
            return {}
        rows = (await db.execute(select(AIMessage.conversation_id, func.count(AIMessage.id))
                                 .where(AIMessage.conversation_id.in_(conversation_ids)).group_by(AIMessage.conversation_id))).all()
        return {cid: int(n) for cid, n in rows}

    # -- helpers ------------------------------------------------------------------------------------------------------
    @staticmethod
    async def _audit(db: AsyncSession, member: Any, action: str, run: AIRun) -> None:
        try:
            from app.services.audit_service import audit
        except ImportError:
            return
        try:
            await audit(db, member, action, "ai_run", str(run.id), before=None,
                        after={"status": run.status.value, "mode": run.mode})
        except Exception as e:  # noqa: BLE001
            log.warning("audit.failed", action=action, error=str(e)[:200])


def _task_sort_key(key: str) -> tuple[int, ...]:
    parts = key.lstrip("t").split(".")
    out = []
    for p in parts:
        try:
            out.append(int(p))
        except ValueError:
            out.append(0)
    return tuple(out)


def _summary(obj: Any, limit: int = 240) -> str:
    import json
    try:
        s = obj if isinstance(obj, str) else json.dumps(obj, default=str, ensure_ascii=False)
    except Exception:  # noqa: BLE001
        s = str(obj)
    return s if len(s) <= limit else s[: limit - 1] + "…"

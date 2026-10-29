"""Orchestrator.run(run_id): mode=tool → single agent action; chat/task → IntentRouter → (clarification) → Planner →
Executor → result assembly {deliverables, sources, reasoning_summary, actions, cost}; automation → fixed plan."""
from __future__ import annotations

from typing import Any
from uuid import UUID

from app.agents.orchestrator import ledger
from app.agents.orchestrator.approval_gate import ApprovalGate
from app.agents.orchestrator.context import ContextBuilder, RunContext
from app.agents.orchestrator.executor import ExecutionResult, Executor, resolve_ref
from app.agents.orchestrator.intent_router import IntentRouter
from app.agents.orchestrator.memory import MemoryService
from app.agents.orchestrator.plan_templates import NO_PLAN_INTENTS
from app.agents.orchestrator.planner import PlanInvalid, Planner, PlanValidator
from app.agents.orchestrator.runtime import AgentRuntime
from app.agents.registry import enabled_agent_ids, get_spec, has_agent
from app.agents.schemas.orchestrator import IntentResult, Plan, PlanTask
from app.core.logging import get_logger
from app.core.ports.ai_provider import Message
from app.models.ai import AIMessage, AIRun
from app.models.enums import RunStatus
from app.services.budget_guard import BudgetExceeded, BudgetGuard
from app.tools.registry import load_builtin_tools

log = get_logger("ai.orchestrator")
TERMINAL = {RunStatus.completed, RunStatus.failed, RunStatus.cancelled}


class Orchestrator:
    def __init__(self, *, runtime: AgentRuntime | None = None, session_factory: Any = None, max_parallel: int | None = None):
        self.budget = BudgetGuard()
        self.runtime = runtime or AgentRuntime(self.budget)
        self.session_factory = session_factory
        self.max_parallel = max_parallel
        self.gate = ApprovalGate()

    # -- entry points -------------------------------------------------------------------------------------------------
    async def run(self, db: Any, run_id: UUID) -> AIRun | None:
        run = await db.get(AIRun, run_id)
        if run is None:
            log.warning("orchestrator.run_missing", run_id=str(run_id))
            return None
        if run.status in TERMINAL:
            return run
        load_builtin_tools()
        try:
            if run.status == RunStatus.queued:
                await ledger.run_started(db, run)
            elif run.status in (RunStatus.awaiting_approval, RunStatus.paused):
                if await self.gate.pending_for_run(db, run.id):
                    log.info("orchestrator.still_awaiting", run_id=str(run.id))
                    return run
                await ledger.run_running(db, run)
            ctx = await ContextBuilder().build(db, run)
            plan = await self._plan(db, run, ctx)
            if plan is None:                       # clarification / direct reply / awaiting spend approval
                return run
            await ledger.run_running(db, run)
            executor = Executor(self.runtime, max_parallel=self.max_parallel or ctx.max_parallel,
                                session_factory=self.session_factory, gate=self.gate)
            result = await executor.run(db, run, plan, ctx)
            await self._finish(db, run, ctx, plan, result, executor)
        except BudgetExceeded as e:
            await ledger.run_failed(db, run, f"budget exceeded: {e.detail}")
        except PlanInvalid as e:
            await ledger.run_failed(db, run, f"could not build a valid plan: {'; '.join(e.errors[:4])}")
            await self._assistant_message(db, run, f"I couldn't turn that into a plan: {'; '.join(e.errors[:2])}")
        except Exception as e:  # noqa: BLE001
            log.exception("orchestrator.crashed", run_id=str(run.id))
            await ledger.run_failed(db, run, f"{type(e).__name__}: {str(e)[:500]}")
        return run

    async def resume(self, db: Any, run_id: UUID) -> AIRun | None:
        return await self.run(db, run_id)

    # -- planning -----------------------------------------------------------------------------------------------------
    async def _plan(self, db: Any, run: AIRun, ctx: RunContext) -> Plan | None:
        inp = run.input or {}
        if run.plan:
            return Plan.model_validate(run.plan)
        if run.mode == "tool":
            plan = self._tool_plan(inp)
        elif run.mode == "automation" and inp.get("plan"):
            plan = Plan.model_validate(inp["plan"])
            errors = PlanValidator(await enabled_agent_ids(db), budget_usd=ctx.budget.max_cost_usd).validate(plan)
            if errors:
                raise PlanInvalid(errors)
        else:
            await ledger.run_planning(db, run)
            intent = IntentResult.model_validate(run.intent) if run.intent else await IntentRouter().route(db, ctx, ctx.message)
            run.intent = intent.model_dump()
            ctx.intent = run.intent
            await ledger.safe_commit(db)
            if intent.clarification_needed and intent.question:
                await self._complete_with_text(db, run, ctx, intent.question, kind="clarification")
                return None
            if intent.intent in NO_PLAN_INTENTS and not any(i not in NO_PLAN_INTENTS for i in intent.all_intents()):
                text = intent.reply or _canned_reply(intent.intent)
                await self._complete_with_text(db, run, ctx, text, kind="reply")
                return None
            plan = await Planner().plan(db, ctx, intent, ctx.message)
        run.plan = plan.model_dump()
        await ledger.safe_commit(db)
        est = plan.estimated_cost_usd or PlanValidator().estimate_cost(plan)
        if run.mode != "tool" and est > ctx.confirm_above_usd and not inp.get("confirmed_spend"):
            await self.gate.pause_for_spend(db, run, est, ctx.confirm_above_usd)
            return None
        return plan

    @staticmethod
    def _tool_plan(inp: dict[str, Any]) -> Plan:
        agent, action = str(inp.get("agent") or ""), str(inp.get("action") or "")
        if not has_agent(agent):
            raise PlanInvalid([f"unknown agent {agent!r}"])
        spec = get_spec(agent)
        if action not in spec.actions:
            raise PlanInvalid([f"agent {agent!r} has no action {action!r} (valid: {', '.join(spec.actions)})"])
        inputs = dict(inp.get("inputs") or {})
        if inp.get("message") and "message" not in inputs:
            inputs["message"] = inp["message"]
        task = PlanTask(id="t1", agent=agent, action=action, label=spec.actions[action].label, inputs=inputs,
                        requires_approval=spec.actions[action].approval)
        return Plan(goal=f"{agent}.{action}", tasks=[task], deliverables=["t1"],
                    approval_points=["t1"] if task.requires_approval else [])

    # -- completion ---------------------------------------------------------------------------------------------------
    async def _finish(self, db: Any, run: AIRun, ctx: RunContext, plan: Plan, result: ExecutionResult, executor: Executor) -> None:
        if result.status == "awaiting_approval":
            task = next((t for t in executor.tasks if t.task_key == result.awaiting_task_key), None)
            if result.awaiting is not None:
                await self.gate.pause_for_tool(db, run, task, result.awaiting)
            else:
                run.status = RunStatus.awaiting_approval
                await ledger.safe_commit(db)
            return
        assembled = await self.assemble_result(db, run, ctx, plan, result, executor)
        if result.status == "cancelled":
            await ledger.run_cancelled(db, run, partial_result=assembled)
            await self._assistant_message(db, run, "Run cancelled. Partial results were kept.", assembled)
            return
        if result.status == "failed":
            await ledger.run_failed(db, run, result.error or "run failed", partial_result=assembled)
            await self._assistant_message(db, run, f"I couldn't finish: {result.error}", assembled)
            return
        summary = assembled.get("reasoning_summary") or ""
        await ledger.run_completed(db, run, assembled, summary)
        text = self._completion_text(plan, assembled)
        await self._assistant_message(db, run, text, assembled)
        await MemoryService().write_run_memories(db, run, assembled, messages=ctx.conversation + [
            Message(role="user", content=ctx.message or plan.goal), Message(role="assistant", content=text)])

    async def assemble_result(self, db: Any, run: AIRun, ctx: RunContext, plan: Plan, result: ExecutionResult,
                              executor: Executor) -> dict[str, Any]:
        deliverables: dict[str, Any] = {}
        for ref in plan.deliverables:
            val = resolve_ref(ref, result.outputs, ctx)
            if val is not None:
                deliverables[ref] = val
        if not deliverables:
            consumed = {d for t in plan.tasks for d in t.depends_on}
            for t in plan.tasks:
                if t.id not in consumed and t.id in result.outputs:
                    deliverables[t.id] = result.outputs[t.id]
        sources = await result.tracker.resolve_sources(db, run.workspace_id, set(result.tracker.source_ids) or None)
        bullets: list[str] = []
        for t in executor.tasks:
            r = result.reasoning.get(t.task_key)
            if r:
                bullets.append(f"{t.label}: " + " ".join(x.strip().rstrip(".") + "." for x in r[:2]))
        if result.error:
            bullets.append(f"Failed: {result.error}")
        reasoning_summary = "\n".join(f"- {b}" for b in bullets[:8])
        actions = [{"approval_id": str(a.id), "description": (a.payload or {}).get("description"), "status": a.status.value,
                    "kind": a.kind} for a in await self.gate.approvals_for_run(db, run.id)]
        tasks = [{"key": t.task_key, "label": t.label, "agent": t.agent_id, "action": t.action, "status": t.status.value,
                  "cost_usd": float(t.cost_usd or 0), "error": t.error} for t in executor.tasks]
        return {"goal": plan.goal, "deliverables": deliverables, "sources": sources, "reasoning_summary": reasoning_summary,
                "actions": actions, "errors": result.errors,
                "cost": {"cost_usd": float(run.cost_usd or 0), "tokens_in": int(run.tokens_in or 0),
                         "tokens_out": int(run.tokens_out or 0), "cached_tokens": int(run.cached_tokens or 0),
                         "budget_usd": ctx.budget.max_cost_usd},
                "tasks": tasks}

    @staticmethod
    def _completion_text(plan: Plan, assembled: dict[str, Any]) -> str:
        keys = list(assembled.get("deliverables", {}).keys())
        n_sources = len(assembled.get("sources", []) or [])
        parts = [f"Done: {plan.goal}."]
        if keys:
            parts.append(f"Deliverables: {', '.join(keys[:6])}.")
        if n_sources:
            parts.append(f"{n_sources} source(s) cited.")
        pending = [a for a in assembled.get("actions", []) if a.get("status") == "pending"]
        if pending:
            parts.append(f"{len(pending)} action(s) await your approval.")
        if assembled.get("reasoning_summary"):
            parts.append("\n" + assembled["reasoning_summary"])
        return " ".join(parts)

    async def _complete_with_text(self, db: Any, run: AIRun, ctx: RunContext, text: str, *, kind: str) -> None:
        result = {"deliverables": {}, "sources": [], "reasoning_summary": "", "actions": [], kind: text,
                  "cost": {"cost_usd": float(run.cost_usd or 0), "tokens_in": int(run.tokens_in or 0),
                           "tokens_out": int(run.tokens_out or 0)}, "intent": run.intent}
        await ledger.run_completed(db, run, result, None)
        await self._assistant_message(db, run, text, result)

    async def _assistant_message(self, db: Any, run: AIRun, text: str, result: dict[str, Any] | None = None) -> None:
        if db is None or run.conversation_id is None:
            return
        try:
            content = {"text": text, "run_id": str(run.id), "status": run.status.value if hasattr(run.status, "value") else str(run.status)}
            if result:
                content["deliverable_keys"] = list((result.get("deliverables") or {}).keys())[:20]
                content["sources_count"] = len(result.get("sources") or [])
            db.add(AIMessage(workspace_id=run.workspace_id, conversation_id=run.conversation_id, role="assistant", content=content,
                             run_id=run.id))
            await ledger.safe_commit(db)
        except Exception as e:  # noqa: BLE001
            log.warning("orchestrator.assistant_message_failed", error=str(e)[:200])


def _canned_reply(intent: str) -> str:
    return {
        "smalltalk": "Hi! Ask me to research a topic, analyze competitors, find trends, generate ideas, write or repurpose posts, "
                     "plan a calendar, analyze performance or draft a report.",
        "question_about_data": "I can look that up if you tell me which brand, platform and period you mean.",
        "configure_automation": "Automations are configured from the Automations page; tell me what you want to automate and I'll "
                                "describe the workflow to set up.",
        "unknown": "I'm not sure what you'd like me to do. Try: 'research X', 'write 3 LinkedIn posts about Y', or 'analyze last month'.",
    }.get(intent, "Okay.")

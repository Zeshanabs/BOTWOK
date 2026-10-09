"""ApprovalGate (doc 05 §5.2.8): pause a run on APPROVAL tools / spend confirmation, execute the proposed action through
the owning deterministic service on approve (the tool body), store the result, and resume via re-enqueue."""
from __future__ import annotations

from datetime import UTC, datetime
from typing import Any
from uuid import UUID

from sqlalchemy import select

from app.agents.orchestrator import ledger
from app.core.errors import ProblemError, not_found
from app.core.logging import get_logger
from app.models.ai import AIRun, AITask, AIToolCall
from app.models.enums import ApprovalStatus, RunStatus
from app.models.platform import Approval
from app.tools.registry import ToolContext, load_builtin_tools, registry
from app.tools.runner import AwaitingApproval, fingerprint, to_jsonable

log = get_logger("ai.approvals")
AI_KINDS = ("ai_action", "spend")


class ApprovalGate:
    # -- pause --------------------------------------------------------------------------------------------------------
    async def pause_for_tool(self, db: Any, run: AIRun, task: AITask | None, awaiting: AwaitingApproval) -> None:
        desc = f"{awaiting.tool_name}: {ledger.dumps(awaiting.tool_args)[:200]}"
        await ledger.run_awaiting_approval(db, run, task, awaiting.approval_id, desc, kind="ai_action")

    async def pause_for_spend(self, db: Any, run: AIRun, estimated_cost: float, threshold: float) -> Approval:
        approval = Approval(workspace_id=run.workspace_id, brand_id=run.brand_id, kind="spend", target_type="ai_run", target_id=run.id,
                            payload={"estimated_cost_usd": estimated_cost, "threshold_usd": threshold,
                                     "description": f"Projected cost ${estimated_cost:.2f} exceeds the confirmation threshold ${threshold:.2f}"},
                            status=ApprovalStatus.pending, requested_by=f"user:{run.user_id}" if run.user_id else "system")
        db.add(approval)
        await db.flush()
        await ledger.run_awaiting_approval(db, run, None, approval.id, approval.payload["description"], kind="spend")
        return approval

    # -- queries ------------------------------------------------------------------------------------------------------
    async def pending_for_run(self, db: Any, run_id: UUID) -> list[Approval]:
        rows = (await db.execute(select(Approval).where(Approval.target_type == "ai_run", Approval.target_id == run_id,
                                                        Approval.status == ApprovalStatus.pending))).scalars().all()
        return list(rows or [])

    async def approvals_for_run(self, db: Any, run_id: UUID) -> list[Approval]:
        rows = (await db.execute(select(Approval).where(Approval.target_type == "ai_run", Approval.target_id == run_id)
                                 .order_by(Approval.created_at))).scalars().all()
        return list(rows or [])

    async def approval_results_for_task(self, db: Any, run_id: UUID, task_id: UUID) -> tuple[dict[str, Any], bool]:
        """(fingerprint -> stored result for decided ai_action approvals of this task, has_pending)."""
        results: dict[str, Any] = {}
        pending = False
        for a in await self.approvals_for_run(db, run_id):
            if a.kind != "ai_action" or str((a.payload or {}).get("task_id")) != str(task_id):
                continue
            if a.status == ApprovalStatus.pending:
                pending = True
                continue
            fp = (a.payload or {}).get("fingerprint") or fingerprint(a.payload.get("tool", ""), a.payload.get("args", {}))
            results[fp] = {**(a.payload.get("result") or {"rejected": a.status != ApprovalStatus.approved}),
                           "approval_id": str(a.id), "approval_status": a.status.value}
        return results, pending

    # -- decisions ----------------------------------------------------------------------------------------------------
    async def decide(self, db: Any, approval_id: UUID, decision: str, *, member: Any = None, comment: str | None = None,
                     resume: bool = True) -> dict[str, Any]:
        """Approve/reject an `ai_action` or `spend` approval (standalone path; ApprovalService uses the hooks below)."""
        approval = await db.get(Approval, approval_id)
        if approval is None or approval.kind not in AI_KINDS:
            raise not_found("Approval")
        if approval.status != ApprovalStatus.pending:
            raise ProblemError(409, "conflict", "Approval already decided", f"status={approval.status.value}")
        if member is not None and getattr(member, "workspace_id", approval.workspace_id) != approval.workspace_id:
            raise not_found("Approval")
        decision = decision.lower()
        if decision not in ("approve", "reject"):
            raise ProblemError(422, "validation_error", "Validation failed", "decision must be approve|reject")
        approval.status = ApprovalStatus.approved if decision == "approve" else ApprovalStatus.rejected
        approval.decided_by = getattr(getattr(member, "user", None), "id", None)
        approval.decided_at = datetime.now(UTC)
        approval.decision_comment = comment
        await db.flush()
        await self._audit(db, member, f"ai_approval.{decision}", approval)
        return await self.apply(db, approval, decision, member=member, comment=comment, resume=resume)

    async def apply(self, db: Any, approval: Approval, decision: str, *, member: Any = None, comment: str | None = None,
                    resume: bool = True) -> dict[str, Any]:
        """Execute the consequences of an already-decided approval: run the proposed action through the owning service
        (approve) or record the rejection, store the result on the approval + ai_tool_calls row, and resume the run."""
        if approval.kind not in AI_KINDS:
            raise not_found("Approval")
        decision = decision.lower()
        run = await db.get(AIRun, approval.target_id)
        payload = dict(approval.payload or {})
        if payload.get("result") is not None:                      # idempotent: already applied
            return {"approval_id": str(approval.id), "status": approval.status.value, "result": payload["result"],
                    "resumed": False, "run_id": str(approval.target_id)}
        if decision == "reject":
            result: dict[str, Any] = {"rejected": True, "reason": comment or approval.decision_comment or "rejected by approver"}
        elif approval.kind == "spend":
            result = {"confirmed": True}
            if run is not None:
                run.input = {**(run.input or {}), "confirmed_spend": True}
        else:
            result = await self._execute(db, approval, run, payload, member)
        payload["result"] = to_jsonable(result)
        approval.payload = payload
        row_id = payload.get("tool_call_row_id")
        if row_id:
            row = await db.get(AIToolCall, UUID(str(row_id)))
            if row is not None:
                row.status = "succeeded" if decision == "approve" else "denied"
                row.result = {"data": payload["result"], "truncated": False}
                row.finished_at = datetime.now(UTC)
        await db.flush()
        resumed = False
        if run is not None and resume:
            still_pending = [a for a in await self.pending_for_run(db, run.id) if a.id != approval.id]
            if not still_pending and run.status in (RunStatus.awaiting_approval, RunStatus.paused):
                run.status = RunStatus.paused
                await db.flush()
                try:
                    from app.agents.orchestrator.service import enqueue_job
                    await enqueue_job("jobs.ai.resume", run.id, run.workspace_id)
                    resumed = True
                except Exception as e:  # noqa: BLE001
                    log.warning("approval.resume_enqueue_failed", error=str(e)[:200])
        return {"approval_id": str(approval.id), "status": approval.status.value, "result": payload["result"], "resumed": resumed,
                "run_id": str(approval.target_id)}

    async def _execute(self, db: Any, approval: Approval, run: AIRun | None, payload: dict[str, Any], member: Any) -> dict[str, Any]:
        load_builtin_tools()
        tool = registry.get(str(payload.get("tool") or ""))
        if tool is None:
            return {"executed": False, "error": f"tool {payload.get('tool')} is not registered"}
        ctx = ToolContext(workspace_id=approval.workspace_id, brand_id=approval.brand_id,
                          user_id=getattr(getattr(member, "user", None), "id", None),
                          role=str(getattr(getattr(member, "role", None), "value", getattr(member, "role", "approver")) or "approver"),
                          run_id=approval.target_id, task_id=UUID(payload["task_id"]) if payload.get("task_id") else None,
                          agent_id=payload.get("agent_id"), db=db)
        try:
            args = tool.validate_args(payload.get("args") or {})
            res = await tool.fn(ctx, **args)
            data = to_jsonable(res)
            if not isinstance(data, dict):
                data = {"result": data}
            data.setdefault("executed", True)
            return data
        except Exception as e:  # noqa: BLE001 - execution failure is reported back to the agent, not raised to the approver
            log.warning("approval.execute_failed", tool=tool.name, error=str(e)[:300])
            return {"executed": False, "error": f"{type(e).__name__}: {str(e)[:300]}"}

    @staticmethod
    async def _audit(db: Any, member: Any, action: str, approval: Approval) -> None:
        if member is None:
            return
        try:
            from app.services.audit_service import audit
            await audit(db, member, action, "approval", str(approval.id), before=None,
                        after={"status": approval.status.value, "kind": approval.kind})
        except Exception:  # noqa: BLE001
            pass


async def handle_decision(db: Any, approval_id: UUID, decision: str, *, member: Any = None, comment: str | None = None) -> dict[str, Any]:
    """Standalone entry point: decide + apply for approvals with kind in ('ai_action', 'spend')."""
    return await ApprovalGate().decide(db, approval_id, decision, member=member, comment=comment)


async def on_approved(db: Any, approval: Approval) -> dict[str, Any]:
    """Hook called by ApprovalService.approve after it marked the approval approved (kind ai_action|spend)."""
    return await ApprovalGate().apply(db, approval, "approve", comment=approval.decision_comment)


async def on_rejected(db: Any, approval: Approval) -> dict[str, Any]:
    """Hook called by ApprovalService.reject after it marked the approval rejected."""
    return await ApprovalGate().apply(db, approval, "reject", comment=approval.decision_comment)

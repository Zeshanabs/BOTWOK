"""BudgetGuard (doc 05 §5.2.10, doc 20 §20.5): per-run, per-day and per-month cost gates + usage_ledger writes."""
from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.core.errors import ProblemError
from app.core.events import emit
from app.core.logging import get_logger
from app.core.pricing import estimate_tokens_cost
from app.models.platform import UsageBudget, UsageLedger

log = get_logger("budget")
THRESHOLD = 0.8


class BudgetExceeded(ProblemError):
    def __init__(self, detail: str, *, scope: str = "run", limit: float = 0.0, spent: float = 0.0):
        super().__init__(402, "budget_exceeded", "Budget exceeded", detail)
        self.scope = scope
        self.limit = limit
        self.spent = spent


def period_start(period: str, now: datetime | None = None) -> datetime:
    now = now or datetime.now(UTC)
    if period == "month":
        return now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    if period == "week":
        start = now - timedelta(days=now.weekday())
        return start.replace(hour=0, minute=0, second=0, microsecond=0)
    return now.replace(hour=0, minute=0, second=0, microsecond=0)


class BudgetGuard:
    def __init__(self) -> None:
        self._threshold_emitted: set[str] = set()

    # -- estimates --------------------------------------------------------------------------------------------------
    @staticmethod
    def estimate(provider: str, model: str, tokens_in: int, tokens_out: int) -> float:
        return estimate_tokens_cost(provider, model, tokens_in, tokens_out)

    @staticmethod
    def run_budget(run: Any) -> float:
        b = getattr(run, "budget", None) or {}
        try:
            return float(b.get("max_cost_usd") or settings.default_run_budget_usd)
        except (TypeError, ValueError):
            return float(settings.default_run_budget_usd)

    @staticmethod
    def run_spent(run: Any) -> float:
        return float(getattr(run, "cost_usd", 0) or 0)

    # -- queries ----------------------------------------------------------------------------------------------------
    async def spent_in_period(self, db: AsyncSession, workspace_id: UUID, kind: str, period: str) -> float:
        start = period_start(period)
        q = select(func.coalesce(func.sum(UsageLedger.cost_usd), 0)).where(
            UsageLedger.workspace_id == workspace_id, UsageLedger.kind == kind, UsageLedger.occurred_at >= start)
        try:
            val = (await db.execute(q)).scalar()
        except Exception as e:  # noqa: BLE001 - ledger unavailable → treat as 0 (never block on observability)
            log.warning("budget.ledger_query_failed", error=str(e)[:200])
            return 0.0
        return float(val or 0)

    async def budgets(self, db: AsyncSession, workspace_id: UUID, kind: str = "ai_cost") -> list[UsageBudget]:
        try:
            rows = (await db.execute(select(UsageBudget).where(UsageBudget.workspace_id == workspace_id,
                                                               UsageBudget.kind == kind))).scalars().all()
        except Exception as e:  # noqa: BLE001
            log.warning("budget.budgets_query_failed", error=str(e)[:200])
            return []
        return list(rows or [])

    # -- gate -------------------------------------------------------------------------------------------------------
    async def check(self, db: AsyncSession | None, workspace_id: UUID, run: Any, estimated_cost: float) -> None:
        """Raise BudgetExceeded (402) when `estimated_cost` would push the run or a hard workspace budget over its limit.
        Emits BUDGET_THRESHOLD_REACHED once per scope at 80%."""
        estimated_cost = float(estimated_cost or 0)
        run_id = str(getattr(run, "id", "")) if run is not None else ""
        if run is not None:
            limit = self.run_budget(run)
            spent = self.run_spent(run)
            if limit > 0 and spent + estimated_cost > limit:
                await self._emit(db, workspace_id, "BUDGET_EXCEEDED", {"scope": "run", "run_id": run_id, "limit_usd": limit,
                                                                       "spent_usd": spent, "estimated_usd": estimated_cost})
                raise BudgetExceeded(f"Run budget ${limit:.2f} exceeded (spent ${spent:.4f}, next call ≈ ${estimated_cost:.4f})",
                                     scope="run", limit=limit, spent=spent)
            if limit > 0 and spent + estimated_cost >= THRESHOLD * limit:
                await self._threshold(db, workspace_id, f"run:{run_id}", "run", limit, spent + estimated_cost, run_id)
        if db is None:
            return
        for b in await self.budgets(db, workspace_id, "ai_cost"):
            spent = await self.spent_in_period(db, workspace_id, "ai_cost", b.period)
            limit = float(b.limit_value or 0)
            if limit <= 0:
                continue
            if spent + estimated_cost > limit:
                await self._emit(db, workspace_id, "BUDGET_EXCEEDED", {"scope": b.period, "kind": "ai_cost", "limit_usd": limit,
                                                                       "spent_usd": spent, "hard": bool(b.hard), "run_id": run_id})
                if b.hard:
                    raise BudgetExceeded(f"Workspace {b.period} AI budget ${limit:.2f} exceeded (spent ${spent:.2f})",
                                         scope=b.period, limit=limit, spent=spent)
            elif spent + estimated_cost >= THRESHOLD * limit:
                await self._threshold(db, workspace_id, f"{b.period}:{period_start(b.period).date()}", b.period, limit,
                                      spent + estimated_cost, run_id)

    async def _threshold(self, db, workspace_id: UUID, key: str, scope: str, limit: float, spent: float, run_id: str) -> None:
        if key in self._threshold_emitted:
            return
        self._threshold_emitted.add(key)
        await self._emit(db, workspace_id, "BUDGET_THRESHOLD_REACHED",
                         {"scope": scope, "limit_usd": limit, "spent_usd": round(spent, 6), "threshold": THRESHOLD, "run_id": run_id})

    async def _emit(self, db, workspace_id: UUID, name: str, payload: dict[str, Any]) -> None:
        if db is None:
            return
        try:
            await emit(db, name, payload, workspace_id=workspace_id, actor={"type": "system", "component": "BudgetGuard"})
        except Exception as e:  # noqa: BLE001
            log.warning("budget.emit_failed", event=name, error=str(e)[:200])

    # -- ledger -----------------------------------------------------------------------------------------------------
    async def record(self, db: AsyncSession | None, workspace_id: UUID, cost: float, tokens: int, ref: Any, *,
                     provider: str | None = None, model: str | None = None, kind: str = "ai_cost",
                     ref_type: str = "ai_run") -> None:
        """Append a usage_ledger row (quantity = tokens for ai_cost; cost in USD). `ref` = run id (UUID|str) or obj with .id."""
        if db is None:
            return
        ref_id = getattr(ref, "id", ref)
        try:
            ref_uuid = UUID(str(ref_id)) if ref_id else None
        except ValueError:
            ref_uuid = None
        row = UsageLedger(workspace_id=workspace_id, kind=kind, provider=provider, model=model, quantity=float(tokens or 0),
                          cost_usd=float(cost or 0), ref_type=ref_type, ref_id=ref_uuid, occurred_at=datetime.now(UTC))
        db.add(row)
        try:
            await db.flush()
        except Exception as e:  # noqa: BLE001
            log.warning("budget.ledger_write_failed", error=str(e)[:200])

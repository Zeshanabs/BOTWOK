"""Agent registry: the 13 AgentSpecs, Agent instances, and `seed_agents(db)` (idempotent upsert into ai_agents)."""
from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.agents.base import Agent, AgentSpec
from app.agents.competitor_intel import CompetitorIntelAgent
from app.agents.critic import CriticAgent
from app.agents.fact_check import FactCheckAgent
from app.agents.ideation import IdeationAgent
from app.agents.performance_analyst import PerformanceAnalystAgent
from app.agents.report import ReportAgent
from app.agents.repurposer import RepurposerAgent
from app.agents.research import ResearchAgent
from app.agents.social_listening import SocialListeningAgent
from app.agents.specs import ALL_SPECS, ORCHESTRATION_SPECS, SPECS
from app.agents.strategy import StrategyAgent
from app.agents.trend import TrendAgent
from app.agents.visual import VisualAgent
from app.agents.writer import WriterAgent
from app.core.logging import get_logger
from app.models.ai import AIAgent

log = get_logger("agents.registry")

AGENT_CLASSES: dict[str, type[Agent]] = {
    "research": ResearchAgent, "social_listening": SocialListeningAgent, "competitor_intel": CompetitorIntelAgent,
    "trend": TrendAgent, "strategy": StrategyAgent, "ideation": IdeationAgent, "writer": WriterAgent,
    "repurposer": RepurposerAgent, "visual": VisualAgent, "critic": CriticAgent, "fact_check": FactCheckAgent,
    "performance_analyst": PerformanceAnalystAgent, "report": ReportAgent,
}
AGENT_IDS: list[str] = list(SPECS)
_instances: dict[str, Agent] = {}


def get_spec(agent_id: str) -> AgentSpec:
    if agent_id not in ALL_SPECS:
        raise KeyError(f"unknown agent {agent_id!r}")
    return ALL_SPECS[agent_id]


def has_agent(agent_id: str) -> bool:
    return agent_id in SPECS


def get_agent(agent_id: str) -> Agent:
    if agent_id not in _instances:
        if agent_id in AGENT_CLASSES:
            _instances[agent_id] = AGENT_CLASSES[agent_id]()
        elif agent_id in ORCHESTRATION_SPECS:
            _instances[agent_id] = Agent(ORCHESTRATION_SPECS[agent_id])
        else:
            raise KeyError(f"unknown agent {agent_id!r}")
    return _instances[agent_id]


def list_specs(include_orchestration: bool = False) -> list[AgentSpec]:
    return list(ALL_SPECS.values()) if include_orchestration else list(SPECS.values())


def catalog_for_planner() -> list[dict[str, Any]]:
    return [{"id": s.id, "tier": s.tier, "description": s.description, "actions": list(s.actions),
             "approval_actions": [a for a, spec in s.actions.items() if spec.approval]} for s in SPECS.values()]


async def enabled_agent_ids(db: AsyncSession | None) -> set[str]:
    """Agent ids enabled in ai_agents (all registry agents when the table is empty/unavailable)."""
    if db is None:
        return set(SPECS)
    try:
        from sqlalchemy import select
        rows = (await db.execute(select(AIAgent.id, AIAgent.enabled))).all()
    except Exception as e:  # noqa: BLE001
        log.warning("agents.enabled_query_failed", error=str(e)[:200])
        return set(SPECS)
    if not rows:
        return set(SPECS)
    enabled = {r[0] for r in rows if r[1]}
    return {a for a in SPECS if a in enabled or a not in {r[0] for r in rows}}


async def seed_agents(db: AsyncSession) -> int:
    """Upsert ai_agents rows for every spec (keeps `enabled` as set by admins). Idempotent."""
    n = 0
    now = datetime.now(UTC)
    for spec in ALL_SPECS.values():
        values = {"id": spec.id, "name": spec.name or spec.id, "description": spec.description, "tier": spec.tier,
                  "tools": list(spec.tools), "actions": spec.actions_catalog(),
                  "limits": {**spec.limits(), "orchestration": spec.orchestration}, "updated_at": now}
        stmt = pg_insert(AIAgent).values(**values)
        stmt = stmt.on_conflict_do_update(index_elements=[AIAgent.id],
                                          set_={k: v for k, v in values.items() if k != "id"})
        await db.execute(stmt)
        n += 1
    await db.flush()
    return n

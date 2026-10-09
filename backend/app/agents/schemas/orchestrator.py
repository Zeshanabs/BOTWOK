"""IntentResult, Plan/PlanTask (doc 05 §5.2.3–5.2.4)."""
from __future__ import annotations

from typing import Any

from pydantic import Field, field_validator

from app.agents.schemas.common import StrictBase

INTENTS: tuple[str, ...] = (
    "research_topic", "research_competitors", "find_trends", "find_news", "analyze_competitor_content",
    "strategy_recommendation", "generate_ideas", "write_post", "repurpose", "generate_media", "build_calendar",
    "schedule", "publish", "analyze_performance", "report", "configure_automation", "question_about_data",
    "smalltalk", "unknown",
)


class IntentResult(StrictBase):
    intent: str = "unknown"
    intents: list[str] = Field(default_factory=list, description="all detected intents (multi-intent allowed)")
    entities: dict[str, Any] = Field(default_factory=dict)
    capabilities: list[str] = Field(default_factory=list)
    clarification_needed: bool = False
    question: str | None = None
    confidence: float | None = Field(default=None, ge=0, le=1)
    reply: str | None = Field(default=None, description="direct answer for smalltalk / question_about_data")

    @field_validator("intent")
    @classmethod
    def _known(cls, v: str) -> str:
        return v if v in INTENTS else "unknown"

    @field_validator("intents")
    @classmethod
    def _known_list(cls, v: list[str]) -> list[str]:
        return [x for x in v if x in INTENTS]

    def all_intents(self) -> list[str]:
        out = [self.intent] + [i for i in self.intents if i != self.intent]
        return [i for i in out if i not in ("unknown",)] or [self.intent]


class TaskBudget(StrictBase):
    max_cost_usd: float | None = Field(default=None, ge=0)
    max_tool_calls: int | None = Field(default=None, ge=0)
    max_turns: int | None = Field(default=None, ge=1)


class PlanTask(StrictBase):
    id: str
    agent: str
    action: str
    label: str | None = None
    inputs: dict[str, Any] = Field(default_factory=dict)
    depends_on: list[str] = Field(default_factory=list)
    fan_out: str | None = Field(default=None, description="reference like t1.competitors to fan out over")
    optional: bool = False
    budget: TaskBudget | None = None
    requires_approval: bool = False


class Plan(StrictBase):
    goal: str
    tasks: list[PlanTask] = Field(default_factory=list)
    approval_points: list[str] = Field(default_factory=list)
    deliverables: list[str] = Field(default_factory=list)
    estimated_cost_usd: float | None = None
    notes: str | None = None

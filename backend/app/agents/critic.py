from __future__ import annotations

from typing import Any

from pydantic import BaseModel

from app.agents.base import Agent
from app.agents.specs import SPECS


class CriticAgent(Agent):
    spec = SPECS["critic"]

    async def post_process(self, ctx: Any, action: str, output: BaseModel, inputs: dict[str, Any], tool_results) -> BaseModel:
        """Deterministic post-check: consistent overall/recommend/risk_level; the critic proposes, never edits."""
        s = output.scores  # type: ignore[attr-defined]
        base = (s.quality + s.brand_fit + s.platform_fit + s.clarity + s.hook_strength + s.cta_strength) / 6
        overall = max(0.0, min(1.0, base - 0.5 * s.risk))
        if not output.overall or abs(output.overall - overall) > 0.25:  # type: ignore[attr-defined]
            output.overall = round(overall, 3)  # type: ignore[attr-defined]
        severities = {i.severity for i in output.issues}  # type: ignore[attr-defined]
        if s.risk >= 0.7 or "blocker" in severities:
            output.recommend = "reject"  # type: ignore[attr-defined]
        elif output.overall >= 0.75 and s.risk <= 0.3 and not severities & {"high", "blocker"}:  # type: ignore[attr-defined]
            output.recommend = "approve"  # type: ignore[attr-defined]
        else:
            output.recommend = "revise"  # type: ignore[attr-defined]
        output.risk_level = "high" if s.risk >= 0.7 else "medium" if s.risk >= 0.4 else "low"  # type: ignore[attr-defined]
        return output

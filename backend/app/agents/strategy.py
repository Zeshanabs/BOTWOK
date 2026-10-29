from __future__ import annotations

from typing import Any

from pydantic import BaseModel

from app.agents.base import Agent
from app.agents.specs import SPECS


class StrategyAgent(Agent):
    spec = SPECS["strategy"]

    async def post_process(self, ctx: Any, action: str, output: BaseModel, inputs: dict[str, Any], tool_results) -> BaseModel:
        pillars = getattr(output, "pillars", None)
        if pillars:
            total = sum(p.share for p in pillars)
            if total > 0 and abs(total - 1.0) > 0.02:
                for p in pillars:
                    p.share = round(p.share / total, 3)
        return output

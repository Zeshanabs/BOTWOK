from __future__ import annotations

from typing import Any

from pydantic import BaseModel

from app.agents.base import Agent
from app.agents.specs import SPECS


class PerformanceAnalystAgent(Agent):
    spec = SPECS["performance_analyst"]

    async def post_process(self, ctx: Any, action: str, output: BaseModel, inputs: dict[str, Any], tool_results) -> BaseModel:
        for ins in output.insights:  # type: ignore[attr-defined]
            if ins.n is not None and ins.n < 8:
                ins.early_signal = True
        return output

from __future__ import annotations

from typing import Any

from pydantic import BaseModel

from app.agents.base import Agent
from app.agents.specs import SPECS


class CompetitorIntelAgent(Agent):
    spec = SPECS["competitor_intel"]

    async def post_process(self, ctx: Any, action: str, output: BaseModel, inputs: dict[str, Any], tool_results) -> BaseModel:
        if action == "analyze" and hasattr(output, "data_coverage") and not output.data_coverage:
            platforms = set()
            for r in tool_results:
                if isinstance(r.result, dict) and r.result.get("platform"):
                    platforms.add(str(r.result["platform"]))
            output.data_coverage = {p: "official_api" for p in platforms} or {"_": "not_disclosed"}  # type: ignore[attr-defined]
        return output

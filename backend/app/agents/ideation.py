from __future__ import annotations

from typing import Any

from pydantic import BaseModel

from app.agents.base import Agent
from app.agents.specs import SPECS


class IdeationAgent(Agent):
    spec = SPECS["ideation"]

    async def post_process(self, ctx: Any, action: str, output: BaseModel, inputs: dict[str, Any], tool_results) -> BaseModel:
        ideas = getattr(output, "ideas", None)
        if ideas:
            seen: set[str] = set()
            kept = []
            for idea in ideas:
                key = f"{idea.title.strip().lower()}|{idea.angle.strip().lower()[:60]}"
                if key in seen:
                    output.dropped_as_duplicates = getattr(output, "dropped_as_duplicates", 0) + 1  # type: ignore[attr-defined]
                    continue
                seen.add(key)
                kept.append(idea)
            output.ideas = kept  # type: ignore[attr-defined]
        return output

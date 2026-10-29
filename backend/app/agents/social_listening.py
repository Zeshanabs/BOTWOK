from __future__ import annotations

from typing import Any

from pydantic import BaseModel

from app.agents.base import Agent
from app.agents.specs import SPECS


class SocialListeningAgent(Agent):
    spec = SPECS["social_listening"]

    async def post_process(self, ctx: Any, action: str, output: BaseModel, inputs: dict[str, Any], tool_results) -> BaseModel:
        # Never emit posts for platforms the agent itself marked unavailable (doc 06 eval invariant).
        unavailable = {a.platform for a in getattr(output, "availability", []) if a.status != "official_api"}
        if unavailable and hasattr(output, "posts"):
            output.posts = [p for p in output.posts if p.platform not in unavailable]  # type: ignore[attr-defined]
        return output

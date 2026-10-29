from __future__ import annotations

from typing import Any

from pydantic import BaseModel

from app.agents.base import Agent
from app.agents.specs import SPECS

_BANNED = ("real person", "celebrity", "trademark", "logo of", "cures", "guaranteed returns")


class VisualAgent(Agent):
    spec = SPECS["visual"]

    async def post_process(self, ctx: Any, action: str, output: BaseModel, inputs: dict[str, Any], tool_results) -> BaseModel:
        prompts = getattr(output, "image_prompts", []) or []
        flags = list(getattr(output, "policy_flags", []) or [])
        for p in prompts:
            low = p.lower()
            for b in _BANNED:
                if b in low:
                    flags.append(f"prompt mentions '{b}'")
        if flags:
            output.policy_flags = sorted(set(flags))  # type: ignore[attr-defined]
        if not getattr(output, "alt_text", None):
            output.alt_text = (getattr(output, "concept", "") or "Brand visual")[:125]  # type: ignore[attr-defined]
        return output

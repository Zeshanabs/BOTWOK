from __future__ import annotations

from typing import Any

from pydantic import BaseModel

from app.agents.base import Agent
from app.agents.specs import SPECS


class ResearchAgent(Agent):
    spec = SPECS["research"]

    async def post_process(self, ctx: Any, action: str, output: BaseModel, inputs: dict[str, Any], tool_results) -> BaseModel:
        # Findings without sources are demoted into gaps so nothing unsourced reads as a fact.
        findings = getattr(output, "key_findings", None)
        if findings is not None:
            keep, gaps = [], list(getattr(output, "gaps", []) or [])
            for f in findings:
                if f.sources:
                    keep.append(f)
                else:
                    gaps.append(f"Unsourced finding dropped: {f.text[:160]}")
            output.key_findings = keep  # type: ignore[attr-defined]
            output.gaps = gaps  # type: ignore[attr-defined]
        return output

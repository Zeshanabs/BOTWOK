from __future__ import annotations

from typing import Any

from pydantic import BaseModel

from app.agents.base import Agent
from app.agents.specs import SPECS

REGULATED = ("health", "medical", "finance", "financial", "legal")


class FactCheckAgent(Agent):
    spec = SPECS["fact_check"]

    async def post_process(self, ctx: Any, action: str, output: BaseModel, inputs: dict[str, Any], tool_results) -> BaseModel:
        """Claim loop (doc 06/19): contradicted → blocking; unverifiable in regulated domains → high risk; evidence must be real."""
        seen_sources: set[str] = set()
        seen_urls: set[str] = set()
        for r in tool_results:
            seen_sources.update(r.source_ids)
            seen_urls.update(r.urls)
        for s in inputs.get("sources", []) or []:
            if isinstance(s, dict):
                if s.get("source_id"):
                    seen_sources.add(str(s["source_id"]))
                if s.get("url"):
                    seen_urls.add(str(s["url"]).rstrip("/"))
        risk = "low"
        blocking = False
        for c in output.claims:  # type: ignore[attr-defined]
            c.evidence = [e for e in c.evidence if (e.source_id and e.source_id in seen_sources) or
                          (e.url and e.url.rstrip("/") in seen_urls) or (not seen_sources and not seen_urls)]
            if c.verdict == "supported" and not c.evidence:
                c.verdict = "unverifiable"
            if c.verdict == "contradicted":
                blocking = True
                risk = "high"
            elif c.verdict == "unverifiable":
                dom = (c.regulated_domain or "").lower()
                if any(k in dom for k in REGULATED):
                    risk = "high"
                elif risk == "low":
                    risk = "medium"
        output.overall_risk = risk  # type: ignore[attr-defined]
        output.blocking = blocking  # type: ignore[attr-defined]
        output.requires_human = blocking or risk != "low" or any(c.verdict not in ("supported", "opinion") for c in output.claims)  # type: ignore[attr-defined]
        return output

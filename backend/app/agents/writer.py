from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ValidationError

from app.agents.base import Agent, log
from app.agents.specs import SPECS
from app.tools.registry import registry


class WriterAgent(Agent):
    spec = SPECS["writer"]

    async def post_process(self, ctx: Any, action: str, output: BaseModel, inputs: dict[str, Any], tool_results) -> BaseModel:
        """Persist through content.create_draft when registered and the agent did not already do it."""
        if getattr(output, "content_id", None) or inputs.get("persist") is False:
            return output
        t = registry.get("content.create_draft")
        tool_ctx = getattr(ctx, "tool_context", None)
        if t is None or tool_ctx is None or getattr(tool_ctx, "db", None) is None:
            return output
        args = {"title": getattr(output, "title", None) or getattr(output, "hook", "")[:120], "hook": output.hook,  # type: ignore[attr-defined]
                "body": output.body, "cta": output.cta, "hashtags": output.hashtags, "keywords": output.keywords,  # type: ignore[attr-defined]
                "platform": output.platform or inputs.get("platform"), "format": output.format or inputs.get("format"),  # type: ignore[attr-defined]
                "content_type": output.content_type or inputs.get("content_type"), "alt_text": output.alt_text,  # type: ignore[attr-defined]
                "visual_concept": output.visual_concept, "idea_id": inputs.get("idea_id"),  # type: ignore[attr-defined]
                "sources": [s.model_dump() for s in output.sources], "generation_metadata": output.generation_metadata.model_dump()}  # type: ignore[attr-defined]
        try:
            valid = t.validate_args({k: v for k, v in args.items() if v is not None})
            res = await t.fn(tool_ctx, **valid)
            data = res.model_dump() if hasattr(res, "model_dump") else (res if isinstance(res, dict) else {})
            cid = data.get("content_id") or data.get("id")
            if cid:
                output.content_id = str(cid)  # type: ignore[attr-defined]
            if data.get("variant_id"):
                output.variant_id = str(data["variant_id"])  # type: ignore[attr-defined]
        except (ValidationError, Exception) as e:  # noqa: BLE001 - draft stays in the output
            log.warning("writer.persist_failed", error=str(e)[:200])
        return output

"""condition — evaluates a sandboxed boolean expression over the run context; branch ``true`` / ``false``."""
from __future__ import annotations

from typing import Any

from app.workflows.expressions import ExpressionError
from app.workflows.nodes.base import NodeContext, NodeError


async def run(ctx: NodeContext, config: dict[str, Any]) -> dict[str, Any]:
    expr = str(config.get("expression") or "")
    try:
        value = ctx.evaluate(expr)
    except ExpressionError as e:
        raise NodeError(f"condition {expr!r}: {e}") from e
    result = bool(value)
    return {"result": result, "branch": "true" if result else "false", "expression": expr}

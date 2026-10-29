"""Glue between research/competitor/trend tools and the AI core's tool registry.

Imports ``app.tools.registry`` lazily; if the AI core isn't present the local fallback decorator records the metadata on
the function (``fn.__tool_meta__``) and in ``FALLBACK_TOOLS`` so tools stay importable and testable.
"""
from __future__ import annotations

import enum
import inspect
from collections.abc import AsyncIterator, Callable
from contextlib import asynccontextmanager
from typing import Any
from uuid import UUID

FALLBACK_TOOLS: dict[str, dict[str, Any]] = {}

try:  # AI core present
    from app.tools.registry import SideEffect, ToolContext
    from app.tools.registry import tool as _core_tool
except ImportError:  # pragma: no cover - exercised only when the AI core is absent
    class SideEffect(enum.StrEnum):  # type: ignore[no-redef]
        READ = "READ"
        WRITE_INTERNAL = "WRITE_INTERNAL"
        EXTERNAL_READ = "EXTERNAL_READ"
        SPEND = "SPEND"
        APPROVAL = "APPROVAL"
        EXTERNAL_WRITE = "EXTERNAL_WRITE"

    ToolContext = Any  # type: ignore[misc,assignment]
    _core_tool = None


def tool(name: str, side_effect: Any = "READ", **meta: Any) -> Callable[[Callable[..., Any]], Callable[..., Any]]:
    """Register with the AI core's ``@tool`` when available (passing only the kwargs it accepts)."""
    if _core_tool is not None:
        accepted = set(inspect.signature(_core_tool).parameters)
        kwargs = {k: v for k, v in meta.items() if k in accepted}
        return _core_tool(name, side_effect=side_effect, **kwargs)

    def deco(fn: Callable[..., Any]) -> Callable[..., Any]:
        info = {"name": name, "side_effect": str(getattr(side_effect, "value", side_effect)), **meta, "fn": fn}
        FALLBACK_TOOLS[name] = info
        fn.__tool_meta__ = info  # type: ignore[attr-defined]
        return fn
    return deco


def ctx_workspace(ctx: Any) -> UUID:
    ws = getattr(ctx, "workspace_id", None)
    if ws is None:
        raise ValueError("tool context has no workspace_id")
    return ws if isinstance(ws, UUID) else UUID(str(ws))


def ctx_actor(ctx: Any) -> dict[str, Any]:
    agent = getattr(ctx, "agent_id", None)
    if agent:
        return {"type": "agent", "id": agent, "run_id": str(getattr(ctx, "run_id", "") or "") or None}
    uid = getattr(ctx, "user_id", None)
    return {"type": "user", "id": str(uid)} if uid else {"type": "system"}


@asynccontextmanager
async def tool_db(ctx: Any) -> AsyncIterator[Any]:
    """The run's session when the tool executes inside a run (the runner commits), else a fresh unit of work."""
    db = getattr(ctx, "db", None)
    if db is not None:
        yield db
        return
    session_fn = getattr(ctx, "session", None)
    if callable(session_fn):
        async with session_fn() as s:
            yield s
        return
    from app.core.db import session_scope
    async with session_scope(ctx_workspace(ctx)) as s:
        yield s

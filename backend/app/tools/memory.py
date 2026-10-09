"""memory.search / memory.remember — semantic memory (pgvector cosine on `memories`) through MemoryService."""
from __future__ import annotations

from app.tools.registry import SideEffect, ToolContext, tool

KINDS = ("preference", "performance", "strategy", "conversation_summary", "note", "content")


@tool("memory.search", side_effect=SideEffect.READ, timeout_s=15, idempotent=True)
async def memory_search(ctx: ToolContext, query: str, kinds: list[str] | None = None, k: int = 8) -> dict:
    """Search long-term memories (preferences, performance insights, strategy notes, past summaries) by meaning."""
    from app.agents.orchestrator.memory import MemoryService
    k = max(1, min(int(k), 20))
    kinds = [x for x in (kinds or []) if x in KINDS] or None
    hits = await MemoryService().search(ctx.db, ctx.workspace_id, query, kinds=kinds, k=k, brand_id=ctx.brand_id)
    return {"query": query, "memories": hits}


@tool("memory.remember", side_effect=SideEffect.WRITE_INTERNAL, timeout_s=15, roles={"editor", "admin", "owner"})
async def memory_remember(ctx: ToolContext, text: str, kind: str = "note", importance: float = 0.5) -> dict:
    """Store a durable note (preference, strategy decision, performance learning) for future runs. Deduplicated."""
    from app.agents.orchestrator.memory import MemoryService
    kind = kind if kind in KINDS else "note"
    mem = await MemoryService().remember(ctx.db, ctx.workspace_id, kind, text, brand_id=ctx.brand_id, user_id=ctx.user_id,
                                         importance=max(0.0, min(1.0, float(importance))),
                                         source_ref={"run_id": str(ctx.run_id) if ctx.run_id else None, "agent_id": ctx.agent_id})
    return {"memory_id": str(mem["id"]), "kind": kind, "deduplicated": mem.get("deduplicated", False)}

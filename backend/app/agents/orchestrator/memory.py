"""MemoryService (doc 15 §15.2): pgvector cosine search over `memories`, deduped writes (cosine > 0.92), read bundle for
the ContextBuilder, conversation summaries at run end."""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import UUID

from sqlalchemy import or_, select

from app.core.ids import new_id
from app.core.logging import get_logger
from app.core.ports.ai_provider import Message
from app.integrations.embeddings.base import cosine
from app.integrations.embeddings.registry import get_embedding_provider
from app.models.ai import AIConversation, AIRun, Memory

log = get_logger("ai.memory")
DEDUPE_THRESHOLD = 0.92
SUMMARY_TTL_DAYS = 90


@dataclass
class MemoryBundle:
    memories: list[dict[str, Any]] = field(default_factory=list)
    preferences: list[dict[str, Any]] = field(default_factory=list)
    conversation_summary: str | None = None

    def snippets(self, limit: int = 8) -> list[dict[str, Any]]:
        return (self.preferences[:3] + self.memories)[:limit]


def _row_dict(m: Memory, similarity: float | None = None, score: float | None = None) -> dict[str, Any]:
    return {"id": str(m.id), "kind": m.kind, "text": m.text, "importance": float(m.importance or 0.5),
            "similarity": similarity, "score": score, "source_ref": m.source_ref or {},
            "created_at": m.created_at.isoformat() if m.created_at else None}


class MemoryService:
    async def embed(self, db: Any, workspace_id: UUID, texts: list[str]) -> list[list[float]] | None:
        try:
            provider = await get_embedding_provider(db, workspace_id)
            return await provider.embed(texts)
        except Exception as e:  # noqa: BLE001 - embeddings are optional; degrade to keyword search
            log.warning("memory.embed_failed", error=str(e)[:200])
            return None

    async def _embedding_model(self, db: Any, workspace_id: UUID) -> str | None:
        try:
            p = await get_embedding_provider(db, workspace_id)
            return f"{p.name}/{p.model}"
        except Exception:  # noqa: BLE001
            return None

    # -- read -------------------------------------------------------------------------------------------------------
    async def search(self, db: Any, workspace_id: UUID, query: str, *, kinds: list[str] | None = None, k: int = 8,
                     brand_id: UUID | None = None, user_id: UUID | None = None) -> list[dict[str, Any]]:
        if db is None or not query:
            return []
        now = datetime.now(UTC)
        base = [Memory.workspace_id == workspace_id, or_(Memory.expires_at.is_(None), Memory.expires_at > now)]
        if brand_id is not None:
            base.append(or_(Memory.brand_id == brand_id, Memory.brand_id.is_(None)))
        if kinds:
            base.append(Memory.kind.in_(kinds))
        vectors = await self.embed(db, workspace_id, [query])
        rows: list[tuple[Memory, float | None]] = []
        try:
            if vectors:
                vec = vectors[0]
                dist = Memory.embedding.cosine_distance(vec)
                res = (await db.execute(select(Memory, dist).where(*base, Memory.embedding.is_not(None))
                                        .order_by(dist).limit(max(k * 3, 10)))).all()
                rows = [(m, 1.0 - float(d)) for m, d in res]
            else:
                words = [w for w in query.lower().split() if len(w) > 3][:6]
                conds = [Memory.text.ilike(f"%{w}%") for w in words] or [Memory.text.ilike("%")]
                res = (await db.execute(select(Memory).where(*base, or_(*conds)).order_by(Memory.importance.desc())
                                        .limit(max(k * 3, 10)))).scalars().all()
                rows = [(m, None) for m in res]
        except Exception as e:  # noqa: BLE001
            log.warning("memory.search_failed", error=str(e)[:200])
            return []
        scored = []
        for m, sim in rows:
            age_days = max(0.0, (now - (m.created_at or now)).total_seconds() / 86400)
            recency = max(0.0, 1.0 - age_days / 180)
            s = 0.7 * (sim if sim is not None else 0.5) + 0.2 * float(m.importance or 0.5) + 0.1 * recency
            scored.append((s, sim, m))
        scored.sort(key=lambda t: t[0], reverse=True)
        out = []
        for s, sim, m in scored[:k]:
            try:
                m.use_count = int(m.use_count or 0) + 1
                m.last_used_at = now
            except Exception:  # noqa: BLE001
                pass
            out.append(_row_dict(m, sim, round(s, 4)))
        return out

    async def read_bundle(self, db: Any, workspace_id: UUID, *, brand_id: UUID | None, user_id: UUID | None, query: str,
                          k: int = 8) -> MemoryBundle:
        bundle = MemoryBundle()
        if db is None:
            return bundle
        try:
            bundle.memories = await self.search(db, workspace_id, query, k=k, brand_id=brand_id,
                                                kinds=["performance", "strategy", "note", "conversation_summary", "content"])
            prefs = (await db.execute(select(Memory).where(Memory.workspace_id == workspace_id, Memory.kind == "preference",
                                                           or_(Memory.user_id == user_id, Memory.user_id.is_(None)) if user_id else Memory.user_id.is_(None))
                                      .order_by(Memory.importance.desc()).limit(5))).scalars().all()
            bundle.preferences = [_row_dict(m) for m in prefs]
        except Exception as e:  # noqa: BLE001
            log.warning("memory.bundle_failed", error=str(e)[:200])
        return bundle

    # -- write ------------------------------------------------------------------------------------------------------
    async def remember(self, db: Any, workspace_id: UUID, kind: str, text: str, *, brand_id: UUID | None = None,
                       user_id: UUID | None = None, importance: float = 0.5, source_ref: dict[str, Any] | None = None,
                       expires_at: datetime | None = None) -> dict[str, Any]:
        text = (text or "").strip()
        if not text:
            raise ValueError("empty memory text")
        vectors = await self.embed(db, workspace_id, [text[:8000]])
        vec = vectors[0] if vectors else None
        # dedupe: nearest same-kind memory with cosine > 0.92 → merge (bump importance / use_count)
        if vec is not None and db is not None:
            try:
                dist = Memory.embedding.cosine_distance(vec)
                nearest = (await db.execute(select(Memory, dist).where(Memory.workspace_id == workspace_id, Memory.kind == kind,
                                                                        Memory.embedding.is_not(None)).order_by(dist).limit(1))).first()
                if nearest is not None:
                    m, d = nearest
                    sim = 1.0 - float(d)
                    if sim > DEDUPE_THRESHOLD:
                        m.importance = max(float(m.importance or 0.5), float(importance))
                        m.use_count = int(m.use_count or 0) + 1
                        m.last_used_at = datetime.now(UTC)
                        if source_ref:
                            m.source_ref = {**(m.source_ref or {}), **source_ref}
                        await db.flush()
                        return {**_row_dict(m, sim), "deduplicated": True}
            except Exception as e:  # noqa: BLE001
                log.warning("memory.dedupe_failed", error=str(e)[:200])
        row = Memory(id=new_id(), workspace_id=workspace_id, brand_id=brand_id, user_id=user_id, kind=kind, text=text,
                     embedding=vec, embedding_model=await self._embedding_model(db, workspace_id) if vec else None,
                     importance=float(importance), source_ref=source_ref or {}, expires_at=expires_at,
                     created_at=datetime.now(UTC), use_count=0)
        if db is not None:
            db.add(row)
            try:
                await db.flush()
            except Exception as e:  # noqa: BLE001
                log.warning("memory.write_failed", error=str(e)[:200])
        return {**_row_dict(row), "deduplicated": False}

    async def summarize_conversation(self, db: Any, workspace_id: UUID, messages: list[Message], *,
                                     previous_summary: str | None = None, run: AIRun | None = None) -> str:
        """Cheap-model rolling summary; falls back to a truncated transcript when no provider is reachable."""
        transcript = "\n".join(f"{m.role}: {str(m.content)[:600]}" for m in messages[-12:])
        try:
            from app.agents.orchestrator import ledger
            from app.integrations.ai.registry import providers_for_tier
            candidates = await providers_for_tier(db, workspace_id, "cheap", "intent_router")
            provider, model = candidates[0]
            prompt = ("Summarize this conversation between a user and a social-media AI assistant in ≤ 120 words: goals, "
                      "decisions, preferences, open items. Previous summary (merge, do not repeat): "
                      f"{previous_summary or '(none)'}\n\nTranscript:\n{transcript}\n\nSummary:")
            comp = await provider.complete([Message(role="user", content=prompt)], model=model, temperature=0.1, max_tokens=300)
            await ledger.record_call(db, run=run, task=None, agent_id="memory", completion=comp, workspace_id=workspace_id)
            if comp.content.strip():
                return comp.content.strip()[:1500]
        except Exception as e:  # noqa: BLE001
            log.info("memory.summary_fallback", error=str(e)[:160])
        return ((previous_summary + "\n" if previous_summary else "") + transcript)[-1500:]

    async def write_run_memories(self, db: Any, run: AIRun, result: dict[str, Any], *, messages: list[Message] | None = None) -> None:
        """At run end: conversation summary (ai_conversations.summary + memories kind=conversation_summary) and notes."""
        if db is None:
            return
        try:
            summary_text = None
            if run.conversation_id:
                conv = await db.get(AIConversation, run.conversation_id)
                if conv is not None and messages:
                    summary_text = await self.summarize_conversation(db, run.workspace_id, messages, previous_summary=conv.summary, run=run)
                    conv.summary = summary_text
                    vectors = await self.embed(db, run.workspace_id, [summary_text])
                    if vectors:
                        conv.summary_embedding = vectors[0]
                        conv.embedding_model = await self._embedding_model(db, run.workspace_id)
            if summary_text:
                await self.remember(db, run.workspace_id, "conversation_summary", summary_text, brand_id=run.brand_id,
                                    user_id=run.user_id, importance=0.3, source_ref={"run_id": str(run.id), "conversation_id": str(run.conversation_id)},
                                    expires_at=datetime.now(UTC) + timedelta(days=SUMMARY_TTL_DAYS))
            for note in (result.get("memory_notes") or [])[:5]:
                if isinstance(note, dict) and note.get("text"):
                    await self.remember(db, run.workspace_id, note.get("kind", "note"), note["text"], brand_id=run.brand_id,
                                        user_id=run.user_id, importance=float(note.get("importance", 0.5)),
                                        source_ref={"run_id": str(run.id)})
        except Exception as e:  # noqa: BLE001
            log.warning("memory.write_run_failed", error=str(e)[:200])


def cosine_similarity(a: list[float], b: list[float]) -> float:
    return cosine(a, b)

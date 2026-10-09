"""Persistence helpers for research sources/documents/chunks (pipeline stage ⑨), shared by the pipeline, services, tools
and competitor collectors."""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import UUID

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.core.ids import new_id
from app.core.logging import get_logger
from app.models.research import ResearchChunk, ResearchDocument, ResearchSource
from app.research.ai import Embedder
from app.research.chunk import chunk_text

log = get_logger("research.store")
REUSE_WINDOW = timedelta(hours=24)


@dataclass
class SourceData:
    canonical_url: str
    domain: str
    final_url: str | None = None
    title: str | None = None
    author: str | None = None
    source_kind: str = "web"
    platform: Any = None
    published_at: datetime | None = None
    language: str | None = None
    summary: str | None = None
    keywords: list[str] = field(default_factory=list)
    topics: list[str] = field(default_factory=list)
    entities: dict[str, Any] = field(default_factory=dict)
    credibility_score: float | None = None
    credibility_components: dict[str, Any] | None = None
    citation: str | None = None
    content_hash: str | None = None
    simhash: int | None = None
    word_count: int | None = None
    trust: str = "untrusted"
    injection_flag: bool = False
    fetch_status: str = "ok"
    error: str | None = None
    competitor_id: UUID | None = None
    duplicates_of: UUID | None = None


def format_citation(title: str | None, domain: str, url: str, author: str | None, published_at: datetime | None) -> str:
    """"Author. Title. Domain, date. URL" (doc 07 §7.3)."""
    parts = []
    if author:
        parts.append(author.strip().rstrip("."))
    parts.append((title or url).strip().rstrip("."))
    tail = domain + (f", {published_at.date().isoformat()}" if published_at else "")
    parts.append(tail)
    return ". ".join(parts) + f". {url}"


async def get_source_by_url(db: AsyncSession, workspace_id: UUID, canonical_url: str) -> ResearchSource | None:
    return (await db.execute(select(ResearchSource).where(ResearchSource.workspace_id == workspace_id,
                                                          ResearchSource.canonical_url == canonical_url))).scalar_one_or_none()


async def find_by_content_hash(db: AsyncSession, workspace_id: UUID, h: str, *, exclude_url: str | None = None) -> ResearchSource | None:
    stmt = select(ResearchSource).where(ResearchSource.workspace_id == workspace_id, ResearchSource.content_hash == h,
                                        ResearchSource.duplicates_of.is_(None))
    if exclude_url:
        stmt = stmt.where(ResearchSource.canonical_url != exclude_url)
    return (await db.execute(stmt.order_by(ResearchSource.created_at).limit(1))).scalar_one_or_none()


def is_fresh(src: ResearchSource, now: datetime | None = None) -> bool:
    now = now or datetime.now(UTC)
    ra = src.retrieved_at
    if ra is None:
        return False
    if ra.tzinfo is None:
        ra = ra.replace(tzinfo=UTC)
    return src.fetch_status == "ok" and now - ra < REUSE_WINDOW


async def upsert_source(db: AsyncSession, workspace_id: UUID, data: SourceData, *,
                        existing: ResearchSource | None = None) -> tuple[ResearchSource, bool]:
    """Insert or update the workspace's row for ``canonical_url``. Returns (row, created)."""
    src = existing or await get_source_by_url(db, workspace_id, data.canonical_url)
    created = src is None
    if src is None:
        src = ResearchSource(id=new_id(), workspace_id=workspace_id, canonical_url=data.canonical_url, domain=data.domain)
        db.add(src)
    pinned = (src.entities or {}).get("pin") if not created else None
    keep_kind = not created and src.source_kind in ("user_provided", "competitor_site", "rss", "news") \
        and data.source_kind == "web"
    for attr in ("final_url", "title", "author", "source_kind", "platform", "published_at", "language", "summary",
                 "credibility_score", "credibility_components", "citation", "content_hash", "simhash", "word_count",
                 "injection_flag", "fetch_status", "error", "duplicates_of"):
        val = getattr(data, attr)
        if attr == "source_kind" and keep_kind:
            continue
        if val is None and attr in ("title", "author", "published_at", "language", "summary", "content_hash", "simhash",
                                    "word_count", "final_url", "platform", "credibility_score", "credibility_components",
                                    "citation"):
            continue  # never erase known metadata with a missing value
        setattr(src, attr, val)
    src.domain = data.domain or src.domain
    if data.keywords:
        src.keywords = list(data.keywords)
    if data.topics:
        src.topics = list(data.topics)
    if data.entities:
        ent = dict(data.entities)
        if pinned:
            ent["pin"] = pinned
        src.entities = ent
    if data.competitor_id and not src.competitor_id:
        src.competitor_id = data.competitor_id
    if not (src.trust == "trusted" and data.trust == "untrusted" and src.source_kind == "user_provided"):
        src.trust = data.trust
    src.retrieved_at = datetime.now(UTC)
    await db.flush()
    return src, created


def _object_key(workspace_id: UUID, source_id: UUID) -> str:
    return f"research/{workspace_id}/{source_id}.txt"


async def store_document(db: AsyncSession, src: ResearchSource, text: str, *, extractor: str | None,
                         structure: dict[str, Any] | None = None, storage: Any = None) -> bool:
    """Full text → object storage (documents bucket) + research_documents row. Returns False when storage is down
    (chunks still carry the text, so reads keep working)."""
    key = _object_key(src.workspace_id, src.id)
    try:
        if storage is None:
            from app.integrations.storage.s3 import storage as default_storage
            storage = default_storage
        await storage.put(settings.s3_bucket_documents, key, text.encode("utf-8"), "text/plain; charset=utf-8")
    except Exception as e:
        log.warning("research.storage_unavailable", source_id=str(src.id), error=str(e)[:200])
        return False
    src.content_object_key = key
    doc = (await db.execute(select(ResearchDocument).where(ResearchDocument.source_id == src.id))).scalar_one_or_none()
    if doc is None:
        db.add(ResearchDocument(id=new_id(), workspace_id=src.workspace_id, source_id=src.id, text_object_key=key,
                                structure=structure or {}, extractor=extractor, extracted_at=datetime.now(UTC)))
    else:
        doc.text_object_key = key
        doc.structure = structure or doc.structure or {}
        doc.extractor = extractor or doc.extractor
        doc.extracted_at = datetime.now(UTC)
    await db.flush()
    return True


async def replace_chunks(db: AsyncSession, src: ResearchSource, text: str, *, embedder: Embedder | None = None) -> int:
    chunks = chunk_text(text)
    await db.execute(delete(ResearchChunk).where(ResearchChunk.source_id == src.id))
    vectors: list[list[float]] | None = None
    if embedder is not None and chunks:
        vectors = []
        for i in range(0, len(chunks), 64):
            part = await embedder.embed([c.text for c in chunks[i:i + 64]])
            if part is None:
                vectors = None
                break
            vectors.extend(part)
    for i, c in enumerate(chunks):
        db.add(ResearchChunk(id=new_id(), workspace_id=src.workspace_id, source_id=src.id, chunk_index=c.index,
                             section=c.section[:300] if c.section else None, text=c.text, token_count=c.token_count,
                             embedding=vectors[i] if vectors else None, embedding_model=embedder.model if vectors and embedder else None))
    await db.flush()
    return len(chunks)


async def embed_existing_chunks(db: AsyncSession, source_id: UUID, embedder: Embedder) -> int:
    rows = list((await db.execute(select(ResearchChunk).where(ResearchChunk.source_id == source_id,
                                                              ResearchChunk.embedding.is_(None))
                                  .order_by(ResearchChunk.chunk_index))).scalars())
    done = 0
    for i in range(0, len(rows), 64):
        batch = rows[i:i + 64]
        vecs = await embedder.embed([r.text for r in batch])
        if vecs is None:
            break
        for r, v in zip(batch, vecs, strict=False):
            r.embedding = v
            r.embedding_model = embedder.model
            done += 1
    await db.flush()
    return done


async def load_source_text(db: AsyncSession, src: ResearchSource, *, storage: Any = None) -> str | None:
    """Full text from object storage, falling back to the concatenated chunks."""
    if src.content_object_key:
        try:
            if storage is None:
                from app.integrations.storage.s3 import storage as default_storage
                storage = default_storage
            data = await storage.get(settings.s3_bucket_documents, src.content_object_key)
            return data.decode("utf-8", errors="replace")
        except Exception as e:
            log.info("research.storage_read_failed", source_id=str(src.id), error=str(e)[:200])
    rows = (await db.execute(select(ResearchChunk.text).where(ResearchChunk.source_id == src.id)
                             .order_by(ResearchChunk.chunk_index))).scalars().all()
    if rows:
        return "\n\n".join(rows)
    return None

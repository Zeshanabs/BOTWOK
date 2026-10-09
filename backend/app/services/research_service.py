"""ResearchService — research runs, sources, feeds, keywords, similarity search (doc 07)."""
from __future__ import annotations

import asyncio
from collections import Counter
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import UUID

from sqlalchemy import and_, any_, func, literal, or_, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import ProblemError, not_found, validation
from app.core.events import emit
from app.core.ids import new_id
from app.core.logging import get_logger
from app.core.pagination import decode_cursor, encode_cursor
from app.core.resilience import ResilienceError
from app.models.brand import Brand
from app.models.competitor import Competitor
from app.models.research import (
    Keyword,
    ResearchChunk,
    ResearchRun,
    ResearchRunSource,
    ResearchSource,
    RssFeed,
)
from app.research.ai import get_embedder
from app.research.store import SourceData, format_citation, get_source_by_url, load_source_text, upsert_source
from app.research.text import term_set
from app.research.urls import domain_of, safe_canonicalize
from app.schemas.research import FeedCreate, KeywordCreate, ResearchRunCreate, SourcePin

log = get_logger("research.service")
_inline_tasks: set[asyncio.Task[Any]] = set()


def _actor(member: Any) -> dict[str, Any]:
    user = getattr(member, "user", None)
    if user is not None:
        return {"type": "user", "id": str(user.id)}
    if isinstance(member, dict):
        return member
    return {"type": "system"}


async def _audit(db: AsyncSession, member: Any, action: str, target_type: str, target_id: Any,
                 before: Any = None, after: Any = None) -> None:
    try:
        from app.services.audit_service import audit
    except ImportError:
        return
    try:
        await audit(db, member, action, target_type, target_id, before=before, after=after)
    except Exception as e:  # auditing must never break the mutation
        log.warning("audit.failed", action=action, error=str(e)[:200])


async def _run_inline(run_id: UUID, workspace_id: UUID) -> None:
    """Local-dev fallback when the job queue is unreachable: run the pipeline in-process."""
    from app.core.db import SessionLocal, set_workspace
    from app.research.pipeline import run_pipeline
    try:
        async with SessionLocal() as db:
            await set_workspace(db, workspace_id)
            run = await db.get(ResearchRun, run_id)
            if run is not None:
                await run_pipeline(db, run)
    except Exception as e:
        log.error("research.inline_failed", run_id=str(run_id), error=str(e)[:300])


class ResearchService:
    """All methods are classmethods so both ``ResearchService.x(db, ...)`` and ``ResearchService().x(db, ...)`` work."""

    # ------------------------------------------------------------------------------------------------ runs
    @classmethod
    async def start_run(cls, db: AsyncSession, member: Any, params: ResearchRunCreate | dict[str, Any], *,
                        enqueue: bool = True) -> ResearchRun:
        p = params if isinstance(params, ResearchRunCreate) else ResearchRunCreate.model_validate(params)
        ws = member.workspace_id
        if p.brand_id is not None:
            ok = (await db.execute(select(Brand.id).where(Brand.id == p.brand_id, Brand.workspace_id == ws))).scalar_one_or_none()
            if ok is None:
                raise validation("brand_id does not belong to this workspace")
        comp_ids = list(p.competitor_ids) + ([p.competitor_id] if p.competitor_id else [])
        if comp_ids:
            found = set((await db.execute(select(Competitor.id).where(Competitor.workspace_id == ws,
                                                                      Competitor.id.in_(comp_ids)))).scalars())
            if found != set(comp_ids):
                raise validation("competitor id(s) not found in this workspace")
        user = getattr(member, "user", None)
        run = ResearchRun(id=new_id(), workspace_id=ws, brand_id=p.brand_id, competitor_id=p.competitor_id, query=p.query,
                          scope=list(p.scope), depth=p.depth, status="queued", ai_run_id=p.ai_run_id,
                          created_by=getattr(user, "id", None) or getattr(member, "user_id", None),
                          params={"recency_days": p.recency_days, "domains_allow": p.domains_allow,
                                  "domains_deny": p.domains_deny, "competitor_ids": [str(c) for c in p.competitor_ids]})
        db.add(run)
        await _audit(db, member, "research.run_started", "research_run", run.id, after={"query": p.query, "scope": p.scope,
                                                                                         "depth": p.depth})
        await db.commit()  # the worker must be able to see the row
        from app.core.db import set_workspace
        await set_workspace(db, ws)
        if enqueue:
            await cls.enqueue_run(db, run)
        return run

    @classmethod
    async def enqueue_run(cls, db: AsyncSession, run: ResearchRun) -> None:
        try:
            from app.research.queue import defer
            job_id = await defer("jobs.research.run", queue="research", lock=f"research:{run.id}", run_id=str(run.id),
                                 workspace_id=str(run.workspace_id))
            run.params = {**(run.params or {}), "job_id": job_id}
        except Exception as e:
            log.warning("research.enqueue_failed_inline_fallback", run_id=str(run.id), error=str(e)[:300])
            run.params = {**(run.params or {}), "job_id": None, "executed": "inline"}
            task = asyncio.get_running_loop().create_task(_run_inline(run.id, run.workspace_id))
            _inline_tasks.add(task)
            task.add_done_callback(_inline_tasks.discard)
        await db.flush()

    @classmethod
    async def get_run(cls, db: AsyncSession, workspace_id: UUID, run_id: UUID) -> ResearchRun:
        run = (await db.execute(select(ResearchRun).where(ResearchRun.id == run_id, ResearchRun.workspace_id == workspace_id))
               ).scalar_one_or_none()
        if run is None:
            raise not_found("Research run")
        return run

    @classmethod
    async def ranked_sources(cls, db: AsyncSession, run: ResearchRun, *, limit: int = 100) -> list[dict[str, Any]]:
        rows = (await db.execute(select(ResearchRunSource, ResearchSource).join(
            ResearchSource, ResearchSource.id == ResearchRunSource.source_id).where(
            ResearchRunSource.run_id == run.id).order_by(ResearchRunSource.rank).limit(limit))).all()
        return [{"id": s.id, "rank": link.rank, "title": s.title, "url": s.canonical_url, "domain": s.domain,
                 "published_at": s.published_at, "relevance": float(link.relevance_score),
                 "credibility": float(s.credibility_score) if s.credibility_score is not None else None,
                 "summary": s.summary, "injection_flag": s.injection_flag, "source_kind": s.source_kind,
                 "query_variant": link.query_variant} for link, s in rows]

    @classmethod
    async def list_runs(cls, db: AsyncSession, workspace_id: UUID, *, limit: int = 50, cursor: str | None = None,
                        status: str | None = None, brand_id: UUID | None = None) -> tuple[list[ResearchRun], str | None]:
        stmt = select(ResearchRun).where(ResearchRun.workspace_id == workspace_id)
        if status:
            stmt = stmt.where(ResearchRun.status == status)
        if brand_id:
            stmt = stmt.where(ResearchRun.brand_id == brand_id)
        cur = decode_cursor(cursor)
        if cur:
            ts = datetime.fromisoformat(cur["t"])
            stmt = stmt.where(or_(ResearchRun.created_at < ts, and_(ResearchRun.created_at == ts, ResearchRun.id < UUID(cur["id"]))))
        rows = list((await db.execute(stmt.order_by(ResearchRun.created_at.desc(), ResearchRun.id.desc()).limit(limit + 1))).scalars())
        nxt = None
        if len(rows) > limit:
            rows = rows[:limit]
            nxt = encode_cursor({"t": rows[-1].created_at.isoformat(), "id": str(rows[-1].id)})
        return rows, nxt

    @classmethod
    async def cancel_run(cls, db: AsyncSession, member: Any, run_id: UUID) -> ResearchRun:
        run = await cls.get_run(db, member.workspace_id, run_id)
        if run.status in ("completed", "failed", "cancelled"):
            raise ProblemError(409, "conflict", "Conflict", f"run is already {run.status}")
        run.status = "cancelled"
        run.completed_at = datetime.now(UTC)
        await _audit(db, member, "research.run_cancelled", "research_run", run.id)
        await db.flush()
        return run

    # ------------------------------------------------------------------------------------------------ sources
    @classmethod
    async def list_sources(cls, db: AsyncSession, workspace_id: UUID, *, q: str | None = None, domain: str | None = None,
                           competitor_id: UUID | None = None, min_credibility: float | None = None,
                           since: datetime | None = None, kind: str | None = None, include_duplicates: bool = False,
                           flagged: bool | None = None, limit: int = 50, cursor: str | None = None
                           ) -> tuple[list[ResearchSource], str | None]:
        stmt = select(ResearchSource).where(ResearchSource.workspace_id == workspace_id)
        if q:
            like = f"%{q.strip()[:200]}%"
            stmt = stmt.where(or_(ResearchSource.title.ilike(like), ResearchSource.summary.ilike(like),
                                  ResearchSource.canonical_url.ilike(like)))
        if domain:
            d = domain_of(domain)
            stmt = stmt.where(or_(ResearchSource.domain == d, ResearchSource.domain.like(f"%.{d}")))
        if competitor_id:
            stmt = stmt.where(ResearchSource.competitor_id == competitor_id)
        if min_credibility is not None:
            stmt = stmt.where(ResearchSource.credibility_score >= min_credibility)
        if since:
            stmt = stmt.where(ResearchSource.retrieved_at >= since)
        if kind:
            stmt = stmt.where(ResearchSource.source_kind == kind)
        if flagged is not None:
            stmt = stmt.where(ResearchSource.injection_flag.is_(flagged))
        if not include_duplicates:
            stmt = stmt.where(ResearchSource.duplicates_of.is_(None))
        cur = decode_cursor(cursor)
        if cur:
            ts = datetime.fromisoformat(cur["t"])
            stmt = stmt.where(or_(ResearchSource.retrieved_at < ts,
                                  and_(ResearchSource.retrieved_at == ts, ResearchSource.id < UUID(cur["id"]))))
        rows = list((await db.execute(stmt.order_by(ResearchSource.retrieved_at.desc(), ResearchSource.id.desc())
                                      .limit(limit + 1))).scalars())
        nxt = None
        if len(rows) > limit:
            rows = rows[:limit]
            nxt = encode_cursor({"t": rows[-1].retrieved_at.isoformat(), "id": str(rows[-1].id)})
        return rows, nxt

    @classmethod
    async def get_source(cls, db: AsyncSession, workspace_id: UUID, source_id: UUID, *, include_text: bool = True,
                         max_chars: int = 50_000) -> tuple[ResearchSource, str | None, bool]:
        src = (await db.execute(select(ResearchSource).where(ResearchSource.id == source_id,
                                                             ResearchSource.workspace_id == workspace_id))).scalar_one_or_none()
        if src is None:
            raise not_found("Source")
        if not include_text:
            return src, None, False
        txt = await load_source_text(db, src)
        truncated = bool(txt and len(txt) > max_chars)
        return src, (txt[:max_chars] if txt else None), truncated

    @classmethod
    async def pin_source(cls, db: AsyncSession, member: Any, source_id: UUID, data: SourcePin) -> ResearchSource:
        src, _, _ = await cls.get_source(db, member.workspace_id, source_id, include_text=False)
        before = {"pin": (src.entities or {}).get("pin"), "trust": src.trust, "credibility": float(src.credibility_score or 0)}
        ents = dict(src.entities or {})
        if data.pinned:
            ents["pin"] = {"pinned": True, "notes": data.notes, "brand_id": str(data.brand_id) if data.brand_id else None,
                           "by": str(getattr(getattr(member, "user", None), "id", "") or "") or None,
                           "at": datetime.now(UTC).isoformat()}
        else:
            ents.pop("pin", None)
        src.entities = ents
        if data.trust is not None:
            # Fetched content stays untrusted no matter what (doc 19 §19.6); only user-provided notes can be trusted.
            if data.trust == "trusted" and src.source_kind != "user_provided":
                raise validation("only user-provided sources can be marked trusted")
            src.trust = data.trust
        if data.credibility_override is not None:
            comps = dict(src.credibility_components or {})
            comps["user_override"] = {"value": data.credibility_override, "previous": float(src.credibility_score or 0)}
            src.credibility_components = comps
            src.credibility_score = data.credibility_override
        await emit(db, "SOURCE_SAVED", {"source_id": str(src.id), "injection_flag": src.injection_flag, "pinned": data.pinned},
                   workspace_id=member.workspace_id, actor=_actor(member))
        await _audit(db, member, "research.source_pinned", "research_source", src.id, before=before,
                     after={"pin": ents.get("pin"), "trust": src.trust, "credibility": float(src.credibility_score or 0)})
        await db.flush()
        return src

    @classmethod
    async def save_source(cls, db: AsyncSession, workspace_id: UUID, *, url: str, title: str | None = None,
                          summary: str | None = None, relevance: float | None = None, credibility: float | None = None,
                          notes: str | None = None, actor: dict[str, Any] | None = None,
                          competitor_id: UUID | None = None) -> tuple[ResearchSource, bool]:
        """Idempotent by canonical URL (used by the ``research.save_source`` tool). Agent-supplied text stays untrusted;
        an agent's credibility estimate is recorded but never overrides the deterministic score of a fetched source."""
        canon = safe_canonicalize(url)
        if not canon:
            raise validation("invalid url")
        from app.research.injection import classify
        existing = await get_source_by_url(db, workspace_id, canon)
        prev_retrieved = existing.retrieved_at if existing else None
        ents = dict(existing.entities or {}) if existing else {}
        agent_notes = list(ents.get("agent_notes") or [])
        if notes or relevance is not None or credibility is not None:
            entry = {"notes": (notes or "")[:2000], "relevance": relevance, "credibility": credibility,
                     "actor": actor or {"type": "system"}, "at": datetime.now(UTC).isoformat()}
            if not any(e.get("notes") == entry["notes"] and e.get("actor") == entry["actor"] for e in agent_notes):
                agent_notes.append(entry)
        ents["agent_notes"] = agent_notes[-20:]
        clean_summary = classify(summary or "").sanitized_text[:3000] if summary else None
        report = classify(f"{title or ''}\n{summary or ''}")
        data = SourceData(canonical_url=canon, domain=domain_of(canon), final_url=url, title=(title or None),
                          source_kind=existing.source_kind if existing else "web",
                          summary=(existing.summary if existing and existing.summary else clean_summary),
                          entities=ents, injection_flag=bool(existing.injection_flag if existing else False) or report.flagged,
                          fetch_status=existing.fetch_status if existing else "not_fetched",
                          credibility_score=(float(existing.credibility_score) if existing and existing.credibility_score is not None
                                             else (round(float(credibility), 3) if credibility is not None else None)),
                          citation=(existing.citation if existing else format_citation(title, domain_of(canon), canon, None, None)),
                          competitor_id=competitor_id)
        src, created = await upsert_source(db, workspace_id, data, existing=existing)
        if prev_retrieved is not None:  # saving a note must not make a stale copy look freshly fetched
            src.retrieved_at = prev_retrieved
        await emit(db, "SOURCE_SAVED", {"source_id": str(src.id), "injection_flag": src.injection_flag, "created": created},
                   workspace_id=workspace_id, actor=actor)
        await db.flush()
        return src, created

    # ------------------------------------------------------------------------------------------------ feeds
    @classmethod
    async def list_feeds(cls, db: AsyncSession, workspace_id: UUID, *, brand_id: UUID | None = None,
                         competitor_id: UUID | None = None) -> list[RssFeed]:
        stmt = select(RssFeed).where(RssFeed.workspace_id == workspace_id)
        if brand_id:
            stmt = stmt.where(RssFeed.brand_id == brand_id)
        if competitor_id:
            stmt = stmt.where(RssFeed.competitor_id == competitor_id)
        return list((await db.execute(stmt.order_by(RssFeed.created_at.desc()))).scalars())

    @classmethod
    async def add_feed(cls, db: AsyncSession, member: Any, data: FeedCreate, *, poll: bool | None = None) -> RssFeed:
        ws = member.workspace_id if hasattr(member, "workspace_id") else member["workspace_id"]
        canon = safe_canonicalize(data.url)
        if not canon:
            raise validation("invalid feed url")
        from app.core.safe_fetch import get_fetcher
        try:
            await get_fetcher().validate_url(canon)
        except ResilienceError as e:
            raise validation(f"feed url rejected: {e.message}") from e
        existing = (await db.execute(select(RssFeed).where(RssFeed.workspace_id == ws, RssFeed.url == canon))).scalar_one_or_none()
        if existing is not None:
            return existing
        feed = RssFeed(id=new_id(), workspace_id=ws, url=canon, title=data.title, brand_id=data.brand_id,
                       competitor_id=data.competitor_id, status="active")
        db.add(feed)
        await db.flush()
        await _audit(db, member, "research.feed_added", "rss_feed", feed.id, after={"url": canon})
        if data.poll_now if poll is None else poll:
            from app.research.feeds import poll_feed
            await poll_feed(db, feed)
            await db.flush()
        return feed

    @classmethod
    async def delete_feed(cls, db: AsyncSession, member: Any, feed_id: UUID) -> None:
        feed = (await db.execute(select(RssFeed).where(RssFeed.id == feed_id, RssFeed.workspace_id == member.workspace_id))
                ).scalar_one_or_none()
        if feed is None:
            raise not_found("Feed")
        await _audit(db, member, "research.feed_deleted", "rss_feed", feed.id, before={"url": feed.url})
        await db.delete(feed)
        await db.flush()

    @classmethod
    async def poll_feed(cls, db: AsyncSession, workspace_id: UUID, feed_id: UUID) -> dict[str, Any]:
        from app.research.feeds import poll_feed
        feed = (await db.execute(select(RssFeed).where(RssFeed.id == feed_id, RssFeed.workspace_id == workspace_id))
                ).scalar_one_or_none()
        if feed is None:
            raise not_found("Feed")
        res = await poll_feed(db, feed)
        await db.flush()
        return res

    # ------------------------------------------------------------------------------------------------ keywords
    @classmethod
    async def list_keywords(cls, db: AsyncSession, workspace_id: UUID, *, brand_id: UUID | None = None, q: str | None = None,
                            source: str | None = None, limit: int = 200) -> list[Keyword]:
        stmt = select(Keyword).where(Keyword.workspace_id == workspace_id)
        if brand_id:
            stmt = stmt.where(or_(Keyword.brand_id == brand_id, Keyword.brand_id.is_(None)))
        if q:
            stmt = stmt.where(Keyword.term.ilike(f"%{q[:100]}%"))
        if source:
            stmt = stmt.where(Keyword.source == source)
        return list((await db.execute(stmt.order_by(Keyword.last_seen.desc()).limit(limit))).scalars())

    @classmethod
    async def upsert_keyword(cls, db: AsyncSession, member: Any, data: KeywordCreate, *, source: str = "user") -> Keyword:
        ws = member.workspace_id
        stmt = select(Keyword).where(Keyword.workspace_id == ws, Keyword.term == data.term)
        stmt = stmt.where(Keyword.brand_id == data.brand_id) if data.brand_id else stmt.where(Keyword.brand_id.is_(None))
        kw = (await db.execute(stmt.limit(1))).scalar_one_or_none()
        if kw is None:
            kw = Keyword(id=new_id(), workspace_id=ws, brand_id=data.brand_id, term=data.term, source=source,
                         related=data.related, volume_hint=data.volume_hint, frequency={})
            db.add(kw)
        else:
            kw.related = sorted(set(kw.related or []) | set(data.related))
            if data.volume_hint is not None:
                kw.volume_hint = data.volume_hint
            if source == "user":
                kw.source = "user"
            kw.last_seen = datetime.now(UTC)
        await db.flush()
        await _audit(db, member, "research.keyword_saved", "keyword", kw.id, after={"term": data.term})
        return kw

    @classmethod
    async def lookup_keyword(cls, db: AsyncSession, workspace_id: UUID, term: str, *, brand_id: UUID | None = None,
                             days: int = 30) -> dict[str, Any]:
        """Keyword row(s) + relative frequency in collected sources (no search-volume provider configured)."""
        term = " ".join(term.split()).lower()[:120]
        if not term:
            raise validation("empty term")
        rows = list((await db.execute(select(Keyword).where(Keyword.workspace_id == workspace_id,
                                                            Keyword.term == term))).scalars())
        since = datetime.now(UTC) - timedelta(days=days)
        like = f"%{term}%"
        match = or_(literal(term) == any_(ResearchSource.keywords), ResearchSource.title.ilike(like), ResearchSource.summary.ilike(like))
        day_col = func.date_trunc("day", func.coalesce(ResearchSource.published_at, ResearchSource.retrieved_at))
        series = (await db.execute(select(day_col, func.count()).where(
            ResearchSource.workspace_id == workspace_id, match, ResearchSource.retrieved_at >= since)
            .group_by(day_col).order_by(day_col))).all()
        total_sources = (await db.execute(select(func.count()).select_from(ResearchSource).where(
            ResearchSource.workspace_id == workspace_id, ResearchSource.retrieved_at >= since))).scalar_one()
        co = (await db.execute(select(ResearchSource.keywords).where(ResearchSource.workspace_id == workspace_id, match,
                                                                     ResearchSource.retrieved_at >= since).limit(300))).scalars()
        related: Counter[str] = Counter()
        for kws in co:
            for k in kws or []:
                if k != term and term not in k:
                    related[k] += 1
        mentions = sum(int(c) for _, c in series)
        brand_rows = [r for r in rows if brand_id is None or r.brand_id in (brand_id, None)]
        return {
            "term": term,
            "keywords": [{"id": str(r.id), "brand_id": str(r.brand_id) if r.brand_id else None, "source": r.source,
                          "volume_hint": r.volume_hint, "related": r.related, "frequency": r.frequency} for r in brand_rows],
            "volume": {"kind": "relative_frequency_in_collected_sources",
                       "label": "Relative frequency in collected sources (no search-volume provider configured)",
                       "mentions": mentions, "share": round(mentions / total_sources, 4) if total_sources else 0.0,
                       "window_days": days, "series": [{"date": d.date().isoformat(), "count": int(c)} for d, c in series]},
            "related": [k for k, _ in related.most_common(10)],
        }

    # ------------------------------------------------------------------------------------------------ similarity
    @classmethod
    async def find_similar(cls, db: AsyncSession, workspace_id: UUID, query_text: str, k: int = 5) -> list[dict[str, Any]]:
        """Nearest sources: pgvector cosine over research_chunks when embeddings exist, else trigram similarity."""
        k = max(1, min(25, k))
        qt = " ".join((query_text or "").split())[:4000]
        if not qt:
            return []
        embedder = await get_embedder(db, workspace_id)
        if embedder is not None:
            vecs = await embedder.embed([qt])
            if vecs:
                dist = ResearchChunk.embedding.cosine_distance(vecs[0])
                rows = (await db.execute(select(ResearchChunk.source_id, ResearchChunk.text, ResearchChunk.section, dist.label("d"))
                                         .where(ResearchChunk.workspace_id == workspace_id, ResearchChunk.embedding.is_not(None))
                                         .order_by(dist).limit(k * 4))).all()
                best: dict[UUID, tuple[float, str, str | None]] = {}
                for sid, ctext, section, d in rows:
                    if sid not in best or d < best[sid][0]:
                        best[sid] = (float(d), ctext, section)
                if best:
                    srcs = {s.id: s for s in (await db.execute(select(ResearchSource).where(
                        ResearchSource.id.in_(list(best))))).scalars()}
                    out = []
                    for sid, (d, ctext, section) in sorted(best.items(), key=lambda kv: kv[1][0])[:k]:
                        s = srcs.get(sid)
                        if s is None:
                            continue
                        out.append({"source_id": str(sid), "title": s.title, "url": s.canonical_url, "domain": s.domain,
                                    "score": round(1 - d, 4), "method": "embedding", "section": section,
                                    "snippet": ctext[:400], "injection_flag": s.injection_flag})
                    return out
        probe = qt[:300]
        sim = func.greatest(func.similarity(func.coalesce(ResearchSource.title, ""), probe),
                            func.word_similarity(probe, func.coalesce(ResearchSource.summary, "")))
        rows = (await db.execute(select(ResearchSource, sim.label("s")).where(
            ResearchSource.workspace_id == workspace_id, ResearchSource.duplicates_of.is_(None)).order_by(text("s DESC"))
            .limit(k * 3))).all()
        terms = term_set(qt)
        out = []
        for s, score in rows:
            score = float(score or 0)
            if score < 0.05 and not (terms & term_set(f"{s.title or ''} {s.summary or ''}")):
                continue
            out.append({"source_id": str(s.id), "title": s.title, "url": s.canonical_url, "domain": s.domain,
                        "score": round(score, 4), "method": "trigram", "section": None, "snippet": (s.summary or "")[:400],
                        "injection_flag": s.injection_flag})
            if len(out) >= k:
                break
        return out

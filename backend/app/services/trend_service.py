"""TrendService — signal ingestion, deterministic burst scoring, trend lifecycle (docs 06 §4 ``trend``, 07 §7.1).

Signals come from research_sources keywords (kind ``keyword`` / ``news_mention``) and competitor_posts hashtags/terms
(``hashtag`` / ``competitor_post``) over a 14-day window. Score = max(z, 0) × credibility × brand relevance, where z is the
z-score of the last 3 days' mention rate against the preceding baseline. The ``trend`` agent only names/explains.
"""
from __future__ import annotations

import statistics
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import UUID

from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import not_found, validation
from app.core.events import emit
from app.core.ids import new_id
from app.core.logging import get_logger
from app.models.brand import Brand, BrandSettings, ContentPillar
from app.models.competitor import Competitor, CompetitorPost, CompetitorProfile
from app.models.enums import Platform
from app.models.research import ResearchSource, Trend, TrendSignal
from app.research.text import STOPWORDS, term_set, top_terms

log = get_logger("trends.service")
WINDOW_DAYS = 14
RECENT_DAYS = 3
SCORE_THRESHOLD = 0.5
MIN_MENTIONS = 3
MAX_TRENDS_PER_SCAN = 30


@dataclass
class Signal:
    kind: str
    term: str
    observed_at: datetime
    value: float = 1.0
    platform: Platform | None = None
    source_id: UUID | None = None
    credibility: float = 0.5
    meta: dict[str, Any] = field(default_factory=dict)

    @property
    def key(self) -> tuple[str, str, str]:
        ref = str(self.source_id) if self.source_id else str(self.meta.get("post_id", ""))
        return self.kind, self.term, ref


@dataclass
class TermScore:
    term: str
    total: float
    recent_rate: float
    baseline_rate: float
    z: float
    velocity: float
    credibility: float
    relevance: float
    score: float
    series: list[float]
    kinds: list[str]
    platforms: list[str]
    source_ids: list[UUID]
    first_seen: datetime
    last_seen: datetime


def _aware(dt: datetime) -> datetime:
    return dt if dt.tzinfo else dt.replace(tzinfo=UTC)


def _norm_term(t: str) -> str:
    return " ".join(t.lower().lstrip("#").split())[:80]


def burst_stats(series: list[float], *, recent_days: int = RECENT_DAYS) -> tuple[float, float, float, float]:
    """(recent_rate, baseline_rate, z, velocity) for a daily series ordered oldest → newest."""
    if not series:
        return 0.0, 0.0, 0.0, 0.0
    recent = series[-recent_days:]
    base = series[:-recent_days] or [0.0]
    r = sum(recent) / len(recent)
    b = sum(base) / len(base)
    sd = statistics.pstdev(base) if len(base) > 1 else 0.0
    z = (r - b) / (sd + 0.5)
    return round(r, 3), round(b, 3), round(z, 3), round(r - b, 3)


def brand_relevance(term: str, brand_terms: set[str]) -> float:
    """1.0 when the term shares a word with brand pillars/topics/keywords, 0.7 on partial overlap, 0.5 when the brand has
    no topical profile yet, 0.25 otherwise (still detectable, ranked lower)."""
    if not brand_terms:
        return 0.5
    words = term_set(term) or {term}
    if words & brand_terms:
        return 1.0
    if any(w in b or b in w for w in words for b in brand_terms if len(w) > 3 and len(b) > 3):
        return 0.7
    return 0.25


def score_terms(signals: list[Signal], *, now: datetime, brand_terms: set[str], window_days: int = WINDOW_DAYS
                ) -> list[TermScore]:
    by_term: dict[str, list[Signal]] = defaultdict(list)
    for s in signals:
        by_term[s.term].append(s)
    start = (now - timedelta(days=window_days)).date()
    out: list[TermScore] = []
    for term, sigs in by_term.items():
        series = [0.0] * window_days
        for s in sigs:
            idx = (_aware(s.observed_at).date() - start).days - 1
            if 0 <= idx < window_days:
                series[idx] += s.value
            elif idx == window_days:
                series[-1] += s.value
        total = sum(series)
        if total < MIN_MENTIONS:
            continue
        r, b, z, vel = burst_stats(series)
        cred = sum(s.credibility for s in sigs) / len(sigs)
        rel = brand_relevance(term, brand_terms)
        score = round(max(z, 0.0) * cred * rel, 3)
        src_ids = [s.source_id for s in sorted(sigs, key=lambda s: -s.credibility) if s.source_id]
        out.append(TermScore(term=term, total=total, recent_rate=r, baseline_rate=b, z=z, velocity=vel, credibility=round(cred, 3),
                             relevance=rel, score=min(score, 999.0), series=series, kinds=sorted({s.kind for s in sigs}),
                             platforms=sorted({s.platform.value for s in sigs if s.platform is not None}),
                             source_ids=list(dict.fromkeys(src_ids))[:10],
                             first_seen=min(_aware(s.observed_at) for s in sigs), last_seen=max(_aware(s.observed_at) for s in sigs)))
    out.sort(key=lambda t: (-t.score, -t.total))
    return out


class TrendService:
    @classmethod
    async def brand_terms(cls, db: AsyncSession, workspace_id: UUID, brand_id: UUID) -> set[str]:
        terms: set[str] = set()
        for name, desc in (await db.execute(select(ContentPillar.name, ContentPillar.description).where(
                ContentPillar.workspace_id == workspace_id, ContentPillar.brand_id == brand_id))).all():
            terms |= term_set(f"{name} {desc or ''}")
        topics = (await db.execute(select(BrandSettings.topics).where(BrandSettings.brand_id == brand_id))).scalar_one_or_none()
        if isinstance(topics, dict):
            for key in ("preferred_topics", "keywords"):
                v = topics.get(key)
                if isinstance(v, list):
                    terms |= term_set(" ".join(map(str, v)))
            tags = topics.get("hashtags")
            if isinstance(tags, dict):
                terms |= {_norm_term(t) for t in tags.get("core") or [] if isinstance(t, str)}
        brand = await db.get(Brand, brand_id)
        if brand is not None and brand.industry:
            terms |= term_set(brand.industry)
        return terms

    @classmethod
    async def collect_signals(cls, db: AsyncSession, workspace_id: UUID, brand_id: UUID, *, window_days: int = WINDOW_DAYS,
                              now: datetime | None = None) -> list[Signal]:
        """In-memory signals from stored sources and competitor posts (no writes)."""
        now = now or datetime.now(UTC)
        since = now - timedelta(days=window_days)
        observed = func.coalesce(ResearchSource.published_at, ResearchSource.retrieved_at)
        rows = (await db.execute(select(ResearchSource.id, ResearchSource.keywords, ResearchSource.source_kind,
                                        ResearchSource.credibility_score, observed, ResearchSource.injection_flag)
                                 .where(ResearchSource.workspace_id == workspace_id, observed >= since,
                                        ResearchSource.duplicates_of.is_(None)).limit(5000))).all()
        signals: list[Signal] = []
        for sid, kws, kind, cred, at, flagged in rows:
            c = float(cred) if cred is not None else 0.5
            if flagged:
                c *= 0.5
            for kw in (kws or [])[:6]:
                t = _norm_term(kw)
                if not t or t in STOPWORDS or len(t) < 3:
                    continue
                signals.append(Signal(kind="news_mention" if kind == "news" else "keyword", term=t, observed_at=at,
                                      source_id=sid, credibility=c))
        comp_ids = select(Competitor.id).where(Competitor.workspace_id == workspace_id, Competitor.brand_id == brand_id)
        posts = (await db.execute(select(CompetitorPost.id, CompetitorPost.platform, CompetitorPost.hashtags,
                                         CompetitorPost.text, CompetitorPost.posted_at, CompetitorProfile.competitor_id)
                                  .join(CompetitorProfile, CompetitorProfile.id == CompetitorPost.profile_id)
                                  .where(CompetitorPost.workspace_id == workspace_id,
                                         CompetitorProfile.competitor_id.in_(comp_ids),
                                         CompetitorPost.posted_at >= since).limit(5000))).all()
        for pid, platform, tags, text, at, cid in posts:
            meta = {"post_id": str(pid), "competitor_id": str(cid)}
            for tag in (tags or [])[:10]:
                t = _norm_term(tag)
                if t:
                    signals.append(Signal(kind="hashtag", term=t, observed_at=at, platform=platform, credibility=0.6,
                                          meta=meta))
            for t in top_terms(text or "", 3, with_bigrams=False):
                signals.append(Signal(kind="competitor_post", term=_norm_term(t), observed_at=at, platform=platform,
                                      credibility=0.55, meta=meta))
        return signals

    @classmethod
    async def ingest_signals(cls, db: AsyncSession, workspace_id: UUID, brand_id: UUID, *, window_days: int = WINDOW_DAYS,
                             now: datetime | None = None) -> tuple[list[Signal], int]:
        """Persist new trend_signals (idempotent per kind/term/source-or-post). Returns (all window signals, inserted)."""
        now = now or datetime.now(UTC)
        signals = await cls.collect_signals(db, workspace_id, brand_id, window_days=window_days, now=now)
        since = now - timedelta(days=window_days)
        existing = set()
        for kind, term, sid, meta in (await db.execute(select(TrendSignal.kind, TrendSignal.term, TrendSignal.source_id,
                                                              TrendSignal.meta).where(
                TrendSignal.workspace_id == workspace_id, TrendSignal.observed_at >= since - timedelta(days=1)))).all():
            existing.add((kind, term, str(sid) if sid else str((meta or {}).get("post_id", ""))))
        inserted = 0
        for s in signals:
            if s.key in existing:
                continue
            existing.add(s.key)
            db.add(TrendSignal(id=new_id(), workspace_id=workspace_id, kind=s.kind, term=s.term, platform=s.platform,
                               observed_at=s.observed_at, value=s.value, source_id=s.source_id,
                               meta={**s.meta, "credibility": round(s.credibility, 3), "brand_id": str(brand_id)}))
            inserted += 1
        await db.flush()
        return signals, inserted

    @classmethod
    async def scan(cls, db: AsyncSession, workspace_id: UUID, brand_id: UUID, *, window_days: int = WINDOW_DAYS,
                   actor: dict[str, Any] | None = None, now: datetime | None = None) -> dict[str, Any]:
        now = now or datetime.now(UTC)
        brand = (await db.execute(select(Brand.id).where(Brand.id == brand_id, Brand.workspace_id == workspace_id)))\
            .scalar_one_or_none()
        if brand is None:
            raise not_found("Brand")
        signals, inserted = await cls.ingest_signals(db, workspace_id, brand_id, window_days=window_days, now=now)
        bterms = await cls.brand_terms(db, workspace_id, brand_id)
        scored = score_terms(signals, now=now, brand_terms=bterms, window_days=window_days)
        cooc = cls._cooccurrence(signals)
        existing = {t.label.lower(): t for t in (await db.execute(select(Trend).where(
            Trend.workspace_id == workspace_id, Trend.brand_id == brand_id))).scalars()}
        detected: list[Trend] = []
        updated: list[Trend] = []
        touched: set[str] = set()
        for ts in scored[:MAX_TRENDS_PER_SCAN]:
            trend = existing.get(ts.term)
            hot = ts.score >= SCORE_THRESHOLD and ts.recent_rate * RECENT_DAYS >= 2
            if trend is None and not hot:
                continue
            touched.add(ts.term)
            summary = cls._summary(ts)
            kws = [ts.term] + [t for t, _ in cooc.get(ts.term, Counter()).most_common(6) if t != ts.term]
            if trend is None:
                trend = Trend(id=new_id(), workspace_id=workspace_id, brand_id=brand_id, label=ts.term, summary=summary,
                              score=ts.score, velocity=ts.velocity, status="emerging", keywords=kws[:8],
                              platforms=[Platform(p) for p in ts.platforms], first_seen=ts.first_seen, last_seen=ts.last_seen,
                              example_source_ids=ts.source_ids[:5])
                db.add(trend)
                detected.append(trend)
                continue
            if trend.status == "dismissed":
                continue
            prev_status, prev_score = trend.status, float(trend.score or 0)
            if hot:
                new_status = "emerging" if (now - _aware(trend.first_seen)) <= timedelta(days=RECENT_DAYS) else "active"
            else:
                new_status = "fading"
            trend.status = new_status
            trend.score = ts.score
            trend.velocity = ts.velocity
            trend.last_seen = max(_aware(trend.last_seen), ts.last_seen)
            trend.summary = summary if not trend.ai_run_id else trend.summary
            trend.keywords = list(dict.fromkeys(list(trend.keywords or []) + kws))[:10]
            trend.platforms = sorted({*trend.platforms, *[Platform(p) for p in ts.platforms]}, key=lambda p: p.value)
            trend.example_source_ids = list(dict.fromkeys(ts.source_ids + list(trend.example_source_ids or [])))[:5]
            if new_status != prev_status or abs(ts.score - prev_score) > max(0.2 * prev_score, 0.1):
                updated.append(trend)
        # trends that went quiet (no longer scored) fade out
        for label, trend in existing.items():
            if label in touched or trend.status in ("fading", "dismissed"):
                continue
            trend.status = "fading"
            trend.velocity = 0
            updated.append(trend)
        await db.flush()
        await cls._link_signals(db, workspace_id, [*detected, *updated], since=now - timedelta(days=window_days))
        for t in detected:
            await emit(db, "TREND_DETECTED", {"trend_id": str(t.id), "brand_id": str(brand_id), "label": t.label,
                                              "score": float(t.score), "status": t.status, "kinds": cls._kinds(scored, t.label)},
                       workspace_id=workspace_id, actor=actor)
        for t in updated:
            await emit(db, "TREND_UPDATED", {"trend_id": str(t.id), "brand_id": str(brand_id), "label": t.label,
                                             "score": float(t.score), "status": t.status, "kinds": cls._kinds(scored, t.label)},
                       workspace_id=workspace_id, actor=actor)
        await db.flush()
        return {"brand_id": str(brand_id), "window_days": window_days, "signals": len(signals), "signals_inserted": inserted,
                "terms_scored": len(scored), "detected": [str(t.id) for t in detected], "updated": [str(t.id) for t in updated],
                "top_terms": [cls.term_dict(t) for t in scored[:15]]}

    @staticmethod
    def _kinds(scored: list[TermScore], label: str) -> list[str]:
        for t in scored:
            if t.term == label:
                return t.kinds
        return []

    @staticmethod
    def _cooccurrence(signals: list[Signal]) -> dict[str, Counter[str]]:
        by_ref: dict[str, set[str]] = defaultdict(set)
        for s in signals:
            by_ref[s.key[2]].add(s.term)
        out: dict[str, Counter[str]] = defaultdict(Counter)
        for terms in by_ref.values():
            for a in terms:
                for b in terms:
                    if a != b:
                        out[a][b] += 1
        return out

    @staticmethod
    def _summary(ts: TermScore) -> str:
        return (f"Mentions of “{ts.term}” averaged {ts.recent_rate:.1f}/day over the last {RECENT_DAYS} days vs "
                f"{ts.baseline_rate:.1f}/day before (z={ts.z:+.1f}); {int(ts.total)} signals from "
                f"{', '.join(ts.kinds)}{' on ' + ', '.join(ts.platforms) if ts.platforms else ''}.")

    @staticmethod
    def term_dict(t: TermScore) -> dict[str, Any]:
        return {"term": t.term, "score": t.score, "z": t.z, "velocity": t.velocity, "recent_rate": t.recent_rate,
                "baseline_rate": t.baseline_rate, "total": t.total, "credibility": t.credibility, "relevance": t.relevance,
                "kinds": t.kinds, "platforms": t.platforms, "series": t.series,
                "source_ids": [str(s) for s in t.source_ids[:5]],
                "first_seen": t.first_seen.isoformat(), "last_seen": t.last_seen.isoformat()}

    @classmethod
    async def _link_signals(cls, db: AsyncSession, workspace_id: UUID, trends: list[Trend], *, since: datetime) -> None:
        for t in trends:
            rows = (await db.execute(select(TrendSignal).where(TrendSignal.workspace_id == workspace_id,
                                                               TrendSignal.term == t.label, TrendSignal.observed_at >= since,
                                                               or_(TrendSignal.trend_id.is_(None), TrendSignal.trend_id != t.id))
                                     .limit(2000))).scalars()
            for s in rows:
                s.trend_id = t.id
        await db.flush()

    # ------------------------------------------------------------------------------------------ reads & agent writes
    @classmethod
    async def signals_view(cls, db: AsyncSession, workspace_id: UUID, brand_id: UUID, *, term: str | None = None,
                           window_days: int = WINDOW_DAYS, limit: int = 25) -> dict[str, Any]:
        now = datetime.now(UTC)
        signals = await cls.collect_signals(db, workspace_id, brand_id, window_days=window_days, now=now)
        if term:
            t = _norm_term(term)
            signals = [s for s in signals if s.term == t or t in s.term]
        scored = score_terms(signals, now=now, brand_terms=await cls.brand_terms(db, workspace_id, brand_id),
                             window_days=window_days)
        return {"brand_id": str(brand_id), "window_days": window_days, "recent_days": RECENT_DAYS,
                "method": "z-score of mention rate (last 3 days vs baseline) × credibility × brand relevance",
                "terms": [cls.term_dict(t) for t in scored[:limit]]}

    @classmethod
    async def list(cls, db: AsyncSession, workspace_id: UUID, *, brand_id: UUID | None = None, status: str | None = None,
                   limit: int = 50) -> list[Trend]:
        stmt = select(Trend).where(Trend.workspace_id == workspace_id)
        if brand_id:
            stmt = stmt.where(Trend.brand_id == brand_id)
        if status:
            stmt = stmt.where(Trend.status == status)
        else:
            stmt = stmt.where(Trend.status != "dismissed")
        return list((await db.execute(stmt.order_by(Trend.score.desc(), Trend.last_seen.desc()).limit(limit))).scalars())

    @classmethod
    async def get(cls, db: AsyncSession, workspace_id: UUID, trend_id: UUID) -> tuple[Trend, list[TrendSignal]]:
        t = (await db.execute(select(Trend).where(Trend.id == trend_id, Trend.workspace_id == workspace_id))).scalar_one_or_none()
        if t is None:
            raise not_found("Trend")
        sigs = list((await db.execute(select(TrendSignal).where(TrendSignal.trend_id == t.id)
                                      .order_by(TrendSignal.observed_at.desc()).limit(200))).scalars())
        return t, sigs

    @classmethod
    async def save(cls, db: AsyncSession, workspace_id: UUID, brand_id: UUID, *, label: str, summary: str | None = None,
                   keywords: list[str] | None = None, source_ids: list[UUID] | None = None, score: float | None = None,
                   status: str | None = None, ai_run_id: UUID | None = None, actor: dict[str, Any] | None = None
                   ) -> tuple[Trend, bool]:
        """Agent naming/explaining a trend: upsert by label. The deterministic score is kept unless none exists."""
        label = " ".join(label.split())[:200]
        if not label:
            raise validation("label required")
        if status and status not in ("emerging", "active", "fading", "dismissed"):
            raise validation("invalid status")
        valid_sources: list[UUID] = []
        if source_ids:
            valid_sources = list((await db.execute(select(ResearchSource.id).where(
                ResearchSource.workspace_id == workspace_id, ResearchSource.id.in_(source_ids)))).scalars())
        now = datetime.now(UTC)
        t = (await db.execute(select(Trend).where(Trend.workspace_id == workspace_id, Trend.brand_id == brand_id,
                                                  func.lower(Trend.label) == label.lower()))).scalar_one_or_none()
        created = t is None
        if t is None:
            t = Trend(id=new_id(), workspace_id=workspace_id, brand_id=brand_id, label=label, summary=summary,
                      score=round(max(0.0, min(999.0, score if score is not None else 0.0)), 3), status=status or "emerging",
                      keywords=[k.lower()[:80] for k in (keywords or [label])][:10], first_seen=now, last_seen=now,
                      example_source_ids=valid_sources[:5], ai_run_id=ai_run_id)
            db.add(t)
        else:
            if summary:
                t.summary = summary[:2000]
            if keywords:
                t.keywords = list(dict.fromkeys(list(t.keywords or []) + [k.lower()[:80] for k in keywords]))[:10]
            if valid_sources:
                t.example_source_ids = list(dict.fromkeys(valid_sources + list(t.example_source_ids or [])))[:5]
            if status:
                t.status = status
            if ai_run_id:
                t.ai_run_id = ai_run_id
            t.last_seen = now
        await db.flush()
        await emit(db, "TREND_DETECTED" if created else "TREND_UPDATED",
                   {"trend_id": str(t.id), "brand_id": str(brand_id), "label": t.label, "score": float(t.score),
                    "status": t.status, "kinds": ["agent"]}, workspace_id=workspace_id, actor=actor)
        return t, created


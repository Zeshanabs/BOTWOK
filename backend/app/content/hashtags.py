"""HashtagService — deterministic hashtag suggestion, validation and usage stats (doc 06: hashtags are a tool, not an agent).

Suggestion score (0..1+): brand core tags 1.0, campaign tags 0.9, historical tags 0.4 + engagement/usage boost,
keyword-derived tags 0.35; +0.3 when the tag already appears as a word in the text. Banned tags (brand settings
`topics.hashtags.banned` and `hashtags.banned=true` rows) are never suggested.
"""
from __future__ import annotations

import re
from collections import Counter
from collections.abc import Iterable
from datetime import UTC, datetime
from typing import Any
from uuid import UUID

from sqlalchemy import or_, select
from sqlalchemy import text as sa_text
from sqlalchemy.ext.asyncio import AsyncSession

from app.content.platform_rules import rules_for
from app.content.validators import VALID_TAG_RE, extract_hashtags, normalize_hashtag
from app.models import Brand, BrandSettings, Campaign, Hashtag

_STOP = set("""a an and are as at be but by for from has have how i if in into is it its of on or our so that the their
them then there these they this to too up us was we were what when where which who why will with you your yours not
can just more most new now get got make made very also than about after before over under out all any each few
some such only own same both being been do does did doing would should could may might must here""".split())
_WORD = re.compile(r"[A-Za-z][A-Za-z0-9]{2,}")


def _section(bs: Any, name: str) -> dict[str, Any]:
    if bs is None:
        return {}
    v = bs.get(name) if isinstance(bs, dict) else getattr(bs, name, None)
    return v if isinstance(v, dict) else {}


def brand_hashtag_sets(bs: Any) -> dict[str, list[str]]:
    tags = _section(bs, "topics").get("hashtags") or {}
    def lst(k: str) -> list[str]:
        v = tags.get(k) or []
        return [normalize_hashtag(str(x)) for x in (v if isinstance(v, list) else [v]) if normalize_hashtag(str(x))]
    return {"core": lst("core"), "campaign": lst("campaign"), "banned": lst("banned")}


def brand_keywords(bs: Any) -> list[str]:
    kws = _section(bs, "topics").get("keywords") or []
    return [str(k) for k in kws if isinstance(k, str)]


def keyword_to_tag(phrase: str) -> str:
    words = re.findall(r"[A-Za-z0-9]+", phrase)
    if not words:
        return ""
    return "".join(w[:1].upper() + w[1:] for w in words)


def text_keywords(text: str, k: int = 8) -> list[str]:
    words = [w for w in _WORD.findall(text or "") if w.casefold() not in _STOP]
    counts = Counter(w.casefold() for w in words)
    first: dict[str, str] = {}
    for w in words:
        first.setdefault(w.casefold(), w)
    ranked = sorted(counts.items(), key=lambda kv: (-kv[1], -len(kv[0])))
    return [first[w] for w, _ in ranked[:k]]


class HashtagService:
    @staticmethod
    async def _brand_and_settings(db: AsyncSession, brand: Brand | UUID | None,
                                  workspace_id: UUID | None) -> tuple[Brand | None, BrandSettings | None]:
        if brand is None:
            return None, None
        if isinstance(brand, Brand):
            return brand, brand.settings
        q = select(Brand).where(Brand.id == brand)
        if workspace_id:
            q = q.where(Brand.workspace_id == workspace_id)
        b = (await db.execute(q)).scalar_one_or_none()
        return b, (b.settings if b else None)

    @staticmethod
    async def banned_for(db: AsyncSession, workspace_id: UUID, brand: Brand | UUID | None) -> set[str]:
        b, bs = await HashtagService._brand_and_settings(db, brand, workspace_id)
        banned = {t.casefold() for t in brand_hashtag_sets(bs)["banned"]}
        q = select(Hashtag.tag).where(Hashtag.workspace_id == workspace_id, Hashtag.banned.is_(True))
        if b is not None:
            q = q.where(or_(Hashtag.brand_id == b.id, Hashtag.brand_id.is_(None)))
        banned |= {str(t).casefold() for t in (await db.execute(q)).scalars().all()}
        return banned

    @staticmethod
    async def suggest(db: AsyncSession, brand: Brand | UUID, platform: str, text: str, k: int | None = None, *,
                      workspace_id: UUID | None = None, campaign_id: UUID | None = None) -> list[dict[str, Any]]:
        b, bs = await HashtagService._brand_and_settings(db, brand, workspace_id)
        ws = workspace_id or (b.workspace_id if b else None)
        rules = rules_for(platform, "text")
        rec = rules["hashtags"].get("recommended")
        hard = rules["hashtags"].get("max")
        if k is None:
            k = rec if rec is not None else 5
        if hard is not None:
            k = min(k, hard)
        k = max(0, int(k))
        if k == 0:
            return []
        sets = brand_hashtag_sets(bs)
        banned = await HashtagService.banned_for(db, ws, b) if ws else {t.casefold() for t in sets["banned"]}
        text_words = {w.casefold() for w in re.findall(r"\w+", text or "")}
        text_tags = {t.casefold() for t in extract_hashtags(text or "")}
        cands: dict[str, dict[str, Any]] = {}

        def add(tag: str, score: float, reason: str) -> None:
            tag = normalize_hashtag(tag)
            if not tag or not VALID_TAG_RE.match(tag) or tag.casefold() in banned or tag.casefold() in text_tags:
                return
            key = tag.casefold()
            bonus = 0.3 if key in text_words or any(w in key for w in text_words if len(w) > 4) else 0.0
            cur = cands.get(key)
            s = round(score + bonus, 4)
            if cur is None or s > cur["score"]:
                cands[key] = {"tag": tag, "score": s, "reason": reason}

        for t in sets["core"]:
            add(t, 1.0, "brand core")
        for t in sets["campaign"]:
            add(t, 0.9, "brand campaign")
        if campaign_id and ws:
            camp = (await db.execute(select(Campaign).where(Campaign.id == campaign_id, Campaign.workspace_id == ws))
                    ).scalar_one_or_none()
            if camp is not None:
                add(keyword_to_tag(camp.name), 0.85, "campaign name")
        if ws:
            q = (select(Hashtag).where(Hashtag.workspace_id == ws, Hashtag.banned.is_(False))
                 .where(or_(Hashtag.platform == platform, Hashtag.platform.is_(None))))
            if b is not None:
                q = q.where(or_(Hashtag.brand_id == b.id, Hashtag.brand_id.is_(None)))
            q = q.order_by(Hashtag.avg_engagement.desc().nullslast(), Hashtag.uses.desc()).limit(200)
            rows = (await db.execute(q)).scalars().all()
            max_uses = max((r.uses for r in rows), default=0) or 1
            max_eng = max((float(r.avg_engagement or 0) for r in rows), default=0.0) or 1.0
            for r in rows:
                s = 0.4 + 0.25 * (float(r.avg_engagement or 0) / max_eng) + 0.15 * (r.uses / max_uses)
                add(str(r.tag), s, "historical performance")
        for kw in brand_keywords(bs):
            if kw.casefold() in (text or "").casefold():
                add(keyword_to_tag(kw), 0.5, "brand keyword in text")
            else:
                add(keyword_to_tag(kw), 0.3, "brand keyword")
        for kw in text_keywords(text or ""):
            add(keyword_to_tag(kw), 0.35, "keyword in text")
        ranked = sorted(cands.values(), key=lambda c: (-c["score"], c["tag"].casefold()))
        return ranked[:k]

    @staticmethod
    def validate(platform: str, hashtags: Iterable[str], banned: Iterable[str] | None = None,
                 format: str = "text") -> dict[str, Any]:
        rules = rules_for(platform, format)
        issues: list[dict[str, Any]] = []
        tags = [normalize_hashtag(h) for h in hashtags or []]
        banned_set = {normalize_hashtag(b).casefold() for b in (banned or [])}
        seen: set[str] = set()
        clean: list[str] = []
        for i, t in enumerate(tags):
            if not t:
                continue
            if not VALID_TAG_RE.match(t):
                issues.append({"code": "invalid_hashtag", "message": f"'#{t}' contains spaces or punctuation",
                               "field": f"hashtags[{i}]", "severity": "error"})
                continue
            if t.casefold() in banned_set:
                issues.append({"code": "banned_hashtag", "message": f"#{t} is banned for this brand",
                               "field": f"hashtags[{i}]", "severity": "error"})
                continue
            if t.casefold() in seen:
                issues.append({"code": "duplicate_hashtag", "message": f"#{t} is duplicated", "field": f"hashtags[{i}]",
                               "severity": "warning"})
                continue
            seen.add(t.casefold())
            clean.append(t)
        hr = rules["hashtags"]
        n = len(seen)
        if hr.get("max") is not None and n > hr["max"]:
            issues.append({"code": "too_many_hashtags", "message": f"{platform} allows at most {hr['max']} hashtags ({n})",
                           "field": "hashtags", "severity": "error"})
        elif hr.get("recommended") is not None and n > hr["recommended"]:
            issues.append({"code": "hashtags_above_recommended",
                           "message": f"{n} hashtags; {hr['recommended']} recommended on {platform}",
                           "field": "hashtags", "severity": "warning"})
        return {"ok": not any(i["severity"] == "error" for i in issues), "issues": issues, "hashtags": clean}

    @staticmethod
    async def record_usage(db: AsyncSession, workspace_id: UUID, brand_id: UUID | None, platform: str | None,
                           tags: Iterable[str]) -> int:
        n = 0
        now = datetime.now(UTC)
        for raw in {normalize_hashtag(t).casefold(): normalize_hashtag(t) for t in tags or [] if normalize_hashtag(t)}.values():
            if not VALID_TAG_RE.match(raw):
                continue
            q = select(Hashtag).where(Hashtag.workspace_id == workspace_id, Hashtag.tag == raw)
            q = q.where(Hashtag.brand_id == brand_id) if brand_id else q.where(Hashtag.brand_id.is_(None))
            q = q.where(Hashtag.platform == platform) if platform else q.where(Hashtag.platform.is_(None))
            row = (await db.execute(q.with_for_update())).scalars().first()
            if row is None:
                db.add(Hashtag(workspace_id=workspace_id, brand_id=brand_id, tag=raw, platform=platform, uses=1,
                               last_used_at=now))
            else:
                row.uses = (row.uses or 0) + 1
                row.last_used_at = now
            n += 1
        await db.flush()
        return n

    @staticmethod
    async def set_banned(db: AsyncSession, workspace_id: UUID, brand_id: UUID | None, tag: str, banned: bool = True) -> None:
        tag = normalize_hashtag(tag)
        await db.execute(sa_text(
            "UPDATE hashtags SET banned=:b WHERE workspace_id=:ws AND tag=:t AND "
            "(brand_id IS NOT DISTINCT FROM CAST(:brand AS uuid))"),
            {"b": banned, "ws": str(workspace_id), "t": tag, "brand": str(brand_id) if brand_id else None})

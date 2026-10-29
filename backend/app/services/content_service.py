"""ContentService — ideas, campaigns, content items, variants, versions, sources, assets, status transitions and the
AI entry points (doc 09 §9.3–9.4, doc 17 "Ideas & content", doc 19 §19.7).

Rules enforced here (not only in routers, so agent tools obey them too):
- every query filters ``workspace_id``;
- approved/archived items are locked (409 ``content_locked``) until transitioned back to draft;
- the guard matrix lives in ``app.content.transitions`` (pure);
- AI output always lands in ``ai_generated`` / ``needs_review`` (or ``rejected`` when a deterministic policy blocks
  it) — never ``approved``.
"""
from __future__ import annotations

import contextlib
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any
from uuid import UUID

from sqlalchemy import Text, and_, cast, func, or_, select
from sqlalchemy import text as sa_text
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.content import _compat
from app.content.claims import extract_claims
from app.content.hashtags import HashtagService
from app.content.platform_rules import support_of
from app.content.policy import has_contradicted_claims, policies_from_brand_settings, policy_check, risk_from
from app.content.transitions import (
    ADMIN_ROLES,
    EDIT_ROLES,
    LOCKED_STATUSES,
    can_transition,
    is_known_transition,
)
from app.content.validators import validate_variant
from app.core.errors import ProblemError, conflict, forbidden, not_found, validation
from app.core.events import emit
from app.core.logging import get_logger
from app.core.pagination import decode_cursor, encode_cursor
from app.models import (
    Approval,
    Brand,
    Campaign,
    ContentAsset,
    ContentIdea,
    ContentItem,
    ContentPillar,
    ContentSource,
    ContentVariant,
    ContentVersion,
    MediaAsset,
    ResearchSource,
    ScheduledPost,
    SocialAccount,
)
from app.models.enums import (
    ApprovalStatus,
    ContentFormat,
    ContentStatus,
    ContentType,
    Platform,
    RiskLevel,
    ScheduleStatus,
)

log = get_logger("content")

LIVE_SCHEDULE_STATUSES = (ScheduleStatus.scheduled, ScheduleStatus.queued, ScheduleStatus.publishing, ScheduleStatus.paused)
ITEM_FIELDS = ("title", "content_type", "master_format", "body", "language", "pillar_id", "campaign_id")
VARIANT_FIELDS = ("text", "segments", "hashtags", "media_plan", "platform_metadata", "social_account_id", "changes_made")
BODY_KEYS = ("hook", "body_md", "cta", "hashtags", "keywords", "visual_concept", "alt_text", "notes")
IDEA_STATUSES = ("new", "shortlisted", "promoted", "discarded")
CAMPAIGN_STATUSES = ("planned", "active", "completed", "archived")
IDEA_EMBED_THRESHOLD = 0.88
IDEA_TRGM_THRESHOLD = 0.6
GENERATE_MODES = {"write": "write", "regenerate": "write", "rewrite": "rewrite", "shorten": "rewrite",
                  "expand": "rewrite", "change_tone": "rewrite"}


# ── actor normalisation ─────────────────────────────────────────────────────────

@dataclass
class Actor:
    workspace_id: UUID
    user_id: UUID | None
    role: str
    kind: str = "user"                  # user | agent | system
    agent_id: str | None = None
    member: Any = field(default=None, repr=False)

    @property
    def event_actor(self) -> dict[str, Any]:
        if self.kind == "agent":
            return {"type": "agent", "id": self.agent_id, "on_behalf_of": str(self.user_id) if self.user_id else None}
        if self.kind == "system":
            return {"type": "system"}
        return {"type": "user", "id": str(self.user_id) if self.user_id else None}

    @property
    def author(self) -> tuple[str, str]:
        if self.kind == "agent":
            return "agent", self.agent_id or "agent"
        return ("user", str(self.user_id)) if self.user_id else ("system", "system")

    @property
    def audit_actor(self) -> Any:
        if self.member is not None:
            return self.member
        if self.kind == "agent":
            return {"type": "agent", "id": self.agent_id or "agent", "workspace_id": str(self.workspace_id)}
        if self.user_id:
            return {"type": "user", "id": str(self.user_id), "workspace_id": str(self.workspace_id)}
        return {"type": "system", "id": "system", "workspace_id": str(self.workspace_id)}

    @property
    def requested_by(self) -> str:
        if self.kind == "agent":
            return f"agent:{self.agent_id}"
        return str(self.user_id) if self.user_id else "system"


def as_actor(member: Any) -> Actor:
    if isinstance(member, Actor):
        return member
    role = getattr(member, "role", None)
    role_s = (getattr(role, "value", role) or "viewer")
    user = getattr(member, "user", None)
    user_id = getattr(user, "id", None) or getattr(member, "user_id", None)
    return Actor(workspace_id=member.workspace_id, user_id=user_id, role=str(role_s), member=member)


def _require(actor: Actor, roles: frozenset[str], what: str = "do this") -> None:
    if actor.kind == "system":
        return
    if actor.role not in roles:
        raise forbidden(f"Your role ({actor.role}) cannot {what}")


def _enum(enum_cls: Any, value: Any, field_name: str) -> Any:
    if value is None or isinstance(value, enum_cls):
        return value
    try:
        return enum_cls(str(value))
    except ValueError as e:
        raise validation(f"Invalid {field_name}: {value}",
                         [{"code": "invalid_enum", "field": field_name, "message": f"'{value}' is not valid"}]) from e


def _uuid(v: Any, field_name: str = "id") -> UUID | None:
    if v is None or v == "":
        return None
    if isinstance(v, UUID):
        return v
    try:
        return UUID(str(v))
    except ValueError as e:
        raise validation(f"Invalid {field_name}", [{"code": "invalid_uuid", "field": field_name, "message": str(v)}]) from e


def _jsonable(v: Any) -> Any:
    if isinstance(v, UUID):
        return str(v)
    if hasattr(v, "value") and not isinstance(v, (str, int, float, bool)):
        return v.value
    if isinstance(v, dict):
        return {k: _jsonable(x) for k, x in v.items()}
    if isinstance(v, (list, tuple)):
        return [_jsonable(x) for x in v]
    if isinstance(v, datetime):
        return v.isoformat()
    return v


def _cursor(cursor: str | None) -> dict[str, Any] | None:
    try:
        cur = decode_cursor(cursor)
        if cur is not None:
            datetime.fromisoformat(cur["t"])
            UUID(cur["id"])
        return cur
    except Exception as e:
        raise validation("Invalid cursor", [{"code": "invalid_cursor", "field": "cursor", "message": "malformed"}]) from e


def item_snapshot(item: ContentItem) -> dict[str, Any]:
    return _jsonable({k: getattr(item, k) for k in ITEM_FIELDS})


def variant_snapshot(v: ContentVariant) -> dict[str, Any]:
    return _jsonable({"platform": v.platform, "format": v.format, **{k: getattr(v, k) for k in VARIANT_FIELDS}})


def item_text(item: ContentItem, include_variants: bool = True) -> str:
    b = item.body or {}
    parts = [str(item.title or "")] + [str(b.get(k) or "") for k in ("hook", "body_md", "body", "cta")]
    if include_variants:
        for v in item.variants or []:
            parts.append(v.text or "")
            for s in v.segments or []:
                parts.append(s if isinstance(s, str) else str((s or {}).get("text") or ""))
    return "\n".join(p for p in parts if p)


def variant_text(v: ContentVariant) -> str:
    segs = [s if isinstance(s, str) else str((s or {}).get("text") or "") for s in (v.segments or [])]
    return "\n".join([v.text or "", *segs]).strip()


def _asset_dict(ca: ContentAsset) -> dict[str, Any]:
    m = ca.media
    return {"id": ca.id, "media_asset_id": ca.media_asset_id, "variant_id": ca.variant_id,
            "content_item_id": ca.content_item_id, "role": ca.role, "position": ca.position,
            "alt_text": ca.alt_text if ca.alt_text is not None else (m.alt_text if m else None),
            "media": ({"id": m.id, "kind": m.kind, "mime": m.mime, "width": m.width, "height": m.height,
                       "duration_ms": m.duration_ms, "bytes": m.bytes, "sha256": m.sha256, "alt_text": m.alt_text,
                       "status": m.status, "object_key": m.object_key, "bucket": m.bucket} if m else None)}


def _validation_assets(v: ContentVariant) -> list[dict[str, Any]]:
    out = []
    for ca in v.assets or []:
        m = ca.media
        out.append({"kind": m.kind if m else None, "mime": m.mime if m else None, "role": ca.role,
                    "alt_text": ca.alt_text if ca.alt_text is not None else (m.alt_text if m else None)})
    return out


class ContentService:
    # ── loaders ──────────────────────────────────────────────────────────────────
    @staticmethod
    async def _brand(db: AsyncSession, ws: UUID, brand_id: Any) -> Brand:
        bid = _uuid(brand_id, "brand_id")
        b = (await db.execute(select(Brand).where(Brand.id == bid, Brand.workspace_id == ws,
                                                  Brand.deleted_at.is_(None)))).scalar_one_or_none()
        if b is None:
            raise not_found("Brand")
        return b

    @staticmethod
    async def get_item(db: AsyncSession, workspace_id: UUID, item_id: Any, *, for_update: bool = False,
                       include_deleted: bool = False) -> ContentItem:
        q = (select(ContentItem).where(ContentItem.id == _uuid(item_id, "content_id"),
                                       ContentItem.workspace_id == workspace_id)
             .execution_options(populate_existing=True))
        if not include_deleted:
            q = q.where(ContentItem.deleted_at.is_(None))
        if for_update:
            q = q.with_for_update(of=ContentItem)
        item = (await db.execute(q)).scalar_one_or_none()
        if item is None:
            raise not_found("Content")
        return item

    @staticmethod
    async def get_variant(db: AsyncSession, workspace_id: UUID, item_id: Any, variant_id: Any) -> ContentVariant:
        v = (await db.execute(select(ContentVariant).where(
            ContentVariant.id == _uuid(variant_id, "variant_id"), ContentVariant.workspace_id == workspace_id,
            ContentVariant.content_item_id == _uuid(item_id, "content_id")).execution_options(populate_existing=True))
             ).scalar_one_or_none()
        if v is None:
            raise not_found("Variant")
        return v

    @staticmethod
    async def _check_refs(db: AsyncSession, ws: UUID, brand_id: UUID, data: dict[str, Any]) -> None:
        if data.get("campaign_id"):
            ok = (await db.execute(select(Campaign.id).where(Campaign.id == _uuid(data["campaign_id"], "campaign_id"),
                                                             Campaign.workspace_id == ws, Campaign.brand_id == brand_id))
                  ).scalar_one_or_none()
            if ok is None:
                raise validation("Unknown campaign", [{"code": "not_found", "field": "campaign_id", "message": "Campaign not found"}])
        if data.get("pillar_id"):
            ok = (await db.execute(select(ContentPillar.id).where(ContentPillar.id == _uuid(data["pillar_id"], "pillar_id"),
                                                                  ContentPillar.workspace_id == ws,
                                                                  ContentPillar.brand_id == brand_id))).scalar_one_or_none()
            if ok is None:
                raise validation("Unknown pillar", [{"code": "not_found", "field": "pillar_id", "message": "Pillar not found"}])
        if data.get("idea_id"):
            ok = (await db.execute(select(ContentIdea.id).where(ContentIdea.id == _uuid(data["idea_id"], "idea_id"),
                                                                ContentIdea.workspace_id == ws))).scalar_one_or_none()
            if ok is None:
                raise validation("Unknown idea", [{"code": "not_found", "field": "idea_id", "message": "Idea not found"}])

    @staticmethod
    def _assert_editable(item: ContentItem) -> None:
        st = item.status.value if hasattr(item.status, "value") else str(item.status)
        if st in LOCKED_STATUSES:
            raise conflict("content_locked", f"Content is {st}; transition it back to draft before editing")

    @staticmethod
    async def _write_version(db: AsyncSession, ws: UUID, target_type: str, target_id: UUID, version: int,
                             snapshot: dict[str, Any], author: tuple[str, str], ai_call_id: Any = None,
                             diff_summary: str | None = None) -> ContentVersion:
        ver = ContentVersion(workspace_id=ws, target_type=target_type, target_id=target_id, version=version,
                             snapshot=snapshot, author_type=author[0], author_id=author[1],
                             ai_call_id=_uuid(ai_call_id, "ai_call_id") if ai_call_id else None, diff_summary=diff_summary)
        db.add(ver)
        await db.flush()
        return ver

    @staticmethod
    async def _live_schedules(db: AsyncSession, ws: UUID, item_id: UUID) -> int:
        q = (select(func.count()).select_from(ScheduledPost)
             .join(ContentVariant, ContentVariant.id == ScheduledPost.content_variant_id)
             .where(ScheduledPost.workspace_id == ws, ContentVariant.content_item_id == item_id,
                    ScheduledPost.status.in_(LIVE_SCHEDULE_STATUSES)))
        return int((await db.execute(q)).scalar() or 0)

    # ── serialization ────────────────────────────────────────────────────────────
    @staticmethod
    def serialize_variant(v: ContentVariant) -> dict[str, Any]:
        return {"id": v.id, "content_item_id": v.content_item_id, "platform": v.platform, "format": v.format,
                "social_account_id": v.social_account_id, "text": v.text, "segments": v.segments or [],
                "hashtags": v.hashtags or [], "media_plan": v.media_plan or {}, "platform_metadata": v.platform_metadata or {},
                "status": v.status, "validation": v.validation, "critique": v.critique, "factcheck": v.factcheck,
                "changes_made": v.changes_made or [], "current_version": v.current_version, "ai_generated": v.ai_generated,
                "generation_metadata": v.generation_metadata or {}, "assets": [_asset_dict(a) for a in v.assets or []],
                "created_at": v.created_at, "updated_at": v.updated_at}

    @staticmethod
    async def serialize_item(db: AsyncSession, item: ContentItem, *, full: bool = True) -> dict[str, Any]:
        out: dict[str, Any] = {k: getattr(item, k) for k in (
            "id", "workspace_id", "brand_id", "campaign_id", "idea_id", "pillar_id", "title", "content_type", "master_format",
            "status", "body", "language", "current_version", "ai_generated", "generation_metadata", "risk_level",
            "approval_required", "critique", "factcheck", "created_by", "assigned_to", "created_at", "updated_at")}
        variants = list(item.variants or [])
        out["platforms"] = sorted({v.platform.value for v in variants})
        out["variant_count"] = len(variants)
        if not full:
            return out
        out["variants"] = [ContentService.serialize_variant(v) for v in variants]
        srcs = list(item.sources or [])
        info: dict[UUID, ResearchSource] = {}
        if srcs:
            rows = (await db.execute(select(ResearchSource).where(
                ResearchSource.id.in_([s.source_id for s in srcs]), ResearchSource.workspace_id == item.workspace_id))
            ).scalars().all()
            info = {r.id: r for r in rows}
        out["sources"] = [{"source_id": s.source_id, "claim_text": s.claim_text, "used_for": s.used_for,
                           "title": getattr(info.get(s.source_id), "title", None),
                           "url": getattr(info.get(s.source_id), "canonical_url", None),
                           "domain": getattr(info.get(s.source_id), "domain", None),
                           "credibility": (float(info[s.source_id].credibility_score)
                                           if s.source_id in info and info[s.source_id].credibility_score is not None else None)}
                          for s in srcs]
        assets = (await db.execute(select(ContentAsset).where(
            ContentAsset.workspace_id == item.workspace_id, ContentAsset.content_item_id == item.id,
            ContentAsset.variant_id.is_(None)).order_by(ContentAsset.position))).scalars().all()
        out["assets"] = [_asset_dict(a) for a in assets]
        return out

    # ── ideas ────────────────────────────────────────────────────────────────────
    @staticmethod
    async def list_ideas(db: AsyncSession, member: Any, *, brand_id: Any = None, status: list[str] | None = None,
                         q: str | None = None, campaign_id: Any = None, limit: int = 50,
                         cursor: str | None = None) -> tuple[list[ContentIdea], str | None]:
        a = as_actor(member)
        stmt = select(ContentIdea).where(ContentIdea.workspace_id == a.workspace_id)
        if brand_id:
            stmt = stmt.where(ContentIdea.brand_id == _uuid(brand_id, "brand_id"))
        if campaign_id:
            stmt = stmt.where(ContentIdea.campaign_id == _uuid(campaign_id, "campaign_id"))
        if status:
            stmt = stmt.where(ContentIdea.status.in_(status))
        if q:
            like = f"%{q}%"
            stmt = stmt.where(or_(ContentIdea.title.ilike(like), ContentIdea.angle.ilike(like)))
        cur = _cursor(cursor)
        if cur:
            t = datetime.fromisoformat(cur["t"])
            stmt = stmt.where(or_(ContentIdea.created_at < t, and_(ContentIdea.created_at == t, ContentIdea.id < UUID(cur["id"]))))
        stmt = stmt.order_by(ContentIdea.created_at.desc(), ContentIdea.id.desc()).limit(limit + 1)
        rows = list((await db.execute(stmt)).scalars().all())
        nxt = None
        if len(rows) > limit:
            rows = rows[:limit]
            nxt = encode_cursor({"t": rows[-1].created_at.isoformat(), "id": str(rows[-1].id)})
        return rows, nxt

    @staticmethod
    async def get_idea(db: AsyncSession, workspace_id: UUID, idea_id: Any, for_update: bool = False) -> ContentIdea:
        q = select(ContentIdea).where(ContentIdea.id == _uuid(idea_id, "idea_id"), ContentIdea.workspace_id == workspace_id)
        if for_update:
            q = q.with_for_update()
        idea = (await db.execute(q)).scalar_one_or_none()
        if idea is None:
            raise not_found("Idea")
        return idea

    @staticmethod
    def _idea_fields(data: dict[str, Any]) -> dict[str, Any]:
        out: dict[str, Any] = {}
        for k in ("title", "angle", "hooks", "evidence", "score", "novelty_score", "status"):
            if k in data:
                out[k] = data[k]
        if "content_type" in data:
            out["content_type"] = _enum(ContentType, data["content_type"], "content_type")
        if "formats" in data:
            out["formats"] = [_enum(ContentFormat, f, "formats") for f in data["formats"] or []]
        if "platforms" in data:
            out["platforms"] = [_enum(Platform, p, "platforms") for p in data["platforms"] or []]
        for k in ("campaign_id", "pillar_id"):
            if k in data:
                out[k] = _uuid(data[k], k)
        if out.get("status") is not None and out["status"] not in IDEA_STATUSES:
            raise validation("Invalid idea status", [{"code": "invalid_enum", "field": "status", "message": out["status"]}])
        if "hooks" in out and out["hooks"] is None:
            out["hooks"] = []
        if "evidence" in out and out["evidence"] is None:
            out["evidence"] = {}
        return out

    @staticmethod
    async def find_duplicate_idea(db: AsyncSession, workspace_id: UUID, brand_id: UUID, title: str, angle: str | None,
                                  *, embedding: list[float] | None = None, exclude_id: UUID | None = None
                                  ) -> dict[str, Any] | None:
        """Embedding cosine (> 0.88) vs the last 500 ideas when embeddings exist; else pg_trgm similarity (> 0.6)
        on title+angle vs the last 500 ideas and last 200 content items."""
        if embedding is not None and len(embedding) == settings.embedding_dims:
            recent = (select(ContentIdea.id).where(ContentIdea.workspace_id == workspace_id, ContentIdea.brand_id == brand_id,
                                                   ContentIdea.embedding.is_not(None))
                      .order_by(ContentIdea.created_at.desc()).limit(500)).subquery()
            dist = ContentIdea.embedding.cosine_distance(embedding)
            q = (select(ContentIdea.id, ContentIdea.title, dist.label("d")).where(ContentIdea.id.in_(select(recent.c.id)))
                 .order_by(dist).limit(1))
            if exclude_id:
                q = q.where(ContentIdea.id != exclude_id)
            row = (await db.execute(q)).first()
            if row is not None and (1 - float(row.d)) > IDEA_EMBED_THRESHOLD:
                return {"kind": "idea", "id": row.id, "title": row.title, "similarity": round(1 - float(row.d), 4),
                        "method": "embedding"}
        probe = f"{title} {angle or ''}".strip().lower()
        res = await db.execute(sa_text(
            "SELECT kind, id, title, sim FROM ("
            "  SELECT 'idea' AS kind, id, title, similarity(lower(title || ' ' || coalesce(angle, '')), :p) AS sim FROM ("
            "    SELECT id, title, angle FROM content_ideas WHERE workspace_id = :ws AND brand_id = :b "
            "    AND (CAST(:ex AS uuid) IS NULL OR id <> CAST(:ex AS uuid)) ORDER BY created_at DESC LIMIT 500) i"
            "  UNION ALL "
            "  SELECT 'content' AS kind, id, title, similarity(lower(title || ' ' || coalesce(body->>'hook', '')), :p) FROM ("
            "    SELECT id, title, body FROM content_items WHERE workspace_id = :ws AND brand_id = :b AND deleted_at IS NULL "
            "    ORDER BY created_at DESC LIMIT 200) c"
            ") s WHERE sim > :th ORDER BY sim DESC LIMIT 1"),
            {"p": probe, "ws": str(workspace_id), "b": str(brand_id), "th": IDEA_TRGM_THRESHOLD,
             "ex": str(exclude_id) if exclude_id else None})
        row = res.first()
        if row is None:
            return None
        return {"kind": row.kind, "id": row.id, "title": row.title, "similarity": round(float(row.sim), 4), "method": "trigram"}

    @staticmethod
    async def create_idea(db: AsyncSession, member: Any, data: dict[str, Any], *, ai_run_id: Any = None,
                          dedupe: bool = False) -> tuple[ContentIdea | None, dict[str, Any] | None]:
        """Returns (idea, duplicate). With ``dedupe=True`` a duplicate is not saved and (None, duplicate) is returned."""
        a = as_actor(member)
        _require(a, EDIT_ROLES, "create ideas")
        brand = await ContentService._brand(db, a.workspace_id, data.get("brand_id"))
        fields = ContentService._idea_fields(data)
        if not (fields.get("title") or "").strip():
            raise validation("Idea title is required", [{"code": "required", "field": "title", "message": "required"}])
        await ContentService._check_refs(db, a.workspace_id, brand.id, fields)
        emb = await _compat.embed_texts([f"{fields['title']}\n{fields.get('angle') or ''}"], db, a.workspace_id)
        vec, model = (emb[0][0], emb[1]) if emb else (None, None)
        if vec is not None and len(vec) != settings.embedding_dims:
            vec, model = None, None
        dup = await ContentService.find_duplicate_idea(db, a.workspace_id, brand.id, fields["title"], fields.get("angle"),
                                                       embedding=vec)
        if dup and dedupe:
            return None, dup
        evidence = dict(fields.pop("evidence", None) or {})
        if dup:
            evidence["possible_duplicate"] = _jsonable(dup)
        idea = ContentIdea(workspace_id=a.workspace_id, brand_id=brand.id, created_by=a.user_id, evidence=evidence,
                           ai_run_id=_uuid(ai_run_id, "ai_run_id") if ai_run_id else None, embedding=vec,
                           embedding_model=model, **{k: v for k, v in fields.items() if v is not None or k == "angle"})
        if dup and idea.novelty_score is None:
            idea.novelty_score = round(1 - dup["similarity"], 3)
        db.add(idea)
        await db.flush()
        await db.refresh(idea)
        await _compat.audit(db, a.audit_actor, "idea.create", "content_idea", idea.id, after={"title": idea.title})
        return idea, dup

    @staticmethod
    async def save_ideas(db: AsyncSession, member: Any, brand_id: Any, ideas: list[dict[str, Any]], *,
                         ai_run_id: Any = None) -> dict[str, Any]:
        """Batch save with dedupe (DB + within the batch). Used by the ``ideas.save`` tool."""
        saved: list[dict[str, Any]] = []
        dropped: list[dict[str, Any]] = []
        seen: set[str] = set()
        for raw in ideas or []:
            data = dict(raw or {})
            data["brand_id"] = data.get("brand_id") or brand_id
            if "hook_options" in data and "hooks" not in data:
                data["hooks"] = data.pop("hook_options")
            if "evidence_sources" in data:
                ev = dict(data.get("evidence") or {})
                ev["source_ids"] = [str(s) for s in data.pop("evidence_sources") or []]
                data["evidence"] = ev
            pillar = data.pop("pillar", None)
            if pillar and not data.get("pillar_id"):
                pid = await ContentService._pillar_by_name(db, as_actor(member).workspace_id, data["brand_id"], pillar)
                if pid:
                    data["pillar_id"] = pid
            key = " ".join(f"{data.get('title', '')} {data.get('angle', '')}".lower().split())
            if not data.get("title") or key in seen:
                dropped.append({"title": data.get("title"), "reason": "duplicate_in_batch" if data.get("title") else "missing_title"})
                continue
            seen.add(key)
            data = {k: v for k, v in data.items() if k in {"brand_id", "title", "angle", "content_type", "formats", "platforms",
                                                           "hooks", "evidence", "score", "novelty_score", "campaign_id",
                                                           "pillar_id"}}
            try:
                idea, dup = await ContentService.create_idea(db, member, data, ai_run_id=ai_run_id, dedupe=True)
            except ProblemError as e:
                dropped.append({"title": data.get("title"), "reason": e.type, "detail": e.detail})
                continue
            if idea is None:
                dropped.append({"title": data.get("title"), "reason": "duplicate", "duplicate_of": _jsonable(dup)})
            else:
                saved.append({"id": str(idea.id), "title": idea.title})
        return {"saved": saved, "dropped": dropped}

    @staticmethod
    async def _pillar_by_name(db: AsyncSession, ws: UUID, brand_id: Any, name: str) -> UUID | None:
        return (await db.execute(select(ContentPillar.id).where(
            ContentPillar.workspace_id == ws, ContentPillar.brand_id == _uuid(brand_id, "brand_id"),
            func.lower(ContentPillar.name) == str(name).lower()))).scalar_one_or_none()

    @staticmethod
    async def update_idea(db: AsyncSession, member: Any, idea_id: Any, patch: dict[str, Any]) -> ContentIdea:
        a = as_actor(member)
        _require(a, EDIT_ROLES, "edit ideas")
        idea = await ContentService.get_idea(db, a.workspace_id, idea_id, for_update=True)
        fields = ContentService._idea_fields(patch)
        await ContentService._check_refs(db, a.workspace_id, idea.brand_id, fields)
        before = {k: _jsonable(getattr(idea, k)) for k in fields}
        for k, v in fields.items():
            if k == "title" and not (v or "").strip():
                raise validation("Idea title is required")
            setattr(idea, k, v)
        await db.flush()
        await db.refresh(idea)
        await _compat.audit(db, a.audit_actor, "idea.update", "content_idea", idea.id, before=before,
                            after={k: _jsonable(v) for k, v in fields.items()})
        return idea

    @staticmethod
    async def delete_idea(db: AsyncSession, member: Any, idea_id: Any) -> None:
        a = as_actor(member)
        _require(a, EDIT_ROLES, "delete ideas")
        idea = await ContentService.get_idea(db, a.workspace_id, idea_id, for_update=True)
        await db.delete(idea)
        await db.flush()
        await _compat.audit(db, a.audit_actor, "idea.delete", "content_idea", idea.id, before={"title": idea.title})

    @staticmethod
    async def promote_idea(db: AsyncSession, member: Any, idea_id: Any, overrides: dict[str, Any] | None = None) -> ContentItem:
        a = as_actor(member)
        _require(a, EDIT_ROLES, "promote ideas")
        idea = await ContentService.get_idea(db, a.workspace_id, idea_id, for_update=True)
        if idea.status == "promoted" and idea.promoted_content_id:
            raise conflict("idea_already_promoted", f"Idea already promoted to {idea.promoted_content_id}")
        ov = {k: v for k, v in (overrides or {}).items() if v is not None}
        hooks = idea.hooks or []
        first_hook = hooks[0] if hooks else None
        if isinstance(first_hook, dict):
            first_hook = first_hook.get("text") or first_hook.get("hook")
        fmt = ov.get("master_format") or (idea.formats[0] if idea.formats else ContentFormat.text)
        data = {"brand_id": idea.brand_id, "title": ov.get("title") or idea.title, "content_type": idea.content_type,
                "pillar_id": idea.pillar_id, "campaign_id": ov.get("campaign_id") or idea.campaign_id, "idea_id": idea.id,
                "master_format": fmt, "assigned_to": ov.get("assigned_to"),
                "body": {"hook": first_hook or "", "notes": idea.angle or "",
                         "hook_options": hooks, "target_platforms": [_jsonable(p) for p in idea.platforms or []]}}
        item = await ContentService.create_item(db, a, data)
        idea.status = "promoted"
        idea.promoted_content_id = item.id
        await db.flush()
        await _compat.audit(db, a.audit_actor, "idea.promote", "content_idea", idea.id, after={"content_item_id": str(item.id)})
        return item

    @staticmethod
    async def generate_ideas(db: AsyncSession, member: Any, *, brand_id: Any, count: int = 10, pillars: list[str] | None = None,
                             platforms: list[str] | None = None, from_: dict[str, Any] | None = None) -> dict[str, Any]:
        a = as_actor(member)
        _require(a, EDIT_ROLES, "generate ideas")
        brand = await ContentService._brand(db, a.workspace_id, brand_id)
        inputs = _jsonable({"brand_id": brand.id, "count": count, "pillars": pillars or [], "platforms": platforms or [],
                            "from": from_ or {}})
        return await ContentService._run(db, a, brand.id, "ideation", "generate", inputs,
                                         f"Generate {count} content ideas for {brand.name}")

    # ── campaigns ────────────────────────────────────────────────────────────────
    @staticmethod
    async def list_campaigns(db: AsyncSession, member: Any, *, brand_id: Any = None, status: str | None = None,
                             limit: int = 100, cursor: str | None = None) -> tuple[list[Campaign], str | None]:
        a = as_actor(member)
        q = select(Campaign).where(Campaign.workspace_id == a.workspace_id)
        if brand_id:
            q = q.where(Campaign.brand_id == _uuid(brand_id, "brand_id"))
        if status:
            q = q.where(Campaign.status == status)
        cur = _cursor(cursor)
        if cur:
            t = datetime.fromisoformat(cur["t"])
            q = q.where(or_(Campaign.created_at < t, and_(Campaign.created_at == t, Campaign.id < UUID(cur["id"]))))
        rows = list((await db.execute(q.order_by(Campaign.created_at.desc(), Campaign.id.desc()).limit(limit + 1))).scalars())
        nxt = None
        if len(rows) > limit:
            rows = rows[:limit]
            nxt = encode_cursor({"t": rows[-1].created_at.isoformat(), "id": str(rows[-1].id)})
        return rows, nxt

    @staticmethod
    async def get_campaign(db: AsyncSession, workspace_id: UUID, campaign_id: Any) -> Campaign:
        c = (await db.execute(select(Campaign).where(Campaign.id == _uuid(campaign_id, "campaign_id"),
                                                     Campaign.workspace_id == workspace_id))).scalar_one_or_none()
        if c is None:
            raise not_found("Campaign")
        return c

    @staticmethod
    def _campaign_fields(data: dict[str, Any]) -> dict[str, Any]:
        out = {k: data[k] for k in ("name", "description", "goal", "starts_on", "ends_on", "color", "status") if k in data}
        if out.get("status") is not None and out["status"] not in CAMPAIGN_STATUSES:
            raise validation("Invalid campaign status", [{"code": "invalid_enum", "field": "status", "message": out["status"]}])
        return out

    @staticmethod
    async def create_campaign(db: AsyncSession, member: Any, data: dict[str, Any]) -> Campaign:
        a = as_actor(member)
        _require(a, EDIT_ROLES, "create campaigns")
        brand = await ContentService._brand(db, a.workspace_id, data.get("brand_id"))
        fields = ContentService._campaign_fields(data)
        if not (fields.get("name") or "").strip():
            raise validation("Campaign name is required")
        if fields.get("starts_on") and fields.get("ends_on") and fields["ends_on"] < fields["starts_on"]:
            raise validation("ends_on must be on or after starts_on")
        c = Campaign(workspace_id=a.workspace_id, brand_id=brand.id, created_by=a.user_id or brand.created_by,
                     **{k: v for k, v in fields.items() if v is not None})
        db.add(c)
        await db.flush()
        await db.refresh(c)
        await _compat.audit(db, a.audit_actor, "campaign.create", "campaign", c.id, after={"name": c.name})
        return c

    @staticmethod
    async def update_campaign(db: AsyncSession, member: Any, campaign_id: Any, patch: dict[str, Any]) -> Campaign:
        a = as_actor(member)
        _require(a, EDIT_ROLES, "edit campaigns")
        c = await ContentService.get_campaign(db, a.workspace_id, campaign_id)
        fields = ContentService._campaign_fields(patch)
        before = {k: _jsonable(getattr(c, k)) for k in fields}
        for k, v in fields.items():
            if k == "name" and not (v or "").strip():
                raise validation("Campaign name is required")
            setattr(c, k, v)
        if c.starts_on and c.ends_on and c.ends_on < c.starts_on:
            raise validation("ends_on must be on or after starts_on")
        await db.flush()
        await db.refresh(c)
        await _compat.audit(db, a.audit_actor, "campaign.update", "campaign", c.id, before=before,
                            after={k: _jsonable(v) for k, v in fields.items()})
        return c

    @staticmethod
    async def delete_campaign(db: AsyncSession, member: Any, campaign_id: Any) -> None:
        a = as_actor(member)
        _require(a, ADMIN_ROLES, "delete campaigns")
        c = await ContentService.get_campaign(db, a.workspace_id, campaign_id)
        await db.delete(c)
        await db.flush()
        await _compat.audit(db, a.audit_actor, "campaign.delete", "campaign", c.id, before={"name": c.name})

    # ── items ────────────────────────────────────────────────────────────────────
    @staticmethod
    def _normalize_body(body: Any) -> dict[str, Any]:
        if body is None:
            return {}
        if hasattr(body, "model_dump"):
            body = body.model_dump(exclude_none=True)
        if not isinstance(body, dict):
            raise validation("body must be an object")
        out = dict(body)
        if "body" in out and "body_md" not in out and isinstance(out["body"], str):
            out["body_md"] = out.pop("body")
        for k in ("hashtags", "keywords"):
            if k in out and out[k] is None:
                out[k] = []
        return _jsonable(out)

    @staticmethod
    async def create_item(db: AsyncSession, member: Any, data: dict[str, Any], *, ai_generated: bool = False,
                          status: ContentStatus | None = None, generation_metadata: dict[str, Any] | None = None,
                          ai_call_id: Any = None) -> ContentItem:
        a = as_actor(member)
        _require(a, EDIT_ROLES, "create content")
        brand = await ContentService._brand(db, a.workspace_id, data.get("brand_id"))
        title = (data.get("title") or "").strip()
        if not title:
            raise validation("Title is required", [{"code": "required", "field": "title", "message": "required"}])
        await ContentService._check_refs(db, a.workspace_id, brand.id, data)
        if status is None:
            status = ContentStatus.ai_generated if (ai_generated or a.kind == "agent") else ContentStatus.draft
        if status in (ContentStatus.approved,) or (a.kind == "agent" and status not in (ContentStatus.ai_generated,
                                                                                       ContentStatus.needs_review)):
            status = ContentStatus.ai_generated
        item = ContentItem(
            workspace_id=a.workspace_id, brand_id=brand.id, campaign_id=_uuid(data.get("campaign_id"), "campaign_id"),
            idea_id=_uuid(data.get("idea_id"), "idea_id"), pillar_id=_uuid(data.get("pillar_id"), "pillar_id"),
            title=title, content_type=_enum(ContentType, data.get("content_type"), "content_type"),
            master_format=_enum(ContentFormat, data.get("master_format") or "text", "master_format"),
            status=status, body=ContentService._normalize_body(data.get("body")), language=data.get("language") or "en",
            current_version=1, ai_generated=bool(ai_generated or a.kind == "agent"),
            generation_metadata=_jsonable(generation_metadata or {}), risk_level=RiskLevel.low, approval_required=True,
            created_by=a.user_id or brand.created_by, assigned_to=_uuid(data.get("assigned_to"), "assigned_to"))
        db.add(item)
        await db.flush()
        await ContentService._write_version(db, a.workspace_id, "item", item.id, 1, item_snapshot(item), a.author,
                                            ai_call_id, "created")
        await emit(db, "CONTENT_CREATED", {"content_item_id": str(item.id), "brand_id": str(brand.id), "version": 1,
                                           "ai_generated": item.ai_generated, "status": item.status.value},
                   workspace_id=a.workspace_id, actor=a.event_actor)
        await _compat.audit(db, a.audit_actor, "content.create", "content_item", item.id,
                            after={"title": item.title, "status": item.status.value})
        return await ContentService.get_item(db, a.workspace_id, item.id)

    @staticmethod
    async def list_items(db: AsyncSession, member: Any, *, brand_id: Any = None, status: list[str] | None = None,
                         pillar_id: Any = None, campaign_id: Any = None, platform: list[str] | None = None,
                         q: str | None = None, assignee: Any = None, ai_generated: bool | None = None,
                         limit: int = 50, cursor: str | None = None) -> tuple[list[ContentItem], str | None]:
        a = as_actor(member)
        stmt = select(ContentItem).where(ContentItem.workspace_id == a.workspace_id, ContentItem.deleted_at.is_(None))
        if brand_id:
            stmt = stmt.where(ContentItem.brand_id == _uuid(brand_id, "brand_id"))
        if status:
            stmt = stmt.where(ContentItem.status.in_([_enum(ContentStatus, s, "status") for s in status]))
        if pillar_id:
            stmt = stmt.where(ContentItem.pillar_id == _uuid(pillar_id, "pillar_id"))
        if campaign_id:
            stmt = stmt.where(ContentItem.campaign_id == _uuid(campaign_id, "campaign_id"))
        if assignee:
            stmt = stmt.where(ContentItem.assigned_to == _uuid(assignee, "assignee"))
        if ai_generated is not None:
            stmt = stmt.where(ContentItem.ai_generated.is_(ai_generated))
        if platform:
            plats = [_enum(Platform, p, "platform") for p in platform]
            stmt = stmt.where(ContentItem.id.in_(select(ContentVariant.content_item_id).where(
                ContentVariant.workspace_id == a.workspace_id, ContentVariant.platform.in_(plats))))
        if q:
            like = f"%{q}%"
            stmt = stmt.where(or_(ContentItem.title.ilike(like), cast(ContentItem.body, Text).ilike(like)))
        cur = _cursor(cursor)
        if cur:
            t = datetime.fromisoformat(cur["t"])
            stmt = stmt.where(or_(ContentItem.updated_at < t, and_(ContentItem.updated_at == t, ContentItem.id < UUID(cur["id"]))))
        stmt = stmt.order_by(ContentItem.updated_at.desc(), ContentItem.id.desc()).limit(limit + 1)
        rows = list((await db.execute(stmt)).scalars().all())
        nxt = None
        if len(rows) > limit:
            rows = rows[:limit]
            nxt = encode_cursor({"t": rows[-1].updated_at.isoformat(), "id": str(rows[-1].id)})
        return rows, nxt

    @staticmethod
    async def update_item(db: AsyncSession, member: Any, item_id: Any, patch: dict[str, Any], *,
                          diff_summary: str | None = None, ai_call_id: Any = None, replace_body: bool = False) -> ContentItem:
        a = as_actor(member)
        _require(a, EDIT_ROLES, "edit content")
        item = await ContentService.get_item(db, a.workspace_id, item_id, for_update=True)
        ContentService._assert_editable(item)
        before = item_snapshot(item)
        if "title" in patch and patch["title"] is not None:
            t = str(patch["title"]).strip()
            if not t:
                raise validation("Title is required")
            item.title = t
        if "content_type" in patch:
            item.content_type = _enum(ContentType, patch["content_type"], "content_type")
        if patch.get("master_format"):
            item.master_format = _enum(ContentFormat, patch["master_format"], "master_format")
        if patch.get("language"):
            item.language = patch["language"]
        refs = {k: patch[k] for k in ("pillar_id", "campaign_id") if k in patch}
        await ContentService._check_refs(db, a.workspace_id, item.brand_id, refs)
        for k, v in refs.items():
            setattr(item, k, _uuid(v, k))
        if "body" in patch and patch["body"] is not None:
            new_body = ContentService._normalize_body(patch["body"])
            item.body = new_body if replace_body else {**(item.body or {}), **new_body}
        if "assigned_to" in patch:
            item.assigned_to = _uuid(patch["assigned_to"], "assigned_to")
        after = item_snapshot(item)
        changed = [k for k in ITEM_FIELDS if before.get(k) != after.get(k)]
        if changed:
            item.current_version += 1
            if a.kind == "user" and item.ai_generated:
                gm = dict(item.generation_metadata or {})
                gm["human_edited"] = True
                item.generation_metadata = gm
            await ContentService._write_version(db, a.workspace_id, "item", item.id, item.current_version,
                                                item_snapshot(item), a.author, ai_call_id,
                                                diff_summary or f"updated {', '.join(changed)}")
            await emit(db, "CONTENT_UPDATED", {"content_item_id": str(item.id), "version": item.current_version,
                                               "fields": changed}, workspace_id=a.workspace_id, actor=a.event_actor)
        await db.flush()
        await _compat.audit(db, a.audit_actor, "content.update", "content_item", item.id, before=before,
                            after=item_snapshot(item))
        return await ContentService.get_item(db, a.workspace_id, item.id)

    @staticmethod
    async def delete_item(db: AsyncSession, member: Any, item_id: Any) -> None:
        a = as_actor(member)
        _require(a, EDIT_ROLES, "delete content")
        item = await ContentService.get_item(db, a.workspace_id, item_id, for_update=True)
        if await ContentService._live_schedules(db, a.workspace_id, item.id):
            raise conflict("live_schedules_exist", "Cancel the scheduled posts for this content before deleting it")
        item.deleted_at = datetime.now(UTC)
        await db.execute(sa_text("UPDATE approvals SET status='expired', decision_comment='content deleted' "
                                 "WHERE workspace_id=:ws AND target_id=:id AND status='pending'"),
                         {"ws": str(a.workspace_id), "id": str(item.id)})
        await db.flush()
        await _compat.audit(db, a.audit_actor, "content.delete", "content_item", item.id, before={"title": item.title,
                                                                                            "status": item.status.value})

    # ── status transitions ───────────────────────────────────────────────────────
    @staticmethod
    async def _set_status(db: AsyncSession, a: Actor, item: ContentItem, to: ContentStatus, comment: str | None,
                          reasons: list[Any] | None = None) -> None:
        frm = item.status
        if frm == to:
            return
        item.status = to
        for v in item.variants or []:
            v.status = to
        await db.flush()
        payload = {"id": str(item.id), "content_item_id": str(item.id), "brand_id": str(item.brand_id), "from": frm.value,
                   "to": to.value, "by": a.requested_by, "comment": comment}
        if reasons:
            payload["reasons"] = _jsonable(reasons)
        await emit(db, "CONTENT_STATUS_CHANGED", payload, workspace_id=a.workspace_id, actor=a.event_actor)
        await _compat.audit(db, a.audit_actor, "content.transition", "content_item", item.id, before={"status": frm.value},
                            after={"status": to.value, "comment": comment})
        if item.assigned_to and item.assigned_to != a.user_id:
            await _compat.notify(db, a.workspace_id, "content_status", f"'{item.title}' is now {to.value.replace('_', ' ')}",
                                 comment, f"/studio/{item.id}", user_id=item.assigned_to)

    @staticmethod
    async def transition(db: AsyncSession, member: Any, item_id: Any, to: Any, comment: str | None = None, *,
                         approval: Approval | None = None) -> ContentItem:
        """Guarded status change (doc 17). ``approval`` is passed when called from ApprovalService."""
        a = as_actor(member)
        to_s = _enum(ContentStatus, to, "to")
        item = await ContentService.get_item(db, a.workspace_id, item_id, for_update=True)
        frm = item.status
        if frm == to_s:
            return item
        if not is_known_transition(frm, to_s):
            raise conflict("invalid_transition", f"Cannot move content from {frm.value} to {to_s.value}")
        if a.kind != "system" and not can_transition(a.role, frm, to_s):
            raise forbidden(f"Role {a.role} cannot move content from {frm.value} to {to_s.value}")
        if a.kind == "agent" and to_s in (ContentStatus.approved, ContentStatus.rejected):
            raise forbidden("Agents cannot approve or reject content")
        if to_s == ContentStatus.approved:
            if item.risk_level == RiskLevel.high and a.role not in ADMIN_ROLES:
                raise forbidden("High-risk content requires admin or owner approval")
            if has_contradicted_claims(item.factcheck) or any(has_contradicted_claims(v.factcheck) for v in item.variants or []):
                raise conflict("contradicted_claims", "Fact-check found contradicted claims; edit the content before approving")
        if frm == ContentStatus.approved and to_s in (ContentStatus.draft, ContentStatus.archived):
            n = await ContentService._live_schedules(db, a.workspace_id, item.id)
            if n:
                raise conflict("live_schedules_exist",
                               f"{n} scheduled post(s) exist for this content; cancel them before moving it to {to_s.value}")
        await ContentService._set_status(db, a, item, to_s, comment)
        if approval is None:
            await ContentService._resolve_pending_approvals(db, a, item, to_s, comment)
        return await ContentService.get_item(db, a.workspace_id, item.id)

    @staticmethod
    async def _resolve_pending_approvals(db: AsyncSession, a: Actor, item: ContentItem, to: ContentStatus,
                                         comment: str | None) -> None:
        pend = (await db.execute(select(Approval).where(
            Approval.workspace_id == a.workspace_id, Approval.target_id == item.id, Approval.kind == "content",
            Approval.status == ApprovalStatus.pending))).scalars().all()
        now = datetime.now(UTC)
        for ap in pend:
            if to == ContentStatus.approved:
                ap.status = ApprovalStatus.approved
            elif to == ContentStatus.rejected:
                ap.status = ApprovalStatus.rejected
            elif to in (ContentStatus.draft, ContentStatus.archived):
                ap.status = ApprovalStatus.expired
            else:
                continue
            ap.decided_by = a.user_id
            ap.decided_at = now
            ap.decision_comment = comment or f"resolved by direct transition to {to.value}"
        await db.flush()

    @staticmethod
    async def request_approval(db: AsyncSession, member: Any, item_id: Any, comment: str | None = None, *,
                               expires_in_hours: int = 72) -> Approval:
        from app.services.approval_service import ApprovalService
        a = as_actor(member)
        _require(a, EDIT_ROLES, "request approval")
        item = await ContentService.get_item(db, a.workspace_id, item_id, for_update=True)
        existing = (await db.execute(select(Approval).where(
            Approval.workspace_id == a.workspace_id, Approval.target_id == item.id, Approval.kind == "content",
            Approval.status == ApprovalStatus.pending))).scalars().first()
        if existing is not None:
            return existing
        if item.status not in (ContentStatus.draft, ContentStatus.ai_generated, ContentStatus.needs_review):
            raise conflict("invalid_transition", f"Content in status {item.status.value} cannot be sent for approval")
        if item.status != ContentStatus.needs_review:
            if a.kind != "system" and not can_transition(a.role, item.status, ContentStatus.needs_review):
                raise forbidden("You cannot send this content for review")
            await ContentService._set_status(db, a, item, ContentStatus.needs_review, comment)
        high = item.risk_level == RiskLevel.high
        roles = ["admin", "owner"] if high else ["approver", "admin", "owner"]
        payload = {"title": item.title, "comment": comment, "risk_level": item.risk_level.value, "version": item.current_version,
                   "variant_ids": [str(v.id) for v in item.variants or []],
                   "platforms": sorted({v.platform.value for v in item.variants or []}),
                   "ai_generated": item.ai_generated}
        return await ApprovalService.create(db, a.workspace_id, item.brand_id, "content", "content_item", item.id, payload,
                                            a.requested_by, roles, expires_in_hours=expires_in_hours, actor=a)

    # ── variants ─────────────────────────────────────────────────────────────────
    @staticmethod
    async def _banned(db: AsyncSession, ws: UUID, brand_id: UUID) -> set[str]:
        return await HashtagService.banned_for(db, ws, brand_id)

    @staticmethod
    async def revalidate_variant(db: AsyncSession, v: ContentVariant, banned: set[str] | None = None) -> dict[str, Any]:
        await db.refresh(v, ["assets"])
        if banned is None:
            brand_id = (await db.execute(select(ContentItem.brand_id).where(ContentItem.id == v.content_item_id))).scalar_one()
            banned = await ContentService._banned(db, v.workspace_id, brand_id)
        data = {"text": v.text, "segments": v.segments, "hashtags": v.hashtags, "media_plan": v.media_plan,
                "platform_metadata": v.platform_metadata, "assets": _validation_assets(v)}
        v.validation = validate_variant(v.platform, v.format, data, banned_hashtags=banned)
        await db.flush()
        return v.validation

    @staticmethod
    async def _check_account(db: AsyncSession, ws: UUID, account_id: Any, platform: Platform) -> UUID | None:
        aid = _uuid(account_id, "social_account_id")
        if aid is None:
            return None
        acc = (await db.execute(select(SocialAccount).where(SocialAccount.id == aid, SocialAccount.workspace_id == ws))
               ).scalar_one_or_none()
        if acc is None:
            raise validation("Unknown social account", [{"code": "not_found", "field": "social_account_id", "message": str(aid)}])
        if acc.platform != platform:
            raise validation("Social account platform mismatch",
                             [{"code": "platform_mismatch", "field": "social_account_id",
                               "message": f"account is {acc.platform.value}, variant is {platform.value}"}])
        return aid

    @staticmethod
    def _variant_values(data: dict[str, Any]) -> dict[str, Any]:
        out: dict[str, Any] = {}
        if "text" in data:
            out["text"] = data["text"]
        if "segments" in data:
            out["segments"] = _jsonable(list(data["segments"] or []))
        if "hashtags" in data:
            out["hashtags"] = [str(h).strip().lstrip("#") for h in data["hashtags"] or [] if str(h).strip().lstrip("#")]
        if "media_plan" in data:
            out["media_plan"] = _jsonable(data["media_plan"] or {})
        if "platform_metadata" in data:
            out["platform_metadata"] = _jsonable(data["platform_metadata"] or {})
        if "changes_made" in data:
            out["changes_made"] = [str(c) for c in data["changes_made"] or []]
        return out

    @staticmethod
    async def create_variant(db: AsyncSession, member: Any, item_id: Any, data: dict[str, Any], *, ai_generated: bool = False,
                             generation_metadata: dict[str, Any] | None = None, ai_call_id: Any = None) -> ContentVariant:
        a = as_actor(member)
        _require(a, EDIT_ROLES, "create variants")
        item = await ContentService.get_item(db, a.workspace_id, item_id, for_update=True)
        ContentService._assert_editable(item)
        platform = _enum(Platform, data.get("platform"), "platform")
        fmt = _enum(ContentFormat, data.get("format"), "format")
        if platform is None or fmt is None:
            raise validation("platform and format are required")
        if not support_of(platform, fmt):
            raise validation(f"{platform.value} does not support the '{fmt.value}' format",
                             [{"code": "format_not_supported", "field": "format",
                               "message": f"{platform.value}/{fmt.value} is not supported"}])
        acc = await ContentService._check_account(db, a.workspace_id, data.get("social_account_id"), platform)
        vals = ContentService._variant_values(data)
        banned = await ContentService._banned(db, a.workspace_id, item.brand_id)
        is_ai = bool(ai_generated or a.kind == "agent")
        v = ContentVariant(workspace_id=a.workspace_id, content_item_id=item.id, platform=platform, format=fmt,
                           social_account_id=acc, status=item.status, current_version=1, ai_generated=is_ai,
                           generation_metadata=_jsonable(generation_metadata or {}),
                           **{k: vals.get(k, d) for k, d in (("text", None), ("segments", []), ("hashtags", []),
                                                            ("media_plan", {}), ("platform_metadata", {}),
                                                            ("changes_made", []))})
        v.validation = validate_variant(platform, fmt, {**vals, "assets": []}, banned_hashtags=banned)
        db.add(v)
        await db.flush()
        await ContentService._write_version(db, a.workspace_id, "variant", v.id, 1, variant_snapshot(v), a.author,
                                            ai_call_id, "created")
        await emit(db, "VARIANT_CREATED", {"variant_id": str(v.id), "content_item_id": str(item.id),
                                           "brand_id": str(item.brand_id), "platform": platform.value, "format": fmt.value,
                                           "ai_generated": is_ai, "validation_ok": v.validation.get("ok")},
                   workspace_id=a.workspace_id, actor=a.event_actor)
        await _compat.audit(db, a.audit_actor, "variant.create", "content_variant", v.id,
                            after={"platform": platform.value, "format": fmt.value, "content_item_id": str(item.id)})
        return await ContentService.get_variant(db, a.workspace_id, item.id, v.id)

    @staticmethod
    async def update_variant(db: AsyncSession, member: Any, item_id: Any, variant_id: Any, patch: dict[str, Any], *,
                             ai_call_id: Any = None, diff_summary: str | None = None,
                             generation_metadata: dict[str, Any] | None = None) -> ContentVariant:
        a = as_actor(member)
        _require(a, EDIT_ROLES, "edit variants")
        item = await ContentService.get_item(db, a.workspace_id, item_id, for_update=True)
        ContentService._assert_editable(item)
        v = await ContentService.get_variant(db, a.workspace_id, item.id, variant_id)
        before = variant_snapshot(v)
        vals = ContentService._variant_values(patch)
        if "social_account_id" in patch:
            vals["social_account_id"] = await ContentService._check_account(db, a.workspace_id, patch["social_account_id"],
                                                                            v.platform)
        changed = [k for k, val in vals.items() if getattr(v, k) != val]
        for k in changed:
            setattr(v, k, vals[k])
        if generation_metadata:
            v.generation_metadata = {**(v.generation_metadata or {}), **_jsonable(generation_metadata)}
        if a.kind == "agent":
            v.ai_generated = True
        if changed:
            v.current_version += 1
            if any(k in ("text", "segments", "hashtags") for k in changed):
                v.critique = None
                v.factcheck = None
            await ContentService._write_version(db, a.workspace_id, "variant", v.id, v.current_version, variant_snapshot(v),
                                                a.author, ai_call_id, diff_summary or f"updated {', '.join(changed)}")
            await emit(db, "CONTENT_UPDATED", {"content_item_id": str(item.id), "variant_id": str(v.id),
                                               "version": v.current_version, "fields": changed},
                       workspace_id=a.workspace_id, actor=a.event_actor)
        await ContentService.revalidate_variant(db, v)
        await _compat.audit(db, a.audit_actor, "variant.update", "content_variant", v.id, before=before, after=variant_snapshot(v))
        return await ContentService.get_variant(db, a.workspace_id, item.id, v.id)

    @staticmethod
    async def list_variants(db: AsyncSession, workspace_id: UUID, item_id: Any) -> list[ContentVariant]:
        item = await ContentService.get_item(db, workspace_id, item_id)
        return list(item.variants or [])

    # ── versions ─────────────────────────────────────────────────────────────────
    @staticmethod
    async def list_versions(db: AsyncSession, workspace_id: UUID, item_id: Any, target: str = "all") -> list[ContentVersion]:
        item = await ContentService.get_item(db, workspace_id, item_id, include_deleted=True)
        conds = []
        if target in ("all", "item"):
            conds.append(and_(ContentVersion.target_type == "item", ContentVersion.target_id == item.id))
        if target in ("all", "variant"):
            vids = [v.id for v in item.variants or []]
            if vids:
                conds.append(and_(ContentVersion.target_type == "variant", ContentVersion.target_id.in_(vids)))
        if not conds:
            return []
        q = (select(ContentVersion).where(ContentVersion.workspace_id == workspace_id, or_(*conds))
             .order_by(ContentVersion.created_at.desc(), ContentVersion.version.desc()))
        return list((await db.execute(q)).scalars().all())

    @staticmethod
    async def restore_version(db: AsyncSession, member: Any, item_id: Any, version: int, *,
                              variant_id: Any = None) -> ContentItem:
        a = as_actor(member)
        _require(a, EDIT_ROLES, "restore versions")
        item = await ContentService.get_item(db, a.workspace_id, item_id, for_update=True)
        ContentService._assert_editable(item)
        target_type, target_id = ("variant", _uuid(variant_id, "variant_id")) if variant_id else ("item", item.id)
        if target_type == "variant":
            await ContentService.get_variant(db, a.workspace_id, item.id, target_id)
        ver = (await db.execute(select(ContentVersion).where(
            ContentVersion.workspace_id == a.workspace_id, ContentVersion.target_type == target_type,
            ContentVersion.target_id == target_id, ContentVersion.version == version))).scalar_one_or_none()
        if ver is None:
            raise not_found("Version")
        snap = dict(ver.snapshot or {})
        if target_type == "variant":
            patch = {k: snap.get(k) for k in VARIANT_FIELDS if k in snap}
            await ContentService.update_variant(db, a, item.id, target_id, patch, diff_summary=f"restored v{version}")
        else:
            patch = {k: snap.get(k) for k in ITEM_FIELDS if k in snap}
            await ContentService.update_item(db, a, item.id, patch, diff_summary=f"restored v{version}", replace_body=True)
        return await ContentService.get_item(db, a.workspace_id, item.id)

    # ── sources ──────────────────────────────────────────────────────────────────
    @staticmethod
    async def attach_sources(db: AsyncSession, workspace_id: UUID, item_id: UUID,
                             sources: list[dict[str, Any]]) -> dict[str, Any]:
        wanted: list[tuple[UUID, str | None, str]] = []
        bad: list[str] = []
        for s in sources or []:
            sid = s.get("source_id") if isinstance(s, dict) else s
            try:
                uid = UUID(str(sid))
            except (TypeError, ValueError):
                bad.append(str(sid))
                continue
            claim = (s.get("claim") or s.get("claim_text")) if isinstance(s, dict) else None
            used = (s.get("used_for") if isinstance(s, dict) else None) or "claim"
            if used not in ("claim", "inspiration", "data"):
                used = "claim"
            wanted.append((uid, claim, used))
        if not wanted:
            return {"attached": 0, "skipped": bad}
        known = set((await db.execute(select(ResearchSource.id).where(
            ResearchSource.workspace_id == workspace_id, ResearchSource.id.in_([w[0] for w in wanted])))).scalars().all())
        n = 0
        for uid, claim, used in wanted:
            if uid not in known:
                bad.append(str(uid))
                continue
            res = await db.execute(pg_insert(ContentSource).values(content_item_id=item_id, source_id=uid, claim_text=claim,
                                                                   used_for=used).on_conflict_do_nothing())
            n += res.rowcount or 0
        await db.flush()
        return {"attached": n, "skipped": bad}

    # ── assets ───────────────────────────────────────────────────────────────────
    @staticmethod
    async def attach_asset(db: AsyncSession, member: Any, item_id: Any, media_asset_id: Any, *, variant_id: Any = None,
                           role: str = "primary", position: int | None = None, alt_text: str | None = None) -> ContentAsset:
        a = as_actor(member)
        _require(a, EDIT_ROLES, "attach media")
        item = await ContentService.get_item(db, a.workspace_id, item_id, for_update=True)
        ContentService._assert_editable(item)
        media = (await db.execute(select(MediaAsset).where(MediaAsset.id == _uuid(media_asset_id, "media_asset_id"),
                                                           MediaAsset.workspace_id == a.workspace_id,
                                                           MediaAsset.deleted_at.is_(None)))).scalar_one_or_none()
        if media is None:
            raise not_found("Media asset")
        if role not in ("primary", "carousel_slide", "thumbnail", "cover", "subtitle"):
            raise validation("Invalid role", [{"code": "invalid_enum", "field": "role", "message": role}])
        variant = await ContentService.get_variant(db, a.workspace_id, item.id, variant_id) if variant_id else None
        if position is None:
            cnt = select(func.count()).select_from(ContentAsset).where(ContentAsset.workspace_id == a.workspace_id,
                                                                       ContentAsset.content_item_id == item.id)
            cnt = cnt.where(ContentAsset.variant_id == variant.id) if variant else cnt.where(ContentAsset.variant_id.is_(None))
            position = int((await db.execute(cnt)).scalar() or 0)
        ca = ContentAsset(workspace_id=a.workspace_id, content_item_id=item.id, variant_id=variant.id if variant else None,
                          media_asset_id=media.id, role=role, position=position,
                          alt_text=alt_text if alt_text is not None else media.alt_text)
        db.add(ca)
        await db.flush()
        await db.refresh(ca, ["media"])
        if variant is not None:
            await ContentService.revalidate_variant(db, variant)
        await _compat.audit(db, a.audit_actor, "content.asset_attach", "content_item", item.id,
                            after={"content_asset_id": str(ca.id), "media_asset_id": str(media.id),
                                   "variant_id": str(variant.id) if variant else None, "role": role})
        return ca

    @staticmethod
    async def remove_asset(db: AsyncSession, member: Any, item_id: Any, asset_id: Any) -> None:
        a = as_actor(member)
        _require(a, EDIT_ROLES, "remove media")
        item = await ContentService.get_item(db, a.workspace_id, item_id, for_update=True)
        ContentService._assert_editable(item)
        aid = _uuid(asset_id, "asset_id")
        ca = (await db.execute(select(ContentAsset).where(
            ContentAsset.workspace_id == a.workspace_id,
            or_(ContentAsset.id == aid, ContentAsset.media_asset_id == aid),
            or_(ContentAsset.content_item_id == item.id,
                ContentAsset.variant_id.in_(select(ContentVariant.id).where(ContentVariant.content_item_id == item.id))))
        )).scalars().first()
        if ca is None:
            raise not_found("Content asset")
        vid = ca.variant_id
        await db.delete(ca)
        await db.flush()
        if vid:
            v = await ContentService.get_variant(db, a.workspace_id, item.id, vid)
            await ContentService.revalidate_variant(db, v)
        await _compat.audit(db, a.audit_actor, "content.asset_remove", "content_item", item.id,
                            before={"content_asset_id": str(ca.id), "media_asset_id": str(ca.media_asset_id)})

    @staticmethod
    async def reorder_assets(db: AsyncSession, member: Any, item_id: Any, ordered_ids: list[Any], *,
                             variant_id: Any = None) -> list[ContentAsset]:
        a = as_actor(member)
        _require(a, EDIT_ROLES, "reorder media")
        item = await ContentService.get_item(db, a.workspace_id, item_id, for_update=True)
        ContentService._assert_editable(item)
        q = select(ContentAsset).where(ContentAsset.workspace_id == a.workspace_id, ContentAsset.content_item_id == item.id)
        q = q.where(ContentAsset.variant_id == _uuid(variant_id, "variant_id")) if variant_id else q.where(
            ContentAsset.variant_id.is_(None))
        rows = {r.id: r for r in (await db.execute(q)).scalars().all()}
        order = [_uuid(x, "asset_id") for x in ordered_ids]
        if set(order) != set(rows):
            raise validation("ordered_ids must contain exactly the attached asset ids")
        for i, aid in enumerate(order):
            rows[aid].position = i
        await db.flush()
        if variant_id:
            v = await ContentService.get_variant(db, a.workspace_id, item.id, variant_id)
            await ContentService.revalidate_variant(db, v)
        await _compat.audit(db, a.audit_actor, "content.asset_reorder", "content_item", item.id,
                            after={"order": [str(x) for x in order]})
        return [rows[x] for x in order]

    # ── AI entry points (tool-mode runs) ─────────────────────────────────────────
    @staticmethod
    async def _run(db: AsyncSession, a: Actor, brand_id: UUID | None, agent: str, action: str, inputs: dict[str, Any],
                   message: str) -> dict[str, Any]:
        try:
            run = await _compat.create_ai_run(db, a.member if a.member is not None else a, message=message,
                                              brand_id=brand_id, agent=agent, action=action, inputs=_jsonable(inputs))
        except ImportError as e:
            raise ProblemError(501, "not_implemented", "AI is not available",
                               "The AI orchestrator is not installed in this build") from e
        run_id = getattr(run, "id", None) or (run.get("run_id") if isinstance(run, dict) else run)
        return {"run_id": run_id, "status": getattr(getattr(run, "status", None), "value", "queued"),
                "status_url": f"/api/v1/ai/runs/{run_id}"}

    @staticmethod
    async def generate(db: AsyncSession, member: Any, item_id: Any, req: dict[str, Any]) -> dict[str, Any]:
        a = as_actor(member)
        _require(a, EDIT_ROLES, "run AI")
        item = await ContentService.get_item(db, a.workspace_id, item_id)
        ContentService._assert_editable(item)
        mode = str(req.get("mode") or "write")
        if mode not in GENERATE_MODES:
            raise validation(f"Invalid mode {mode}")
        platform, fmt = req.get("platform"), req.get("format")
        if platform and fmt and not support_of(platform, fmt):
            raise validation(f"{platform} does not support {fmt}")
        inputs = {"content_id": item.id, "brand_id": item.brand_id, "mode": mode, "platform": platform,
                  "format": fmt or item.master_format, "instructions": req.get("instructions"),
                  "source_ids": req.get("source_ids") or [], "length": req.get("length"),
                  "content_type": item.content_type, "pillar_id": item.pillar_id, "idea_id": item.idea_id,
                  "title": item.title, "current_body": item.body}
        out = await ContentService._run(db, a, item.brand_id, "writer", GENERATE_MODES[mode], inputs,
                                        f"{mode} content: {item.title}")
        await ContentService._note_run(db, item, "writer", out["run_id"])
        return out

    @staticmethod
    async def repurpose(db: AsyncSession, member: Any, item_id: Any, targets: list[dict[str, Any]]) -> dict[str, Any]:
        a = as_actor(member)
        _require(a, EDIT_ROLES, "run AI")
        item = await ContentService.get_item(db, a.workspace_id, item_id)
        ContentService._assert_editable(item)
        if not targets:
            raise validation("At least one target is required")
        errs = [{"code": "format_not_supported", "field": f"targets[{i}]", "message": f"{t.get('platform')}/{t.get('format')}"}
                for i, t in enumerate(targets) if not support_of(t.get("platform"), t.get("format"))]
        if errs:
            raise validation("Unsupported repurpose targets", errs)
        run_ids = []
        for t in targets:
            inputs = {"content_id": item.id, "brand_id": item.brand_id, "target_platform": t["platform"],
                      "platform": t["platform"], "format": t["format"], "social_account_id": t.get("social_account_id")}
            out = await ContentService._run(db, a, item.brand_id, "repurposer", "adapt", inputs,
                                            f"Adapt '{item.title}' for {_jsonable(t['platform'])} {_jsonable(t['format'])}")
            run_ids.append(out["run_id"])
        await ContentService._note_run(db, item, "repurposer", run_ids[0])
        return {"run_id": run_ids[0], "run_ids": run_ids, "status": "queued", "status_url": f"/api/v1/ai/runs/{run_ids[0]}"}

    @staticmethod
    async def critique(db: AsyncSession, member: Any, item_id: Any, variant_id: Any = None) -> dict[str, Any]:
        a = as_actor(member)
        _require(a, EDIT_ROLES, "run AI")
        item = await ContentService.get_item(db, a.workspace_id, item_id)
        if variant_id:
            await ContentService.get_variant(db, a.workspace_id, item.id, variant_id)
        inputs = {"content_id": item.id, "variant_id": variant_id, "brand_id": item.brand_id,
                  "target_type": "variant" if variant_id else "item", "target_id": variant_id or item.id}
        out = await ContentService._run(db, a, item.brand_id, "critic", "critique", inputs, f"Critique: {item.title}")
        await ContentService._note_run(db, item, "critic", out["run_id"])
        return out

    @staticmethod
    async def fact_check(db: AsyncSession, member: Any, item_id: Any, variant_id: Any = None) -> dict[str, Any]:
        a = as_actor(member)
        _require(a, EDIT_ROLES, "run AI")
        item = await ContentService.get_item(db, a.workspace_id, item_id)
        text = item_text(item)
        if variant_id:
            v = await ContentService.get_variant(db, a.workspace_id, item.id, variant_id)
            text = variant_text(v)
        inputs = {"content_id": item.id, "variant_id": variant_id, "brand_id": item.brand_id,
                  "target_type": "variant" if variant_id else "item", "target_id": variant_id or item.id,
                  "claims": extract_claims(text), "source_ids": [str(s.source_id) for s in item.sources or []]}
        out = await ContentService._run(db, a, item.brand_id, "fact_check", "check", inputs, f"Fact-check: {item.title}")
        await ContentService._note_run(db, item, "fact_check", out["run_id"])
        return out

    @staticmethod
    async def _note_run(db: AsyncSession, item: ContentItem, agent: str, run_id: Any) -> None:
        gm = dict(item.generation_metadata or {})
        runs = dict(gm.get("pending_runs") or {})
        runs[agent] = str(run_id)
        gm["pending_runs"] = runs
        item.generation_metadata = gm
        await db.flush()

    # ── after-generation hook (called by agent tools) ────────────────────────────
    @staticmethod
    async def apply_agent_output(db: AsyncSession, item_id: Any, agent_id: str, output: dict[str, Any], *,
                                 workspace_id: UUID | None = None, actor: Any = None, variant_id: Any = None,
                                 run_id: Any = None, ai_call_id: Any = None) -> dict[str, Any]:
        """Persist an agent's structured output and route status per doc 19 §19.7.

        writer → item body + version (author agent) + sources, status ``ai_generated``; repurposer → variant;
        critic → critique; fact_check → factcheck. After critic/fact-check the risk level is recomputed and the item
        moves ``ai_generated → needs_review`` once the review passes are complete (``rejected`` when the deterministic
        policy blocks it). Never ``approved``.
        """
        agent = (agent_id or "").replace("agent:", "")
        if actor is None:
            if workspace_id is None:
                raise ValueError("workspace_id or actor required")
            a = Actor(workspace_id=workspace_id, user_id=None, role="editor", kind="agent", agent_id=agent)
        else:
            a = as_actor(actor)
            if a.kind == "user":
                a = Actor(workspace_id=a.workspace_id, user_id=a.user_id, role=a.role, kind="agent", agent_id=agent,
                          member=a.member)
        ws = a.workspace_id
        item = await ContentService.get_item(db, ws, item_id, for_update=True)
        meta = _jsonable({"run_id": run_id, "ai_call_id": ai_call_id, "agent": agent})
        result: dict[str, Any] = {"content_id": str(item.id)}

        if agent == "writer":
            ContentService._assert_editable(item)
            out = dict(output or {})
            body = {k: out[k] for k in BODY_KEYS if k in out and out[k] is not None}
            if "body" in out and "body_md" not in body and isinstance(out["body"], str):
                body["body_md"] = out["body"]
            item.body = {**(item.body or {}), **_jsonable(body)}
            if out.get("title"):
                item.title = str(out["title"]).strip()[:500]
            if out.get("content_type"):
                item.content_type = _enum(ContentType, out["content_type"], "content_type")
            gm = {**(item.generation_metadata or {}), **_jsonable(out.get("generation_metadata") or {}), **meta}
            pending = dict(gm.get("pending_runs") or {})
            pending.pop("writer", None)
            gm["pending_runs"] = pending
            if out.get("confidence") is not None:
                gm["writer_confidence"] = out["confidence"]
            item.generation_metadata = gm
            item.ai_generated = True
            item.critique = None
            item.factcheck = None
            item.current_version += 1
            await ContentService._write_version(db, ws, "item", item.id, item.current_version, item_snapshot(item),
                                                ("agent", agent), ai_call_id, "AI draft")
            if out.get("sources"):
                result["sources"] = await ContentService.attach_sources(db, ws, item.id, out["sources"])
            await emit(db, "CONTENT_UPDATED", {"content_item_id": str(item.id), "version": item.current_version,
                                               "fields": sorted(body), "ai_generated": True}, workspace_id=ws,
                       actor=a.event_actor)
            plat, fmt = out.get("platform"), out.get("format")
            if plat and fmt and support_of(plat, fmt):
                vdata = {"platform": plat, "format": fmt, "text": out.get("text") or ContentService._compose_post(body),
                         "segments": out.get("segments") or [], "hashtags": body.get("hashtags") or [],
                         "platform_metadata": out.get("platform_metadata") or {}, "media_plan": out.get("media_plan") or {}}
                existing = next((v for v in item.variants or []
                                 if v.platform.value == str(_jsonable(plat)) and v.format.value == str(_jsonable(fmt))), None)
                if existing:
                    v = await ContentService.update_variant(db, a, item.id, existing.id, vdata, ai_call_id=ai_call_id,
                                                            diff_summary="AI draft", generation_metadata=meta)
                else:
                    v = await ContentService.create_variant(db, a, item.id, vdata, ai_generated=True,
                                                            generation_metadata=meta, ai_call_id=ai_call_id)
                result["variant_id"] = str(v.id)
                result["validation"] = v.validation
            item = await ContentService.get_item(db, ws, item.id, for_update=True)
            if item.status != ContentStatus.ai_generated:
                # AI changed the content: it must be reviewed again; open approvals are superseded
                await ContentService._set_status(db, a, item, ContentStatus.ai_generated, "AI draft saved")
                await ContentService._resolve_pending_approvals(db, a, item, ContentStatus.draft, "superseded by AI draft")
            await ContentService._route(db, a, item, after="writer")

        elif agent == "repurposer":
            out = dict(output or {})
            vdata = {k: out[k] for k in ("platform", "format", "text", "segments", "hashtags", "media_plan",
                                         "platform_metadata", "changes_made", "social_account_id") if k in out}
            if "metadata" in out and "platform_metadata" not in vdata:
                vdata["platform_metadata"] = out["metadata"]
            if variant_id:
                v = await ContentService.update_variant(db, a, item.id, variant_id, vdata, ai_call_id=ai_call_id,
                                                        diff_summary="AI adaptation", generation_metadata=meta)
            else:
                v = await ContentService.create_variant(db, a, item.id, vdata, ai_generated=True,
                                                        generation_metadata={**meta, **_jsonable(out.get("generation_metadata") or {})},
                                                        ai_call_id=ai_call_id)
            result.update({"variant_id": str(v.id), "validation": v.validation})
            item = await ContentService.get_item(db, ws, item.id, for_update=True)
            await ContentService._route(db, a, item, after="repurposer")

        elif agent in ("critic", "fact_check", "factcheck"):
            key = "critique" if agent == "critic" else "factcheck"
            payload = {**_jsonable(output or {}), "at": datetime.now(UTC).isoformat(), **meta}
            if variant_id:
                v = await ContentService.get_variant(db, ws, item.id, variant_id)
                payload["at_version"] = v.current_version
                setattr(v, key, payload)
                result["variant_id"] = str(v.id)
            else:
                payload["at_version"] = item.current_version
                setattr(item, key, payload)
            await db.flush()
            await _compat.audit(db, a.audit_actor, f"content.{key}_saved", "content_item", item.id,
                                after={"target": "variant" if variant_id else "item"})
            item = await ContentService.get_item(db, ws, item.id, for_update=True)
            await ContentService._route(db, a, item, after=key)
        else:
            raise validation(f"Unknown agent output '{agent_id}'")

        item = await ContentService.get_item(db, ws, item.id)
        result.update({"status": item.status.value, "risk_level": item.risk_level.value, "version": item.current_version})
        return result

    @staticmethod
    def _compose_post(body: dict[str, Any]) -> str:
        parts = [body.get("hook"), body.get("body_md"), body.get("cta")]
        return "\n\n".join(str(p).strip() for p in parts if p and str(p).strip())

    @staticmethod
    async def _route(db: AsyncSession, a: Actor, item: ContentItem, *, after: str) -> None:
        """Risk scoring + status routing (doc 19 §19.7)."""
        brand = (await db.execute(select(Brand).where(Brand.id == item.brand_id))).scalar_one()
        pol = policies_from_brand_settings(brand.settings)
        text = item_text(item)
        policy = policy_check(text, pol)
        critiques = [c for c in [item.critique, *[v.critique for v in item.variants or []]] if c]
        factchecks = [f for f in [item.factcheck, *[v.factcheck for v in item.variants or []]] if f]
        compliance = pol.get("compliance_tags") or []
        levels = [risk_from(c, None, policy, compliance) for c in critiques] or [risk_from(None, None, policy, compliance)]
        levels += [risk_from(None, f, policy, compliance) for f in factchecks]
        rank = {"low": 0, "medium": 1, "high": 2}
        risk = max(levels, key=lambda r: rank[r])
        prev_risk = item.risk_level
        item.risk_level = RiskLevel(risk)
        gm = dict(item.generation_metadata or {})
        gm["policy"] = {"risk": policy["risk"], "blocked": policy["blocked"], "categories": policy["categories"],
                        "flags": policy["flags"][:20]}
        gm["confidence"] = ContentService._confidence(item, critiques, factchecks, policy, text)
        item.generation_metadata = gm
        await db.flush()
        if policy["blocked"] and item.status in (ContentStatus.ai_generated, ContentStatus.needs_review, ContentStatus.draft):
            reasons = [f["message"] for f in policy["flags"] if f["severity"] == "block"]
            await ContentService._set_status(db, Actor(a.workspace_id, a.user_id, a.role, "agent", a.agent_id, a.member),
                                             item, ContentStatus.rejected, "Blocked by content policy", reasons)
            await ContentService._resolve_pending_approvals(db, a, item, ContentStatus.rejected, "Blocked by content policy")
            return
        if item.status == ContentStatus.ai_generated and after in ("critique", "factcheck"):
            fc_needed = bool(extract_claims(text)) or bool(compliance)
            if critiques and (factchecks or not fc_needed):
                await ContentService._set_status(db, a, item, ContentStatus.needs_review,
                                                 f"AI review complete (risk {risk})")
        if item.risk_level == RiskLevel.high and prev_risk != RiskLevel.high:
            pend = (await db.execute(select(Approval).where(
                Approval.workspace_id == a.workspace_id, Approval.target_id == item.id, Approval.kind == "content",
                Approval.status == ApprovalStatus.pending))).scalars().all()
            from app.models.enums import MemberRole
            for ap in pend:
                ap.required_roles = [MemberRole.admin, MemberRole.owner]
                ap.payload = {**(ap.payload or {}), "risk_level": "high"}
            await db.flush()

    @staticmethod
    def _confidence(item: ContentItem, critiques: list[dict[str, Any]], factchecks: list[dict[str, Any]],
                    policy: dict[str, Any], text: str) -> float:
        from app.content.policy import _unit
        comps: list[float] = []
        claims = extract_claims(text)
        if claims:
            sourced = len([s for s in item.sources or [] if s.used_for in ("claim", "data")])
            comps.append(min(1.0, sourced / len(claims)))
        verdicts = [str(c.get("verdict", "")).lower() for f in factchecks for c in (f.get("claims") or []) if isinstance(c, dict)]
        if verdicts:
            comps.append(sum(1 for v in verdicts if v in ("supported", "opinion")) / len(verdicts))
        quals = [_unit((c.get("scores") or {}).get("quality")) for c in critiques if isinstance(c.get("scores"), dict)]
        quals = [q for q in quals if q is not None]
        if quals:
            comps.append(sum(quals) / len(quals))
        comps.append(0.0 if "injection" in policy.get("categories", []) else 1.0)
        return round(sum(comps) / len(comps), 3)


# Event consumers (VARIANT_CREATED → critic auto-pass, CONTENT_APPROVED → content memory) register on import.
with contextlib.suppress(ImportError):
    import app.events.consumers_content  # noqa: E402,F401

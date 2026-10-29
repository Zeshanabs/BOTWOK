"""BrandService: brands, brand_settings sections, content pillars, brand assets, and the BrandContext block.

`build_context()` renders the deterministic BrandContext (doc 09 §9.1.2) every agent receives. The renderer itself is the
pure function `render_brand_context()` so it can be unit-tested without a database.
"""
from __future__ import annotations

import copy
import hashlib
import json
import math
import re
import unicodedata
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any, Literal, Protocol
from uuid import UUID

from pydantic import BaseModel, ValidationError
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import ProblemError, conflict, not_found, validation
from app.core.logging import get_logger
from app.core.redis import get_redis
from app.models.brand import Brand, BrandAsset, BrandSettings, ContentPillar
from app.models.content import MediaAsset
from app.schemas.brand import (
    BRAND_FIELDS,
    DEFAULT_PILLARS,
    SECTION_MODELS,
    SECTION_NAMES,
    BrandAssetCreate,
    BrandCreate,
    BrandOut,
    BrandSettingsUpdate,
    BrandUpdate,
    PillarCreate,
    PillarOut,
    PillarUpdate,
)

log = get_logger("brand")

ContextMode = Literal["compact", "full"]
CONTEXT_TTL_S = 600
PLATFORM_ORDER = ("linkedin", "instagram", "facebook", "x", "threads", "tiktok", "youtube", "pinterest", "gbp")
TONE_KEYS = ("formal", "playful", "concise", "bold")


class MemberLike(Protocol):
    """Anything with a workspace and a user (api.deps.Member, or a job/tool actor)."""
    workspace_id: UUID


def actor_user_id(member: Any) -> UUID | None:
    user = getattr(member, "user", None)
    if user is not None and getattr(user, "id", None) is not None:
        return user.id
    uid = getattr(member, "user_id", None)
    return UUID(str(uid)) if uid else None


def actor_dict(member: Any) -> dict[str, Any]:
    """Event/audit actor: agent (tool calls) > user > system."""
    uid = actor_user_id(member)
    agent = getattr(member, "agent_id", None)
    if agent:
        return {"type": "agent", "id": str(agent), **({"user_id": str(uid)} if uid else {})}
    return {"type": "user", "id": str(uid)} if uid else {"type": "system"}


async def safe_audit(db: AsyncSession, member: Any, action: str, target_type: str, target_id: Any,
                     before: dict[str, Any] | None = None, after: dict[str, Any] | None = None) -> None:
    """Write an audit entry via identity's audit_service when it exists; no-op otherwise.
    Members (with `.user`) are passed through; job/tool actors become {"type", "id", "workspace_id"} dicts."""
    if member is None:
        return
    try:
        from app.services.audit_service import audit
    except ImportError:
        return
    actor: Any = member
    if getattr(member, "user", None) is None:
        actor = {**actor_dict(member), "workspace_id": str(getattr(member, "workspace_id", "") or "") or None}
        actor.setdefault("id", "system")
    await audit(db, actor, action, target_type, str(target_id) if target_id is not None else None, before=before,
                after=after)


# ====================================================================== pure helpers
def slugify(value: str, max_len: int = 60) -> str:
    v = unicodedata.normalize("NFKD", value).encode("ascii", "ignore").decode()
    v = re.sub(r"[^a-zA-Z0-9]+", "-", v).strip("-").lower()
    return (v[:max_len].strip("-")) or "brand"


def estimate_tokens(text: str) -> int:
    """Cheap provider-agnostic estimate (~4 chars/token)."""
    return math.ceil(len(text) / 4) if text else 0


def _json_default(o: Any) -> Any:
    if isinstance(o, (UUID, datetime)):
        return str(o)
    if isinstance(o, Decimal):
        return float(o)
    return str(o)


def compute_context_cache_key(brand: dict[str, Any], sections: dict[str, Any], pillars: list[dict[str, Any]]) -> str:
    """sha256 over every settings section (+ the brand fields and pillars that the context renders)."""
    payload = {"sections": {k: sections.get(k) or {} for k in SECTION_NAMES},
               "brand": {k: brand.get(k) for k in ("name", *BRAND_FIELDS)},
               "pillars": [{k: p.get(k) for k in ("name", "share_target", "status", "position", "description", "examples")}
                           for p in pillars]}
    blob = json.dumps(payload, sort_keys=True, default=_json_default, ensure_ascii=False)
    return hashlib.sha256(blob.encode()).hexdigest()


def _clean(items: Any) -> list[str]:
    out: list[str] = []
    for x in items or []:
        s = str(x).strip() if x is not None else ""
        if s and s not in out:
            out.append(s)
    return out


def _cap(items: list[Any], n: int | None) -> list[Any]:
    return items if n is None else items[:n]


def _pct(share: Any) -> str | None:
    if share is None:
        return None
    return f"{round(float(share) * 100)}%"


def _quote(items: list[str]) -> str:
    return ", ".join(f'"{x}"' for x in items)


def _brand_line(brand: dict[str, Any]) -> str:
    parts: list[str] = []
    industry = " ".join(_clean([brand.get("industry"), brand.get("sub_industry")]))
    if industry:
        parts.append(industry)
    geo = _clean(brand.get("geography"))
    if geo:
        parts.append("/".join(geo))
    langs = [lang.upper() for lang in _clean(brand.get("languages"))]
    if langs:
        parts.append("/".join(langs))
    return f"BRAND: {brand.get('name') or 'Unnamed brand'}" + (f" ({', '.join(parts)})" if parts else "")


def _audience_line(aud: dict[str, Any], full: bool) -> str | None:
    parts: list[str] = []
    personas = [p for p in aud.get("personas") or [] if isinstance(p, dict)]
    if aud.get("summary"):
        parts.append(str(aud["summary"]).strip())
    elif personas:
        parts.append(", ".join(f"{p.get('name')}" + (f" ({p['role']})" if p.get("role") else "") for p in personas))
    if aud.get("market"):
        parts.append(str(aud["market"]).upper())
    if aud.get("demographics") and full:
        parts.append(str(aud["demographics"]))
    geo = _clean(aud.get("geography"))
    if geo:
        parts.append("in " + ", ".join(geo))
    pains = _cap(_clean(x for p in personas for x in p.get("pains") or []), None if full else 5)
    if pains:
        parts.append("pains: " + ", ".join(pains))
    goals = _cap(_clean(x for p in personas for x in p.get("goals") or []), None if full else 3)
    if goals:
        parts.append("goals: " + ", ".join(goals))
    return "AUDIENCE: " + "; ".join(parts) if parts else None


def _voice_line(voice: dict[str, Any], full: bool) -> str | None:
    parts: list[str] = []
    tone = voice.get("tone") or {}
    sliders = [f"{k} {tone[k]}" for k in TONE_KEYS if tone.get(k) is not None]
    if sliders:
        parts.append(" / ".join(sliders))
    person = voice.get("person")
    if person:
        parts.append(f"{'I' if person == 'i' else person}-voice")
    if voice.get("emoji_policy"):
        parts.append(str(voice["emoji_policy"]).strip())
    if voice.get("humor_policy"):
        parts.append(f"humor: {str(voice['humor_policy']).strip()}")
    if voice.get("reading_level") is not None:
        parts.append(f"reading level {voice['reading_level']}")
    preferred = _cap(_clean((voice.get("vocabulary") or {}).get("preferred")), None if full else 8)
    if preferred:
        parts.append("prefer " + _quote(preferred))
    return "VOICE: " + "; ".join(parts) if parts else None


def _rules_line(voice: dict[str, Any], policies: dict[str, Any], full: bool) -> str | None:
    parts: list[str] = []
    if policies.get("claims_policy"):
        parts.append(str(policies["claims_policy"]).strip())
    parts.extend(_cap(_clean(voice.get("style_rules")), None if full else 8))
    forbidden = _clean(policies.get("forbidden_topics"))
    if forbidden:
        parts.append("never discuss " + ", ".join(forbidden))
    for st in policies.get("sensitive_topics") or []:
        if isinstance(st, dict) and st.get("topic"):
            parts.append(f"{st['topic']}: {st['handling']}" if st.get("handling") else f"handle {st['topic']} with care")
    avoid = _clean((voice.get("vocabulary") or {}).get("avoid"))
    if avoid:
        parts.append("avoid " + _quote(avoid))
    for d in _clean(policies.get("legal_disclaimers")):
        parts.append(f'disclaimer "{d}"')
    tags = _clean(policies.get("compliance_tags"))
    if tags:
        parts.append("compliance: " + ", ".join(tags))
    return "RULES: " + "; ".join(parts) if parts else None


def _active_pillars(pillars: list[dict[str, Any]]) -> list[dict[str, Any]]:
    act = [p for p in pillars if (p.get("status") or "active") == "active" and p.get("name")]
    return sorted(act, key=lambda p: (p.get("position") or 0, str(p.get("name"))))


def _pillars_line(pillars: list[dict[str, Any]]) -> str | None:
    items = []
    for p in _active_pillars(pillars):
        pct = _pct(p.get("share_target"))
        items.append(f"{p['name']} {pct}" if pct else str(p["name"]))
    return "PILLARS: " + " · ".join(items) if items else None


def _hashtags_line(topics: dict[str, Any], full: bool) -> str | None:
    tags = topics.get("hashtags") or {}
    segs = []
    for key, n in (("core", 10), ("campaign", 6), ("banned", None)):
        vals = _cap([t if t.startswith("#") else f"#{t}" for t in _clean(tags.get(key))], None if full else n)
        if vals:
            segs.append(f"{key}: {' '.join(vals)}")
    return "HASHTAGS " + "; ".join(segs) if segs else None


def _ctas_line(topics: dict[str, Any], full: bool) -> str | None:
    items = []
    for c in _cap([c for c in topics.get("ctas") or [] if isinstance(c, dict) and c.get("text")], None if full else 4):
        s = f'"{c["text"]}"'
        if c.get("goal"):
            s += f" ({c['goal']})"
        if full and c.get("url"):
            s += f" → {c['url']}"
        items.append(s)
    return "CTAS: " + " · ".join(items) if items else None


def _visual_line(visual: dict[str, Any], full: bool) -> str | None:
    parts: list[str] = []
    colors = visual.get("colors") or {}
    cols = [f"{role} {colors[role]}" for role in ("primary", "secondary", "accent") if colors.get(role)]
    neutral = _clean(colors.get("neutral"))
    if neutral:
        cols.append("neutral " + "/".join(neutral))
    if cols:
        parts.append(", ".join(cols))
    fonts = visual.get("fonts") or {}
    font_names = _clean([fonts.get("heading"), fonts.get("body")])
    if font_names:
        parts.append(" / ".join(font_names))
    if visual.get("imagery_style"):
        parts.append(str(visual["imagery_style"]).strip())
    dos = _cap(_clean(visual.get("dos")), None if full else 5)
    if dos:
        parts.append("do: " + ", ".join(dos))
    donts = _cap(_clean(visual.get("donts")), None if full else 5)
    if donts:
        parts.append("don't: " + ", ".join(donts))
    return "VISUAL: " + "; ".join(parts) if parts else None


def _platforms_line(platforms: dict[str, Any], full: bool) -> str | None:
    items = []
    for code in PLATFORM_ORDER:
        d = platforms.get(code)
        if not isinstance(d, dict) or d.get("enabled") is False:
            continue
        s = code
        if d.get("cadence_per_week") is not None:
            s += f" {d['cadence_per_week']}/wk"
        formats = _clean(f.value if hasattr(f, "value") else f for f in d.get("formats") or [])
        if formats:
            s += " " + "/".join(formats)
        extras = []
        if d.get("notes"):
            extras.append(str(d["notes"]))
        if full:
            if d.get("tone_adjustments"):
                extras.append(f"tone: {d['tone_adjustments']}")
            if d.get("hashtag_count") is not None:
                extras.append(f"{d['hashtag_count']} hashtags")
            if d.get("link_policy"):
                extras.append(f"links: {d['link_policy']}")
            if d.get("signature"):
                extras.append(f'signature "{d["signature"]}"')
        if extras:
            s += f" ({', '.join(extras)})"
        items.append(s)
    return "PLATFORMS: " + "; ".join(items) if items else None


def _goals_line(goals: dict[str, Any], full: bool) -> str | None:
    parts: list[str] = []
    for o in goals.get("objectives") or []:
        if not isinstance(o, dict) or not o.get("name"):
            continue
        target = o.get("target")
        if isinstance(target, float) and target.is_integer():
            target = int(target)
        s = f"{target} {o['name']}" if target not in (None, "") else str(o["name"])
        if o.get("by"):
            s += f" by {o['by']}"
        if full and o.get("metric"):
            s += f" [{o['metric']}]"
        parts.append(s)
    prio = _clean(p.value if hasattr(p, "value") else p for p in goals.get("priority_platforms") or [])
    if prio:
        parts.append("priority: " + ", ".join(prio))
    if goals.get("funnel_focus"):
        parts.append(f"funnel: {goals['funnel_focus']}")
    return "GOALS: " + "; ".join(parts) if parts else None


def _full_extras(brand: dict[str, Any], s: dict[str, Any], pillars: list[dict[str, Any]]) -> list[str]:
    lines: list[str] = []
    if brand.get("description"):
        lines.append(f"DESCRIPTION: {str(brand['description']).strip()}")
    if brand.get("website"):
        lines.append(f"WEBSITE: {brand['website']}")
    topics = s.get("topics") or {}
    if _clean(topics.get("preferred_topics")):
        lines.append("TOPICS: " + ", ".join(_clean(topics.get("preferred_topics"))))
    if _clean(topics.get("keywords")):
        lines.append("KEYWORDS: " + ", ".join(_clean(topics.get("keywords"))))
    off = s.get("offering") or {}
    off_parts: list[str] = []
    if _clean(off.get("services")):
        off_parts.append("services: " + ", ".join(_clean(off.get("services"))))
    prods = []
    for p in off.get("products") or []:
        if isinstance(p, dict) and p.get("name"):
            ps = str(p["name"]) + (f" ({p['price_hint']})" if p.get("price_hint") else "")
            if p.get("description"):
                ps += f" — {p['description']}"
            prods.append(ps)
    if prods:
        off_parts.append("products: " + "; ".join(prods))
    if _clean(off.get("differentiators")):
        off_parts.append("differentiators: " + ", ".join(_clean(off.get("differentiators"))))
    if _clean(off.get("proof_points")):
        off_parts.append("proof: " + ", ".join(_clean(off.get("proof_points"))))
    if off_parts:
        lines.append("OFFERING: " + "; ".join(off_parts))
    personas = [p for p in (s.get("audience") or {}).get("personas") or [] if isinstance(p, dict) and p.get("name")]
    if personas:
        lines.append("PERSONAS:")
        for p in personas:
            head = f"- {p['name']}" + (f" ({p['role']})" if p.get("role") else "")
            segs = [f"{k}: {', '.join(_clean(p.get(k)))}" for k in ("pains", "goals", "objections", "channels")
                    if _clean(p.get(k))]
            lines.append(head + (": " + "; ".join(segs) if segs else ""))
    detailed = [p for p in _active_pillars(pillars) if p.get("description") or p.get("examples")]
    if detailed:
        lines.append("PILLAR DETAIL:")
        for p in detailed:
            pct = _pct(p.get("share_target"))
            s_ = f"- {p['name']}" + (f" ({pct})" if pct else "")
            if p.get("description"):
                s_ += f": {p['description']}"
            if _clean(p.get("examples")):
                s_ += " e.g. " + "; ".join(_clean(p.get("examples")))
            lines.append(s_)
    samples = [w for w in (s.get("voice") or {}).get("writing_samples") or [] if isinstance(w, dict) and w.get("text")]
    if samples:
        lines.append("WRITING SAMPLES:")
        for w in samples:
            text = " ".join(str(w["text"]).split())
            lines.append(f'- "{text}"' + (f" — {w['note']}" if w.get("note") else ""))
    return lines


def render_brand_context(brand: dict[str, Any], settings: dict[str, Any], pillars: list[dict[str, Any]],
                         mode: ContextMode = "compact") -> str:
    """Deterministic BrandContext block (doc 09 §9.1.2). Same inputs → byte-identical output.

    Lines (omitted when empty): BRAND, AUDIENCE, VOICE, RULES, PILLARS, HASHTAGS, CTAS, VISUAL, PLATFORMS, GOALS.
    `full` lifts list caps and appends DESCRIPTION/WEBSITE/TOPICS/KEYWORDS/OFFERING/PERSONAS/PILLAR DETAIL/WRITING SAMPLES.
    """
    if mode not in ("compact", "full"):
        raise ValueError("mode must be 'compact' or 'full'")
    full = mode == "full"
    s = {k: (settings.get(k) or {}) for k in SECTION_NAMES}
    lines = [
        _brand_line(brand),
        _audience_line(s["audience"], full),
        _voice_line(s["voice"], full),
        _rules_line(s["voice"], s["policies"], full),
        _pillars_line(pillars),
        _hashtags_line(s["topics"], full),
        _ctas_line(s["topics"], full),
        _visual_line(s["visual"], full),
        _platforms_line(s["platforms"], full),
        _goals_line(s["goals"], full),
    ]
    out = [line for line in lines if line]
    if full:
        out.extend(_full_extras(brand, s, pillars))
    return "\n".join(out)


def brand_to_dict(brand: Brand) -> dict[str, Any]:
    return {"id": str(brand.id), "name": brand.name, "slug": brand.slug, "description": brand.description,
            "industry": brand.industry, "sub_industry": brand.sub_industry, "website": brand.website,
            "geography": list(brand.geography or []), "languages": list(brand.languages or []),
            "timezone": brand.timezone}


def settings_to_dict(row: BrandSettings | None) -> dict[str, Any]:
    if row is None:
        return {k: {} for k in SECTION_NAMES}
    return {k: copy.deepcopy(getattr(row, k) or {}) for k in SECTION_NAMES}


def pillar_to_dict(p: ContentPillar) -> dict[str, Any]:
    return {"id": str(p.id), "name": p.name, "description": p.description,
            "share_target": float(p.share_target) if p.share_target is not None else None, "color": p.color,
            "examples": list(p.examples or []), "position": p.position, "status": p.status}


def validate_section(name: str, data: dict[str, Any]) -> dict[str, Any]:
    """Validate one settings section and return its canonical JSON form."""
    model = SECTION_MODELS[name]
    try:
        obj = model.model_validate(data)
    except ValidationError as e:
        raise validation(f"Invalid brand settings section '{name}'",
                         [{"code": err.get("type"), "field": ".".join([name, *(str(x) for x in err.get("loc", []))]),
                           "message": err.get("msg")} for err in e.errors()]) from e
    return obj.model_dump(mode="json", exclude_none=True)


def deep_merge(current: dict[str, Any], patch: dict[str, Any]) -> dict[str, Any]:
    """Recursive dict merge: nested objects merge key-wise, lists/scalars (incl. explicit null) replace."""
    out = copy.deepcopy(current)
    for key, value in patch.items():
        if isinstance(value, dict) and isinstance(out.get(key), dict):
            out[key] = deep_merge(out[key], value)
        else:
            out[key] = copy.deepcopy(value)
    return out


def _set_path(target: dict[str, Any], path: list[str], value: Any) -> None:
    cur = target
    for key in path[:-1]:
        nxt = cur.get(key)
        if not isinstance(nxt, dict):
            nxt = {}
            cur[key] = nxt
        cur = nxt
    cur[path[-1]] = value


def _get_path(source: Any, path: list[str]) -> tuple[bool, Any]:
    cur = source
    for key in path:
        if not isinstance(cur, dict) or key not in cur:
            return False, None
        cur = cur[key]
    return True, cur


def pillar_share_warnings(pillars: list[dict[str, Any]]) -> list[str]:
    total = sum(float(p["share_target"]) for p in pillars
                if p.get("share_target") is not None and (p.get("status") or "active") == "active")
    if total > 1.0 + 1e-6:
        return [f"Active pillar share targets sum to {total:.2f} (> 1.00); shares will be normalized when planning."]
    return []


# ====================================================================== service
class BrandService:
    """All methods are classmethods so both `BrandService.x(db, ...)` and `BrandService().x(db, ...)` work."""

    # ------------------------------------------------------------ brands
    @classmethod
    async def get(cls, db: AsyncSession, workspace_id: UUID, brand_id: UUID, *, include_deleted: bool = False) -> Brand:
        stmt = select(Brand).where(Brand.id == brand_id, Brand.workspace_id == workspace_id)
        if not include_deleted:
            stmt = stmt.where(Brand.deleted_at.is_(None))
        brand = (await db.execute(stmt)).scalar_one_or_none()
        if brand is None:
            raise not_found("Brand")
        return brand

    @classmethod
    async def list_brands(cls, db: AsyncSession, workspace_id: UUID, *, status: str | None = None) -> list[Brand]:
        stmt = select(Brand).where(Brand.workspace_id == workspace_id, Brand.deleted_at.is_(None))
        if status:
            stmt = stmt.where(Brand.status == status)
        return list((await db.execute(stmt.order_by(Brand.name, Brand.id))).scalars().all())

    @classmethod
    async def _slug_taken(cls, db: AsyncSession, workspace_id: UUID, slug: str, exclude_id: UUID | None = None) -> bool:
        stmt = select(Brand.id).where(Brand.workspace_id == workspace_id, Brand.slug == slug)
        if exclude_id:
            stmt = stmt.where(Brand.id != exclude_id)
        return (await db.execute(stmt.limit(1))).first() is not None

    @classmethod
    async def _unique_slug(cls, db: AsyncSession, workspace_id: UUID, base: str) -> str:
        slug, n = base, 2
        while await cls._slug_taken(db, workspace_id, slug):
            slug = f"{base[:55]}-{n}"
            n += 1
        return slug

    @classmethod
    async def create(cls, db: AsyncSession, member: Any, data: BrandCreate, *,
                     seed_default_pillars: bool | None = None) -> Brand:
        ws = member.workspace_id
        if data.slug:
            if await cls._slug_taken(db, ws, data.slug):
                raise conflict("slug_taken", f"A brand with slug '{data.slug}' already exists in this workspace")
            slug = data.slug
        else:
            slug = await cls._unique_slug(db, ws, slugify(data.name))
        user_id = actor_user_id(member)
        if user_id is None:
            raise ProblemError(400, "actor_required", "A user is required to create a brand")
        brand = Brand(workspace_id=ws, name=data.name.strip(), slug=slug, description=data.description,
                      industry=data.industry, sub_industry=data.sub_industry,
                      website=str(data.website) if data.website else None, geography=list(data.geography),
                      languages=list(data.languages) or ["en"], timezone=data.timezone, status="active",
                      created_by=user_id)
        brand.settings = BrandSettings(workspace_id=ws)
        db.add(brand)
        await db.flush()
        seed = data.seed_default_pillars if seed_default_pillars is None else seed_default_pillars
        if seed:
            for i, name in enumerate(DEFAULT_PILLARS):
                db.add(ContentPillar(workspace_id=ws, brand_id=brand.id, name=name, position=i, status="active"))
            await db.flush()
        await cls._bump_cache_key(db, brand)
        await db.refresh(brand)
        await safe_audit(db, member, "brand.create", "brand", brand.id,
                         after=BrandOut.model_validate(brand).model_dump(mode="json"))
        return brand

    @classmethod
    async def update(cls, db: AsyncSession, member: Any, brand_id: UUID, data: BrandUpdate) -> Brand:
        brand = await cls.get(db, member.workspace_id, brand_id)
        before = BrandOut.model_validate(brand).model_dump(mode="json")
        patch = data.model_dump(exclude_unset=True)
        if "slug" in patch and patch["slug"] and patch["slug"] != brand.slug:
            if await cls._slug_taken(db, member.workspace_id, patch["slug"], exclude_id=brand.id):
                raise conflict("slug_taken", f"A brand with slug '{patch['slug']}' already exists in this workspace")
        if patch.get("logo_asset_id"):
            await cls._get_media(db, member.workspace_id, patch["logo_asset_id"])
        for key, value in patch.items():
            if key in ("name", "slug", "timezone") and value is None:
                continue
            if key == "website" and value is not None:
                value = str(value)
            if key in ("geography", "languages") and value is None:
                value = []
            setattr(brand, key, value)
        await db.flush()
        await cls._bump_cache_key(db, brand)
        await db.refresh(brand)
        await safe_audit(db, member, "brand.update", "brand", brand.id, before=before,
                         after=BrandOut.model_validate(brand).model_dump(mode="json"))
        return brand

    @classmethod
    async def soft_delete(cls, db: AsyncSession, member: Any, brand_id: UUID) -> None:
        brand = await cls.get(db, member.workspace_id, brand_id)
        before = BrandOut.model_validate(brand).model_dump(mode="json")
        brand.deleted_at = datetime.now(UTC)
        brand.status = "deleted"
        # free the slug for reuse (UNIQUE(workspace_id, slug) also covers soft-deleted rows)
        brand.slug = f"{brand.slug[:40]}--deleted-{brand.id.hex[:8]}"
        await db.flush()
        await safe_audit(db, member, "brand.delete", "brand", brand.id, before=before)

    delete = soft_delete

    # ------------------------------------------------------------ settings
    @classmethod
    async def get_settings(cls, db: AsyncSession, workspace_id: UUID, brand_id: UUID) -> BrandSettings:
        brand = await cls.get(db, workspace_id, brand_id)
        row = (await db.execute(select(BrandSettings).where(BrandSettings.brand_id == brand.id,
                                                            BrandSettings.workspace_id == workspace_id))
               ).scalar_one_or_none()
        if row is None:
            row = BrandSettings(brand_id=brand.id, workspace_id=workspace_id)
            db.add(row)
            await db.flush()
            await db.refresh(row)
        return row

    @classmethod
    async def update_settings(cls, db: AsyncSession, member: Any, brand_id: UUID,
                              data: BrandSettingsUpdate | dict[str, Any]) -> BrandSettings:
        """Partial update: only provided sections change; each is deep-merged into the stored section (nested objects
        merge key-wise, lists replace, explicit null clears; `"section": null` resets it) and re-validated."""
        if isinstance(data, dict):
            try:
                data = BrandSettingsUpdate.model_validate(data)
            except ValidationError as e:
                raise validation("Invalid brand settings", [{"code": err.get("type"),
                                                              "field": ".".join(str(x) for x in err.get("loc", [])),
                                                              "message": err.get("msg")} for err in e.errors()]) from e
        row = await cls.get_settings(db, member.workspace_id, brand_id)
        before = settings_to_dict(row)
        changed: list[str] = []
        for name in SECTION_NAMES:
            if name not in data.model_fields_set:
                continue
            incoming: BaseModel | None = getattr(data, name)
            current = copy.deepcopy(getattr(row, name) or {})
            if incoming is None:
                merged: dict[str, Any] = {}
            else:
                merged = deep_merge(current, incoming.model_dump(mode="json", exclude_unset=True))
            canonical = validate_section(name, merged)
            if canonical != current:
                setattr(row, name, canonical)
                changed.append(name)
        if changed:
            await db.flush()
            brand = await cls.get(db, member.workspace_id, brand_id)
            await cls._bump_cache_key(db, brand, row)
            await db.refresh(row)
            await safe_audit(db, member, "brand.settings_update", "brand", brand_id,
                             before={k: before[k] for k in changed}, after={k: getattr(row, k) for k in changed})
        return row

    @classmethod
    async def _bump_cache_key(cls, db: AsyncSession, brand: Brand, row: BrandSettings | None = None) -> str:
        if row is None:
            row = (await db.execute(select(BrandSettings).where(BrandSettings.brand_id == brand.id))).scalar_one_or_none()
        pillars = await cls._pillar_rows(db, brand.workspace_id, brand.id)
        key = compute_context_cache_key(brand_to_dict(brand), settings_to_dict(row), [pillar_to_dict(p) for p in pillars])
        if row is not None and row.context_cache_key != key:
            row.context_cache_key = key
            await db.flush()
        return key

    # ------------------------------------------------------------ pillars
    @classmethod
    async def _pillar_rows(cls, db: AsyncSession, workspace_id: UUID, brand_id: UUID) -> list[ContentPillar]:
        stmt = (select(ContentPillar)
                .where(ContentPillar.workspace_id == workspace_id, ContentPillar.brand_id == brand_id)
                .order_by(ContentPillar.position, ContentPillar.created_at, ContentPillar.id))
        return list((await db.execute(stmt)).scalars().all())

    @classmethod
    async def list_pillars(cls, db: AsyncSession, workspace_id: UUID, brand_id: UUID, *,
                           status: str | None = None) -> list[ContentPillar]:
        await cls.get(db, workspace_id, brand_id)
        rows = await cls._pillar_rows(db, workspace_id, brand_id)
        return [p for p in rows if status is None or p.status == status]

    @classmethod
    async def _get_pillar(cls, db: AsyncSession, workspace_id: UUID, brand_id: UUID, pillar_id: UUID) -> ContentPillar:
        p = (await db.execute(select(ContentPillar).where(ContentPillar.id == pillar_id,
                                                          ContentPillar.brand_id == brand_id,
                                                          ContentPillar.workspace_id == workspace_id))
             ).scalar_one_or_none()
        if p is None:
            raise not_found("Pillar")
        return p

    @staticmethod
    def _resequence(rows: list[ContentPillar], moved: ContentPillar | None = None, index: int | None = None) -> None:
        ordered = [r for r in rows if r is not moved]
        if moved is not None:
            idx = len(ordered) if index is None else max(0, min(index, len(ordered)))
            ordered.insert(idx, moved)
        for i, r in enumerate(ordered):
            if r.position != i:
                r.position = i

    @classmethod
    async def _name_taken(cls, db: AsyncSession, brand_id: UUID, name: str, exclude_id: UUID | None = None) -> bool:
        stmt = select(ContentPillar.id).where(ContentPillar.brand_id == brand_id,
                                              func.lower(ContentPillar.name) == name.strip().lower())
        if exclude_id:
            stmt = stmt.where(ContentPillar.id != exclude_id)
        return (await db.execute(stmt.limit(1))).first() is not None

    @classmethod
    async def create_pillar(cls, db: AsyncSession, member: Any, brand_id: UUID,
                            data: PillarCreate) -> tuple[ContentPillar, list[str]]:
        brand = await cls.get(db, member.workspace_id, brand_id)
        if await cls._name_taken(db, brand.id, data.name):
            raise conflict("pillar_exists", f"A pillar named '{data.name}' already exists for this brand")
        rows = await cls._pillar_rows(db, member.workspace_id, brand.id)
        pillar = ContentPillar(workspace_id=member.workspace_id, brand_id=brand.id, name=data.name.strip(),
                               description=data.description, share_target=data.share_target, color=data.color,
                               examples=list(data.examples), status=data.status, position=len(rows))
        db.add(pillar)
        cls._resequence(rows, pillar, data.position)
        await db.flush()
        await cls._bump_cache_key(db, brand)
        await db.refresh(pillar)
        rows = await cls._pillar_rows(db, member.workspace_id, brand.id)
        await safe_audit(db, member, "brand.pillar_create", "content_pillar", pillar.id, after=pillar_to_dict(pillar))
        return pillar, pillar_share_warnings([pillar_to_dict(p) for p in rows])

    @classmethod
    async def update_pillar(cls, db: AsyncSession, member: Any, brand_id: UUID, pillar_id: UUID,
                            data: PillarUpdate) -> tuple[ContentPillar, list[str]]:
        brand = await cls.get(db, member.workspace_id, brand_id)
        pillar = await cls._get_pillar(db, member.workspace_id, brand.id, pillar_id)
        before = pillar_to_dict(pillar)
        patch = data.model_dump(exclude_unset=True)
        if patch.get("name") and patch["name"].strip().lower() != pillar.name.lower():
            if await cls._name_taken(db, brand.id, patch["name"], exclude_id=pillar.id):
                raise conflict("pillar_exists", f"A pillar named '{patch['name']}' already exists for this brand")
        position = patch.pop("position", None)
        for key, value in patch.items():
            if key in ("name", "status") and value is None:
                continue
            if key == "examples":
                value = list(value or [])
            if key == "name":
                value = str(value).strip()
            setattr(pillar, key, value)
        if position is not None:
            rows = await cls._pillar_rows(db, member.workspace_id, brand.id)
            cls._resequence(rows, pillar, position)
        await db.flush()
        await cls._bump_cache_key(db, brand)
        await db.refresh(pillar)
        rows = await cls._pillar_rows(db, member.workspace_id, brand.id)
        await safe_audit(db, member, "brand.pillar_update", "content_pillar", pillar.id, before=before,
                         after=pillar_to_dict(pillar))
        return pillar, pillar_share_warnings([pillar_to_dict(p) for p in rows])

    @classmethod
    async def delete_pillar(cls, db: AsyncSession, member: Any, brand_id: UUID, pillar_id: UUID) -> None:
        brand = await cls.get(db, member.workspace_id, brand_id)
        pillar = await cls._get_pillar(db, member.workspace_id, brand.id, pillar_id)
        before = pillar_to_dict(pillar)
        await db.delete(pillar)
        await db.flush()
        cls._resequence(await cls._pillar_rows(db, member.workspace_id, brand.id))
        await db.flush()
        await cls._bump_cache_key(db, brand)
        await safe_audit(db, member, "brand.pillar_delete", "content_pillar", pillar_id, before=before)

    @staticmethod
    def pillar_out(pillar: ContentPillar, warnings: list[str] | None = None) -> PillarOut:
        out = PillarOut.model_validate(pillar)
        return out.model_copy(update={"warnings": warnings or []})

    # ------------------------------------------------------------ assets
    @classmethod
    async def _get_media(cls, db: AsyncSession, workspace_id: UUID, media_id: UUID) -> MediaAsset:
        m = (await db.execute(select(MediaAsset).where(MediaAsset.id == media_id, MediaAsset.workspace_id == workspace_id,
                                                       MediaAsset.deleted_at.is_(None)))).scalar_one_or_none()
        if m is None:
            raise not_found("Media asset")
        return m

    @classmethod
    async def list_assets(cls, db: AsyncSession, workspace_id: UUID, brand_id: UUID, *,
                          kind: str | None = None) -> list[BrandAsset]:
        await cls.get(db, workspace_id, brand_id)
        stmt = select(BrandAsset).where(BrandAsset.workspace_id == workspace_id, BrandAsset.brand_id == brand_id)
        if kind:
            stmt = stmt.where(BrandAsset.kind == kind)
        return list((await db.execute(stmt.order_by(BrandAsset.created_at, BrandAsset.id))).scalars().all())

    @classmethod
    async def attach_asset(cls, db: AsyncSession, member: Any, brand_id: UUID, data: BrandAssetCreate) -> BrandAsset:
        """Link a media asset to the brand. Logos also become `brands.logo_asset_id` (if unset) and `visual.logo_asset_ids`."""
        brand = await cls.get(db, member.workspace_id, brand_id)
        media = await cls._get_media(db, member.workspace_id, data.media_asset_id)
        existing = (await db.execute(select(BrandAsset).where(BrandAsset.brand_id == brand.id,
                                                              BrandAsset.workspace_id == member.workspace_id,
                                                              BrandAsset.kind == data.kind,
                                                              BrandAsset.media_asset_id == media.id))).scalar_one_or_none()
        if existing is not None:
            return existing
        asset = BrandAsset(workspace_id=member.workspace_id, brand_id=brand.id, kind=data.kind, media_asset_id=media.id,
                           meta=dict(data.meta))
        db.add(asset)
        if media.brand_id is None:
            media.brand_id = brand.id
        if data.kind in ("logo", "logo_dark"):
            if data.kind == "logo" and brand.logo_asset_id is None:
                brand.logo_asset_id = media.id
            row = await cls.get_settings(db, member.workspace_id, brand.id)
            visual = copy.deepcopy(row.visual or {})
            ids = [str(x) for x in visual.get("logo_asset_ids") or []]
            if str(media.id) not in ids:
                visual["logo_asset_ids"] = [*ids, str(media.id)]
                row.visual = validate_section("visual", visual)
        await db.flush()
        await cls._bump_cache_key(db, brand)
        await db.refresh(asset)
        await safe_audit(db, member, "brand.asset_attach", "brand_asset", asset.id,
                         after={"brand_id": str(brand.id), "kind": data.kind, "media_asset_id": str(media.id)})
        return asset

    # ------------------------------------------------------------ context
    @classmethod
    async def build_context(cls, db: AsyncSession, brand_id: UUID, mode: ContextMode = "compact", *,
                            workspace_id: UUID | None = None) -> str:
        """Render the BrandContext block; cached in Redis 10 min keyed by brand id + content hash.

        `workspace_id` is optional for backwards-compatible callers (RLS still applies); pass it when available.
        """
        if mode not in ("compact", "full"):
            raise validation("mode must be 'compact' or 'full'")
        stmt = select(Brand).where(Brand.id == brand_id, Brand.deleted_at.is_(None))
        if workspace_id is not None:
            stmt = stmt.where(Brand.workspace_id == workspace_id)
        brand = (await db.execute(stmt)).scalar_one_or_none()
        if brand is None:
            raise not_found("Brand")
        row = (await db.execute(select(BrandSettings).where(BrandSettings.brand_id == brand.id,
                                                            BrandSettings.workspace_id == brand.workspace_id))
               ).scalar_one_or_none()
        pillars = [pillar_to_dict(p) for p in await cls._pillar_rows(db, brand.workspace_id, brand.id)]
        b, s = brand_to_dict(brand), settings_to_dict(row)
        key = compute_context_cache_key(b, s, pillars)
        rkey = f"brand_ctx:{brand.id}:{mode}:{key}"
        try:
            cached = await get_redis().get(rkey)
            if cached:
                return cached.decode() if isinstance(cached, bytes) else str(cached)
        except Exception as e:  # cache is best-effort
            log.debug("brand_ctx.cache_unavailable", error=str(e))
        text = render_brand_context(b, s, pillars, mode)
        try:
            await get_redis().set(rkey, text, ex=CONTEXT_TTL_S)
        except Exception as e:
            log.debug("brand_ctx.cache_unavailable", error=str(e))
        return text

    @classmethod
    async def get_visual_identity(cls, db: AsyncSession, workspace_id: UUID, brand_id: UUID) -> dict[str, Any]:
        brand = await cls.get(db, workspace_id, brand_id)
        row = await cls.get_settings(db, workspace_id, brand_id)
        logos = await cls.list_assets(db, workspace_id, brand_id)
        return {"brand_id": str(brand.id), "name": brand.name, "visual": copy.deepcopy(row.visual or {}),
                "logo_asset_id": str(brand.logo_asset_id) if brand.logo_asset_id else None,
                "assets": [{"id": str(a.id), "kind": a.kind, "media_asset_id": str(a.media_asset_id)}
                           for a in logos if a.media_asset_id]}

    # ------------------------------------------------------------ proposals (AI builder → user confirmation)
    @classmethod
    async def apply_proposal(cls, db: AsyncSession, brand_id: UUID, proposal: dict[str, Any], accepted_fields: list[str],
                             *, member: Any = None, workspace_id: UUID | None = None) -> dict[str, Any]:
        """Write ONLY the accepted fields of an AI proposal.

        `proposal` shape: brand columns at top level or under "brand" (description, industry, …), settings sections at top
        level (audience, voice, …), optional "pillars": [{name, share_target?, description?, examples?}].
        `accepted_fields` entries are dotted paths: "description", "brand.industry", "brand" (all brand fields),
        "voice" (whole section, deep-merged), "voice.tone", "voice.tone.formal", "pillars".
        Returns {"applied": [...], "skipped": [...], "warnings": [...]}.
        """
        ws = workspace_id or getattr(member, "workspace_id", None)
        if ws is None:
            brand = (await db.execute(select(Brand).where(Brand.id == brand_id, Brand.deleted_at.is_(None)))
                     ).scalar_one_or_none()
            if brand is None:
                raise not_found("Brand")
            ws = brand.workspace_id
        else:
            brand = await cls.get(db, ws, brand_id)
        row = await cls.get_settings(db, ws, brand.id)
        brand_props = {**(proposal.get("brand") or {}), **{k: proposal[k] for k in BRAND_FIELDS if k in proposal}}
        applied: list[str] = []
        skipped: list[str] = []
        warnings: list[str] = []
        brand_patch: dict[str, Any] = {}
        sections: dict[str, dict[str, Any]] = {}
        accept_pillars = False
        for raw in accepted_fields:
            path = [p for p in str(raw).strip().split(".") if p]
            if not path:
                continue
            head = path[0]
            if head == "brand" and len(path) == 1:
                for k, v in brand_props.items():
                    if k in BRAND_FIELDS:
                        brand_patch[k] = v
                (applied if brand_props else skipped).append(raw)
                continue
            if head == "brand":
                path = path[1:]
                head = path[0]
            if head in BRAND_FIELDS and len(path) == 1:
                if head in brand_props:
                    brand_patch[head] = brand_props[head]
                    applied.append(raw)
                else:
                    skipped.append(raw)
                continue
            if head == "pillars":
                if isinstance(proposal.get("pillars"), list):
                    accept_pillars = True
                    applied.append(raw)
                else:
                    skipped.append(raw)
                continue
            if head in SECTION_NAMES:
                found, value = _get_path(proposal, path)
                if not found:
                    skipped.append(raw)
                    continue
                target = sections.setdefault(head, copy.deepcopy(getattr(row, head) or {}))
                if len(path) == 1:
                    if not isinstance(value, dict):
                        skipped.append(raw)
                        continue
                    sections[head] = deep_merge(target, value)
                else:
                    _set_path(target, path[1:], copy.deepcopy(value))
                applied.append(raw)
                continue
            skipped.append(raw)

        if brand_patch:
            try:
                upd = BrandUpdate.model_validate(brand_patch)
            except ValidationError as e:
                raise validation("Invalid proposed brand fields",
                                 [{"code": err.get("type"), "field": ".".join(str(x) for x in err.get("loc", [])),
                                   "message": err.get("msg")} for err in e.errors()]) from e
            for key, value in upd.model_dump(exclude_unset=True).items():
                if value is None and key in ("name", "timezone"):
                    continue
                setattr(brand, key, str(value) if key == "website" and value is not None else value)
        before = settings_to_dict(row)
        for name, merged in sections.items():
            setattr(row, name, validate_section(name, merged))
        if accept_pillars:
            existing = {p.name.lower(): p for p in await cls._pillar_rows(db, ws, brand.id)}
            rows = list(existing.values())
            for item in proposal.get("pillars") or []:
                if isinstance(item, str):
                    item = {"name": item}
                try:
                    pc = PillarCreate.model_validate(item)
                except ValidationError:
                    warnings.append(f"Skipped invalid pillar proposal: {item!r}")
                    continue
                cur = existing.get(pc.name.lower())
                if cur is not None:
                    if pc.share_target is not None:
                        cur.share_target = pc.share_target
                    if pc.description and not cur.description:
                        cur.description = pc.description
                    continue
                p = ContentPillar(workspace_id=ws, brand_id=brand.id, name=pc.name.strip(), description=pc.description,
                                  share_target=pc.share_target, color=pc.color, examples=list(pc.examples),
                                  status="active", position=len(rows))
                db.add(p)
                rows.append(p)
                existing[pc.name.lower()] = p
            warnings.extend(pillar_share_warnings([pillar_to_dict(p) for p in rows]))
        await db.flush()
        await cls._bump_cache_key(db, brand, row)
        await safe_audit(db, member, "brand.apply_proposal", "brand", brand.id,
                         before={k: before.get(k) for k in sections} if sections else None,
                         after={"applied": applied, "brand_fields": sorted(brand_patch), "sections": sorted(sections),
                                "pillars": accept_pillars})
        return {"applied": applied, "skipped": skipped, "warnings": warnings}

    list = list_brands  # public alias per contract (`BrandService.list`)


brand_service = BrandService()

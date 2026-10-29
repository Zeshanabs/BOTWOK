"""Content-domain LLM tools (doc 06 §6.3–6.4, doc 05 §5.2.7).

Registered names: content.create_draft, content.update_draft, content.create_variant, content.get,
content.save_critique, content.save_factcheck (+ alias factcheck.save), platform.rules, hashtags.suggest,
hashtags.validate, policy.check, claims.extract, ideas.save, ideas.list_recent.

All writes go through ContentService (workspace-scoped, versioned, audited, events emitted) inside a SAVEPOINT so a
failing tool never leaves partial rows in the run's transaction. Agent output always lands in ``ai_generated`` /
``needs_review`` (``rejected`` if a deterministic policy blocks it) — never ``approved``.
"""
from __future__ import annotations

import contextlib
from collections.abc import AsyncIterator, Callable
from typing import Any, Literal
from uuid import UUID

from app.content.claims import extract_claims, extract_claims_llm
from app.content.hashtags import HashtagService
from app.content.platform_rules import describe_rules, rules_for, supported_formats
from app.content.policy import policies_from_brand_settings, policy_check
from app.content.transitions import EDIT_ROLES

try:  # AI core registry (concurrent builder)
    from app.tools.registry import SideEffect, ToolContext, tool
    _READ, _WRITE = SideEffect.READ, SideEffect.WRITE_INTERNAL
except ImportError:  # pragma: no cover - TEMP until ai-core lands
    from dataclasses import dataclass, field

    _LOCAL_TOOLS: dict[str, dict[str, Any]] = {}
    _READ, _WRITE = "READ", "WRITE_INTERNAL"

    @dataclass
    class ToolContext:  # type: ignore[no-redef]
        workspace_id: UUID
        brand_id: UUID | None = None
        user_id: UUID | None = None
        role: str = "editor"
        run_id: UUID | None = None
        task_id: UUID | None = None
        agent_id: str | None = None
        db: Any = None
        extra: dict[str, Any] = field(default_factory=dict)

    def tool(name: str, side_effect: Any = "READ", roles: Any = None, timeout_s: float = 20.0,  # type: ignore[no-redef]
             idempotent: bool = False, description: str | None = None, **_: Any) -> Callable[..., Any]:
        def deco(fn: Callable[..., Any]) -> Callable[..., Any]:
            _LOCAL_TOOLS[name] = {"fn": fn, "side_effect": side_effect, "roles": roles, "timeout_s": timeout_s}
            return fn
        return deco

WRITE_ROLES = set(EDIT_ROLES)


# ── context helpers ─────────────────────────────────────────────────────────────

@contextlib.asynccontextmanager
async def _session(ctx: ToolContext) -> AsyncIterator[Any]:
    """The run's session when present (wrapped in a SAVEPOINT), else a fresh workspace-scoped unit of work."""
    db = getattr(ctx, "db", None)
    if db is not None:
        async with db.begin_nested():
            yield db
        return
    opener = getattr(ctx, "session", None)
    if callable(opener):
        async with opener() as s:
            yield s
        return
    from app.core.db import session_scope
    async with session_scope(ctx.workspace_id) as s:
        yield s


def _actor(ctx: ToolContext) -> Any:
    from app.services.content_service import Actor
    role = getattr(ctx, "role", None) or "editor"
    return Actor(workspace_id=ctx.workspace_id, user_id=getattr(ctx, "user_id", None), role=str(getattr(role, "value", role)),
                 kind="agent", agent_id=getattr(ctx, "agent_id", None) or "agent")


def _gen_meta(ctx: ToolContext, extra: dict[str, Any] | None = None) -> dict[str, Any]:
    out = {"run_id": str(ctx.run_id) if getattr(ctx, "run_id", None) else None,
           "task_id": str(ctx.task_id) if getattr(ctx, "task_id", None) else None,
           "agent": getattr(ctx, "agent_id", None)}
    for k, v in (extra or {}).items():
        if v is not None:
            out[k] = v
    return out


async def _brand_policies(db: Any, ctx: ToolContext, brand_id: Any = None) -> dict[str, Any]:
    from sqlalchemy import select

    from app.models import Brand
    bid = brand_id or getattr(ctx, "brand_id", None)
    if not bid:
        return {}
    b = (await db.execute(select(Brand).where(Brand.id == UUID(str(bid)), Brand.workspace_id == ctx.workspace_id))
         ).scalar_one_or_none()
    return policies_from_brand_settings(b.settings) if b is not None else {}


def _item_summary(data: dict[str, Any]) -> dict[str, Any]:
    keep = ("id", "brand_id", "campaign_id", "idea_id", "pillar_id", "title", "content_type", "master_format", "status",
            "body", "language", "current_version", "ai_generated", "risk_level", "critique", "factcheck",
            "generation_metadata", "sources", "platforms")
    out = {k: data.get(k) for k in keep}
    out["variants"] = [{k: v.get(k) for k in ("id", "platform", "format", "text", "segments", "hashtags", "media_plan",
                                              "platform_metadata", "status", "validation", "critique", "factcheck",
                                              "changes_made", "current_version")}
                       for v in data.get("variants") or []]
    return out


# ── content.* ───────────────────────────────────────────────────────────────────

@tool("content.create_draft", side_effect=_WRITE, roles=WRITE_ROLES, timeout_s=30)
async def content_create_draft(ctx: ToolContext, title: str, hook: str, body_md: str, cta: str | None = None,
                               hashtags: list[str] | None = None, keywords: list[str] | None = None,
                               visual_concept: str | None = None, alt_text: str | None = None,
                               platform: str | None = None, format: str | None = None, content_type: str | None = None,
                               pillar_id: str | None = None, sources: list[dict[str, Any]] | None = None,
                               generation_metadata: dict[str, Any] | None = None, content_id: str | None = None,
                               campaign_id: str | None = None, idea_id: str | None = None,
                               platform_metadata: dict[str, Any] | None = None) -> dict:
    """Save a written draft. Creates a content item (status ai_generated) + its first platform variant + a version
    authored by the agent + claim-level content_sources. Pass content_id to write into an existing item instead.
    sources: [{claim, source_id}] (use unsourced claims sparingly; fact_check targets them)."""
    from app.services.content_service import ContentService
    a = _actor(ctx)
    meta = _gen_meta(ctx, generation_metadata)
    output = {"title": title, "hook": hook, "body_md": body_md, "cta": cta, "hashtags": hashtags or [],
              "keywords": keywords or [], "visual_concept": visual_concept, "alt_text": alt_text, "platform": platform,
              "format": format, "content_type": content_type, "sources": sources or [], "generation_metadata": meta,
              "platform_metadata": platform_metadata or {}}
    async with _session(ctx) as db:
        if content_id:
            item_id = UUID(str(content_id))
        else:
            if not getattr(ctx, "brand_id", None):
                return {"error": "no brand in context; pass content_id or run with a brand"}
            item = await ContentService.create_item(db, a, {
                "brand_id": ctx.brand_id, "title": title, "content_type": content_type, "pillar_id": pillar_id,
                "campaign_id": campaign_id, "idea_id": idea_id, "master_format": format or "text",
                "body": {}}, ai_generated=True, generation_metadata=meta)
            item_id = item.id
        res = await ContentService.apply_agent_output(db, item_id, "writer", output, actor=a, run_id=meta.get("run_id"))
    return {**res, "content_id": str(item_id)}


@tool("content.update_draft", side_effect=_WRITE, roles=WRITE_ROLES, timeout_s=30)
async def content_update_draft(ctx: ToolContext, content_id: str, title: str | None = None, hook: str | None = None,
                               body_md: str | None = None, cta: str | None = None, hashtags: list[str] | None = None,
                               keywords: list[str] | None = None, visual_concept: str | None = None,
                               alt_text: str | None = None, notes: str | None = None,
                               sources: list[dict[str, Any]] | None = None,
                               generation_metadata: dict[str, Any] | None = None) -> dict:
    """Revise an existing draft (new version authored by the agent). Only the fields you pass change. Approved
    content cannot be modified."""
    from app.services.content_service import ContentService
    a = _actor(ctx)
    output: dict[str, Any] = {k: v for k, v in {"title": title, "hook": hook, "body_md": body_md, "cta": cta,
                                                "hashtags": hashtags, "keywords": keywords,
                                                "visual_concept": visual_concept, "alt_text": alt_text,
                                                "notes": notes, "sources": sources}.items() if v is not None}
    output["generation_metadata"] = _gen_meta(ctx, generation_metadata)
    async with _session(ctx) as db:
        return await ContentService.apply_agent_output(db, UUID(str(content_id)), "writer", output, actor=a,
                                                       run_id=output["generation_metadata"].get("run_id"))


@tool("content.create_variant", side_effect=_WRITE, roles=WRITE_ROLES, timeout_s=30)
async def content_create_variant(ctx: ToolContext, content_id: str, platform: str, format: str, text: str | None = None,
                                 segments: list[Any] | None = None, hashtags: list[str] | None = None,
                                 media_plan: dict[str, Any] | None = None, platform_metadata: dict[str, Any] | None = None,
                                 changes_made: list[str] | None = None, variant_id: str | None = None) -> dict:
    """Save a platform-native variant of a content item (validated against platform.rules; result includes
    `validation` issues to fix). Pass variant_id to revise an existing variant."""
    from app.services.content_service import ContentService
    a = _actor(ctx)
    output = {"platform": platform, "format": format, "text": text, "segments": segments or [], "hashtags": hashtags or [],
              "media_plan": media_plan or {}, "platform_metadata": platform_metadata or {},
              "changes_made": changes_made or [], "generation_metadata": _gen_meta(ctx)}
    async with _session(ctx) as db:
        return await ContentService.apply_agent_output(db, UUID(str(content_id)), "repurposer", output, actor=a,
                                                       variant_id=UUID(str(variant_id)) if variant_id else None,
                                                       run_id=output["generation_metadata"].get("run_id"))


@tool("content.get", side_effect=_READ, timeout_s=15, idempotent=True)
async def content_get(ctx: ToolContext, content_id: str) -> dict:
    """Read a content item with its master body, variants, sources, critique, fact-check and status."""
    from app.services.content_service import ContentService
    async with _session(ctx) as db:
        item = await ContentService.get_item(db, ctx.workspace_id, UUID(str(content_id)))
        return _item_summary(await ContentService.serialize_item(db, item))


async def _save_review(ctx: ToolContext, agent: str, target_type: str, target_id: str, payload: dict[str, Any]) -> dict:
    from sqlalchemy import select

    from app.models import ContentVariant
    from app.services.content_service import ContentService
    a = _actor(ctx)
    tid = UUID(str(target_id))
    async with _session(ctx) as db:
        variant_id = None
        item_id = tid
        if target_type in ("variant", "content_variant"):
            row = (await db.execute(select(ContentVariant.content_item_id).where(
                ContentVariant.id == tid, ContentVariant.workspace_id == ctx.workspace_id))).scalar_one_or_none()
            if row is None:
                return {"error": "variant not found"}
            item_id, variant_id = row, tid
        meta = _gen_meta(ctx)
        return await ContentService.apply_agent_output(db, item_id, agent, payload, actor=a, variant_id=variant_id,
                                                       run_id=meta.get("run_id"))


@tool("content.save_critique", side_effect=_WRITE, roles=WRITE_ROLES, timeout_s=20)
async def content_save_critique(ctx: ToolContext, target_type: Literal["item", "variant"], target_id: str,
                                critique: dict[str, Any]) -> dict:
    """Store a critique {scores{quality, brand_fit, platform_fit, clarity, hook_strength, cta_strength, risk}, issues[],
    rewrite_suggestions[], policy_flags[], overall, recommend, risk_level} on an item or variant. Recomputes risk and
    routes ai_generated content to needs_review."""
    return await _save_review(ctx, "critic", target_type, target_id, critique)


@tool("content.save_factcheck", side_effect=_WRITE, roles=WRITE_ROLES, timeout_s=20)
async def content_save_factcheck(ctx: ToolContext, target_type: Literal["item", "variant"], target_id: str,
                                 factcheck: dict[str, Any]) -> dict:
    """Store a fact-check {claims[{text, verdict: supported|contradicted|unverifiable|opinion, confidence,
    evidence[{source_id, quote}]}], overall_risk, requires_human} on an item or variant. Contradicted claims block
    approval; unverifiable claims in regulated domains make the content high-risk."""
    return await _save_review(ctx, "fact_check", target_type, target_id, factcheck)


@tool("factcheck.save", side_effect=_WRITE, roles=WRITE_ROLES, timeout_s=20)
async def factcheck_save(ctx: ToolContext, content_id: str, factcheck: dict[str, Any], variant_id: str | None = None) -> dict:
    """Alias of content.save_factcheck keyed by content_id (and optional variant_id)."""
    if variant_id:
        return await _save_review(ctx, "fact_check", "variant", variant_id, factcheck)
    return await _save_review(ctx, "fact_check", "item", content_id, factcheck)


# ── platform / hashtags / policy / claims ───────────────────────────────────────

@tool("platform.rules", side_effect=_READ, timeout_s=5, idempotent=True)
async def platform_rules(ctx: ToolContext, platform: str, format: str = "text") -> dict:
    """Platform limits and conventions for a (platform, format): text limits and units, hashtag norms, link behavior,
    segment rules, media limits, poll shape, hook conventions and tone defaults."""
    r = rules_for(platform, format)
    return {"platform": r["platform"], "format": r["format"], "supported": r["supported"],
            "supported_formats": supported_formats(platform), "rules": r, "summary": describe_rules(platform, format)}


@tool("hashtags.suggest", side_effect=_READ, timeout_s=10, idempotent=True)
async def hashtags_suggest(ctx: ToolContext, platform: str, text: str, k: int | None = None) -> dict:
    """Suggest hashtags for a draft from the brand's core/campaign tags, historical performance and keywords in the text.
    Banned tags are never suggested; k defaults to the platform's recommended count."""
    if not getattr(ctx, "brand_id", None):
        return {"hashtags": [], "note": "no brand in context"}
    async with _session(ctx) as db:
        tags = await HashtagService.suggest(db, ctx.brand_id, platform, text, k, workspace_id=ctx.workspace_id)
    r = rules_for(platform, "text")["hashtags"]
    return {"hashtags": tags, "recommended": r.get("recommended"), "max": r.get("max"), "placement": r.get("placement")}


@tool("hashtags.validate", side_effect=_READ, timeout_s=10, idempotent=True)
async def hashtags_validate(ctx: ToolContext, platform: str, hashtags: list[str], format: str = "text") -> dict:
    """Check hashtags against platform counts, formatting and the brand's banned list."""
    banned: set[str] = set()
    if getattr(ctx, "brand_id", None):
        async with _session(ctx) as db:
            banned = await HashtagService.banned_for(db, ctx.workspace_id, ctx.brand_id)
    return HashtagService.validate(platform, hashtags, banned, format=format)


@tool("policy.check", side_effect=_READ, timeout_s=10, idempotent=True)
async def policy_check_tool(ctx: ToolContext, text: str) -> dict:
    """Deterministic policy scan: forbidden topics, banned words/hashtags, sensitive-topic classifier, guarantee
    claims, PII, secrets, link policy and missing disclaimers. Returns {flags[], risk, categories[], blocked}."""
    pol: dict[str, Any] = {}
    if getattr(ctx, "brand_id", None):
        async with _session(ctx) as db:
            pol = await _brand_policies(db, ctx)
    return policy_check(text, pol)


@tool("claims.extract", side_effect=_READ, timeout_s=30, idempotent=True)
async def claims_extract(ctx: ToolContext, text: str, use_llm: bool = True) -> dict:
    """Extract check-worthy factual claims (statistics, dates, named organisations, superlatives, causal statements)."""
    if use_llm:
        claims = await extract_claims_llm(text, workspace_id=ctx.workspace_id, db=getattr(ctx, "db", None),
                                          run_id=getattr(ctx, "run_id", None))
        method = "llm_or_heuristic"
    else:
        claims = extract_claims(text)
        method = "heuristic"
    return {"claims": claims, "count": len(claims), "method": method}


# ── ideas.* ─────────────────────────────────────────────────────────────────────

@tool("ideas.save", side_effect=_WRITE, roles=WRITE_ROLES, timeout_s=60)
async def ideas_save(ctx: ToolContext, ideas: list[dict[str, Any]]) -> dict:
    """Save generated ideas [{title, angle, pillar, content_type, formats[], platforms[], hook_options[],
    evidence_sources[], novelty_score}]. Near-duplicates of recent ideas/content (embedding cosine > 0.88 or trigram
    similarity) are dropped and reported so you can replace them."""
    from app.services.content_service import ContentService
    if not getattr(ctx, "brand_id", None):
        return {"error": "no brand in context"}
    a = _actor(ctx)
    async with _session(ctx) as db:
        res = await ContentService.save_ideas(db, a, ctx.brand_id, ideas, ai_run_id=getattr(ctx, "run_id", None))
    return {**res, "saved_count": len(res["saved"]), "dropped_count": len(res["dropped"])}


@tool("ideas.list_recent", side_effect=_READ, timeout_s=15, idempotent=True)
async def ideas_list_recent(ctx: ToolContext, limit: int = 50) -> dict:
    """Recent ideas and content titles for this brand (use to avoid duplicates)."""
    from sqlalchemy import select

    from app.models import ContentIdea, ContentItem
    limit = max(1, min(int(limit or 50), 500))
    async with _session(ctx) as db:
        q = select(ContentIdea).where(ContentIdea.workspace_id == ctx.workspace_id)
        qi = select(ContentItem.id, ContentItem.title, ContentItem.status).where(
            ContentItem.workspace_id == ctx.workspace_id, ContentItem.deleted_at.is_(None))
        if getattr(ctx, "brand_id", None):
            q = q.where(ContentIdea.brand_id == ctx.brand_id)
            qi = qi.where(ContentItem.brand_id == ctx.brand_id)
        ideas = (await db.execute(q.order_by(ContentIdea.created_at.desc()).limit(limit))).scalars().all()
        items = (await db.execute(qi.order_by(ContentItem.created_at.desc()).limit(min(limit, 200)))).all()
    return {"ideas": [{"id": str(i.id), "title": i.title, "angle": i.angle, "status": i.status,
                       "platforms": [getattr(p, "value", p) for p in i.platforms or []]} for i in ideas],
            "content": [{"id": str(r.id), "title": r.title, "status": getattr(r.status, "value", r.status)} for r in items]}

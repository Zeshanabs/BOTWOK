"""generate — ideas | post | variants | image | report (WRITE_INTERNAL / SPEND).

Idempotent per (run_id, node_key): created content ids and AI run ids live in ``ctx.state`` and are reused on resume
or after a crash. AI kinds call the orchestrator in tool mode (``ideation.generate``, ``writer.write``,
``repurposer.adapt``, ``report.compose``) and yield until AI_RUN_COMPLETED. Generated content is never approved here:
it lands as ``ai_generated``/``needs_review`` and needs a human approval before any schedule/publish.
"""
from __future__ import annotations

from typing import Any
from uuid import UUID

from sqlalchemy import select

from app.core.errors import ProblemError
from app.models.content import ContentIdea, ContentVariant
from app.workflows.nodes.base import NodeContext, NodeError, as_uuid, deliverable, jsonable, problem_message


def _timeout(config: dict[str, Any]) -> int:
    return int(config.get("timeout_minutes") or 60)


async def run(ctx: NodeContext, config: dict[str, Any]) -> dict[str, Any]:
    kind = config.get("kind")
    try:
        if kind == "ideas":
            return await _ideas(ctx, config)
        if kind == "post":
            return await _post(ctx, config)
        if kind == "variants":
            return await _variants(ctx, config)
        if kind == "image":
            return await _image(ctx, config)
        if kind == "report":
            return await _report(ctx, config)
    except ProblemError as e:
        raise NodeError(problem_message(e)) from e
    raise NodeError(f"unknown generate kind {kind!r}")


# ---------------------------------------------------------------------------------------------------------- ideas
async def _ideas(ctx: NodeContext, config: dict[str, Any]) -> dict[str, Any]:
    brand_id = ctx.require_brand()
    count = int(config.get("count") or 10)
    src = config.get("from")
    inputs = {"brand_id": str(brand_id), "count": count, "pillars": config.get("pillars") or [],
              "platforms": config.get("platforms") or [],
              "from": src if isinstance(src, dict) else ({"freeform": src} if src else {})}
    res = await ctx.ai_run("ideas", agent="ideation", action="generate", inputs=inputs,
                           message=f"Generate {count} content ideas ({ctx.workflow.name})",
                           budget_usd=config.get("budget_usd"), timeout_minutes=_timeout(config))
    rid = UUID(str(res["ai_run_id"]))
    ideas = await _ideas_of_run(ctx, rid)
    if not ideas and not ctx.state.get("ideas_saved_fallback"):
        batch = deliverable(res) or {}
        raw = batch.get("ideas") if isinstance(batch, dict) else None
        if raw:
            from app.services.content_service import ContentService
            await ContentService.save_ideas(ctx.db, ctx.require_actor(), brand_id, list(raw), ai_run_id=rid)
            ctx.state["ideas_saved_fallback"] = True
            ideas = await _ideas_of_run(ctx, rid)
    return {"ai_run_id": str(rid), "count": len(ideas), "idea_ids": [str(i.id) for i in ideas],
            "ideas": [{"id": str(i.id), "title": i.title, "angle": i.angle,
                       "content_type": getattr(i.content_type, "value", i.content_type),
                       "platforms": [getattr(p, "value", p) for p in i.platforms or []]} for i in ideas],
            "cost_usd": res.get("cost_usd")}


async def _ideas_of_run(ctx: NodeContext, rid: UUID) -> list[ContentIdea]:
    return list((await ctx.db.execute(select(ContentIdea).where(
        ContentIdea.workspace_id == ctx.workspace_id, ContentIdea.ai_run_id == rid).order_by(ContentIdea.created_at))).scalars())


# ---------------------------------------------------------------------------------------------------------- post
async def _post(ctx: NodeContext, config: dict[str, Any]) -> dict[str, Any]:
    from app.services.content_service import ContentService
    actor = ctx.require_actor()
    brand_id = ctx.require_brand()
    platform = str(config.get("platform") or "")
    if not platform:
        raise NodeError("generate post needs a platform")
    st = ctx.state
    if not st.get("content_item_id"):
        if config.get("content_item_id"):
            item = await ContentService.get_item(ctx.db, ctx.workspace_id, as_uuid(config["content_item_id"], "content_item_id"))
        elif config.get("idea"):
            idea = await ContentService.get_idea(ctx.db, ctx.workspace_id, as_uuid(config["idea"], "idea"))
            if idea.promoted_content_id:
                item = await ContentService.get_item(ctx.db, ctx.workspace_id, idea.promoted_content_id)
            else:
                item = await ContentService.promote_idea(ctx.db, actor, idea.id,
                                                         {"master_format": config.get("format")} if config.get("format") else None)
        else:
            prompt = str(config.get("prompt") or "")
            title = str(config.get("title") or prompt[:120] or "Automation draft").strip()
            item = await ContentService.create_item(ctx.db, actor, {
                "brand_id": brand_id, "title": title[:300], "content_type": config.get("content_type"),
                "master_format": config.get("format") or "text", "body": {"notes": prompt}}, ai_generated=True)
        st["content_item_id"] = str(item.id)
    item_id = as_uuid(st["content_item_id"])
    if not st.get("ai_runs"):
        item = await ContentService.get_item(ctx.db, ctx.workspace_id, item_id)
        fmt = config.get("format") or getattr(item.master_format, "value", item.master_format) or "text"
        inputs = {"content_id": str(item.id), "brand_id": str(item.brand_id), "mode": "write", "platform": platform,
                  "format": fmt, "instructions": config.get("instructions") or config.get("prompt"),
                  "source_ids": config.get("source_ids") or [], "length": config.get("length"),
                  "content_type": getattr(item.content_type, "value", item.content_type) or config.get("content_type"),
                  "pillar_id": str(item.pillar_id) if item.pillar_id else None,
                  "idea_id": str(item.idea_id) if item.idea_id else None, "title": item.title,
                  "current_body": jsonable(item.body)}
        st["write_inputs"] = jsonable(inputs)
    res = await ctx.ai_run("write", agent="writer", action="write", inputs=st["write_inputs"],
                           message=f"Write a {platform} post: {st['write_inputs'].get('title')}",
                           budget_usd=config.get("budget_usd"), timeout_minutes=_timeout(config))
    if not st.get("noted"):
        try:
            item = await ContentService.get_item(ctx.db, ctx.workspace_id, item_id)
            await ContentService._note_run(ctx.db, item, "writer", res.get("ai_run_id"))
        except Exception:  # noqa: BLE001 - metadata only
            pass
        st["noted"] = True
    variants = await _variants_of(ctx, item_id)
    item = await ContentService.get_item(ctx.db, ctx.workspace_id, item_id)
    match = [v for v in variants if getattr(v.platform, "value", v.platform) == platform]
    return {"content_item_id": str(item_id), "title": item.title, "status": getattr(item.status, "value", item.status),
            "variant_id": str(match[0].id) if match else None, "variant_ids": [str(v.id) for v in variants],
            "platform": platform, "ai_run_id": res.get("ai_run_id"), "cost_usd": res.get("cost_usd")}


async def _variants_of(ctx: NodeContext, item_id: UUID) -> list[ContentVariant]:
    return list((await ctx.db.execute(select(ContentVariant).where(
        ContentVariant.workspace_id == ctx.workspace_id, ContentVariant.content_item_id == item_id)
        .order_by(ContentVariant.created_at).execution_options(populate_existing=True))).scalars())


# ---------------------------------------------------------------------------------------------------------- variants
async def _variants(ctx: NodeContext, config: dict[str, Any]) -> dict[str, Any]:
    from app.content.platform_rules import support_of
    from app.services.content_service import ContentService
    item_id = as_uuid(config.get("content_item_id"), "content_item_id")
    item = await ContentService.get_item(ctx.db, ctx.workspace_id, item_id)
    targets = [t for t in config.get("targets") or [] if isinstance(t, dict)]
    if not targets:
        raise NodeError("generate variants needs targets [{platform, format}]")
    bad = [f"{t.get('platform')}/{t.get('format')}" for t in targets if not support_of(t.get("platform"), t.get("format"))]
    if bad:
        raise NodeError(f"unsupported variant targets: {', '.join(bad)}")
    specs = {f"{t['platform']}:{t['format']}": {
        "agent": "repurposer", "action": "adapt", "budget_usd": config.get("budget_usd"),
        "message": f"Adapt '{item.title}' for {t['platform']} {t['format']}",
        "inputs": {"content_id": str(item.id), "brand_id": str(item.brand_id), "target_platform": t["platform"],
                   "platform": t["platform"], "format": t["format"], "social_account_id": t.get("social_account_id")}}
        for t in targets}
    res = await ctx.ai_runs(specs, timeout_minutes=_timeout(config))
    variants = await _variants_of(ctx, item_id)
    wanted = {t["platform"] for t in targets}
    chosen = [v for v in variants if getattr(v.platform, "value", v.platform) in wanted]
    return {"content_item_id": str(item_id), "variant_ids": [str(v.id) for v in chosen],
            "variants": [{"id": str(v.id), "platform": getattr(v.platform, "value", v.platform),
                          "format": getattr(v.format, "value", v.format)} for v in chosen],
            "ai_run_ids": [r.get("ai_run_id") for r in res.values()],
            "cost_usd": round(sum(float(r.get("cost_usd") or 0) for r in res.values()), 6)}


# ---------------------------------------------------------------------------------------------------------- image
async def _image(ctx: NodeContext, config: dict[str, Any]) -> dict[str, Any]:
    from sqlalchemy import func

    from app.models.platform import UsageLedger
    from app.services.media_service import MediaService
    st = ctx.state
    if not st.get("media_asset_ids"):
        ctx.remaining_budget(None)
        assets = await MediaService.generate_image(ctx.db, ctx.require_actor(), ctx.brand_id, str(config.get("prompt") or ""),
                                                   size=str(config.get("size") or "1024x1024"), n=int(config.get("n") or 1))
        st["media_asset_ids"] = [str(a.id) for a in assets]
        if config.get("content_item_id"):
            for a in assets:
                await MediaService.attach_to_content(ctx.db, ctx.require_actor(), a.id,
                                                     content_item_id=as_uuid(config["content_item_id"], "content_item_id"))
    ids = [as_uuid(x) for x in st["media_asset_ids"]]
    cost = float((await ctx.db.execute(select(func.coalesce(func.sum(UsageLedger.cost_usd), 0)).where(
        UsageLedger.workspace_id == ctx.workspace_id, UsageLedger.ref_type == "media_asset",
        UsageLedger.ref_id.in_(ids)))).scalar_one() or 0)
    ctx.add_cost(cost, "image")
    return {"media_asset_ids": [str(i) for i in ids], "count": len(ids), "cost_usd": cost}


# ---------------------------------------------------------------------------------------------------------- report
async def _report(ctx: NodeContext, config: dict[str, Any]) -> dict[str, Any]:
    from app.content import _compat
    from app.workflows.nodes.action import create_report
    kind = str(config.get("report_kind") or "weekly_performance")
    if _compat.optional_attr("app.services.report_service", "ReportService") is not None:
        inputs = dict(config.get("inputs") or {})
        return await create_report(ctx, {"kind": kind, "title": config.get("title"), "instructions": config.get("instructions"),
                                         "period_start": inputs.get("period_start"), "period_end": inputs.get("period_end"),
                                         "options": {k: v for k, v in inputs.items() if k not in ("period_start", "period_end")}})
    inputs = {"kind": kind, "inputs": config.get("inputs") or {}, "brand_id": str(ctx.brand_id) if ctx.brand_id else None,
              "automation_run_id": str(ctx.run.id)}
    res = await ctx.ai_run("report", agent="report", action="compose", inputs=inputs,
                           message=f"Compose a {kind} report", budget_usd=config.get("budget_usd"),
                           timeout_minutes=_timeout(config))
    rep = deliverable(res)
    return {"report": rep, "report_id": (rep or {}).get("report_id") if isinstance(rep, dict) else None,
            "ai_run_id": res.get("ai_run_id"), "cost_usd": res.get("cost_usd")}

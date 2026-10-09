"""action — built-in deterministic service actions (WRITE_INTERNAL):

* ``content.set_status``   {content_item_id, status: draft|needs_review|archived, comment?} (never approves/rejects)
* ``ideas.add_to_planner`` {idea_ids, week? ("2026-W42"; default: current ISO week in the brand timezone), campaign_id?}
  → tags ``content_ideas.evidence.planner_week`` and emits IDEAS_ADDED
* ``competitors.sync``     {competitor_ids?} (default: every active competitor of the brand) → sync jobs
* ``report.generate``      {kind (weekly_performance|competitor|…), title?, period_start?, period_end?, recipients?,
  options?} → ``ReportService.create`` (built inline; step error "not available" when the service is absent)
* ``memory.write``         {text, kind?=note, importance?=0.6}
* ``trends.scan``          {window_days?} → TrendService.scan (deterministic signals)
"""
from __future__ import annotations

import re
from collections.abc import Awaitable, Callable
from datetime import date, datetime
from typing import Any
from zoneinfo import ZoneInfo

from sqlalchemy import select

from app.core.errors import ProblemError
from app.core.events import emit
from app.workflows.nodes.base import (
    NodeContext,
    NodeError,
    as_uuid,
    as_uuid_list,
    jsonable,
    problem_message,
    utcnow,
)

SETTABLE = {"draft", "needs_review", "archived"}
WEEK_RE = re.compile(r"^\d{4}-W(0[1-9]|[1-4]\d|5[0-3])$")


async def _audit(ctx: NodeContext, action: str, target_type: str, target_id: Any, after: Any = None) -> None:
    try:
        from app.services.audit_service import audit
        async with ctx.db.begin_nested():
            await audit(ctx.db, {"type": "system", "id": f"automation:{ctx.workflow.id}", "workspace_id": str(ctx.workspace_id)},
                        action, target_type, target_id, after=jsonable(after))
    except Exception:  # noqa: BLE001 - audit never breaks the action
        pass


async def set_status(ctx: NodeContext, p: dict[str, Any]) -> dict[str, Any]:
    from app.services.content_service import ContentService
    status = str(p.get("status") or "")
    if status not in SETTABLE:
        raise NodeError(f"content.set_status can set {', '.join(sorted(SETTABLE))} (approval requires an approve node)")
    item = await ContentService.transition(ctx.db, ctx.require_actor(), as_uuid(p.get("content_item_id"), "content_item_id"),
                                           status, p.get("comment") or f"automation {ctx.workflow.name}")
    return {"content_item_id": str(item.id), "status": getattr(item.status, "value", item.status)}


def current_week(tz: str | None) -> str:
    try:
        zone = ZoneInfo(tz or "UTC")
    except Exception:  # noqa: BLE001
        zone = ZoneInfo("UTC")
    y, w, _ = datetime.now(zone).isocalendar()
    return f"{y}-W{w:02d}"


async def add_to_planner(ctx: NodeContext, p: dict[str, Any]) -> dict[str, Any]:
    from app.models.content import Campaign
    from app.services.content_service import ContentService
    ids = as_uuid_list(p.get("idea_ids") if p.get("idea_ids") is not None else p.get("ideas"), "idea_ids")
    if not ids:
        return {"idea_ids": [], "count": 0, "planner_week": None, "note": "no ideas to add"}
    week = str(p.get("week") or current_week((ctx.brand or {}).get("timezone")))
    if not WEEK_RE.match(week):
        raise NodeError(f"week must look like 2026-W42 (got {week!r})")
    campaign_id = as_uuid(p["campaign_id"], "campaign_id") if p.get("campaign_id") else None
    if campaign_id is not None:
        ok = (await ctx.db.execute(select(Campaign.id).where(Campaign.id == campaign_id,
                                                             Campaign.workspace_id == ctx.workspace_id))).scalar_one_or_none()
        if ok is None:
            raise NodeError("campaign not found")
    done, brand_id = [], None
    for iid in ids:
        idea = await ContentService.get_idea(ctx.db, ctx.workspace_id, iid, for_update=True)
        idea.evidence = {**(idea.evidence or {}), "planner_week": week, "planner_added_at": utcnow().isoformat(),
                         "automation_run_id": str(ctx.run.id), "workflow_id": str(ctx.workflow.id)}
        if campaign_id is not None:
            idea.campaign_id = campaign_id
        brand_id = idea.brand_id
        done.append(str(idea.id))
    await ctx.db.flush()
    await emit(ctx.db, "IDEAS_ADDED", {"idea_ids": done, "planner_week": week, "brand_id": str(brand_id) if brand_id else None,
                                       "workflow_id": str(ctx.workflow.id), "run_id": str(ctx.run.id)},
               workspace_id=ctx.workspace_id, actor={"type": "system", "id": f"automation:{ctx.workflow.id}"})
    await _audit(ctx, "ideas.add_to_planner", "automation_run", ctx.run.id, {"idea_ids": done, "planner_week": week})
    return {"idea_ids": done, "count": len(done), "planner_week": week}


async def competitors_sync(ctx: NodeContext, p: dict[str, Any]) -> dict[str, Any]:
    from app.models.competitor import Competitor
    from app.services.competitor_service import CompetitorService
    ids = as_uuid_list(p.get("competitor_ids"), "competitor_ids")
    q = select(Competitor.id).where(Competitor.workspace_id == ctx.workspace_id, Competitor.status == "active")
    if ids:
        q = q.where(Competitor.id.in_(ids))
    elif ctx.brand_id:
        q = q.where(Competitor.brand_id == ctx.brand_id)
    if ctx.state.get("synced"):
        return ctx.state["synced"]
    comp_ids = list((await ctx.db.execute(q)).scalars().all())
    profiles, jobs = 0, 0
    for cid in comp_ids:
        job_ids, prof_ids = await CompetitorService.request_sync(ctx.db, ctx.workspace_id, cid)   # commits
        profiles += len(prof_ids)
        jobs += len([j for j in job_ids if j is not None])
    res = {"competitors": len(comp_ids), "profiles": profiles, "jobs_enqueued": jobs,
           "competitor_ids": [str(c) for c in comp_ids]}
    ctx.state["synced"] = res
    return res


def _date(v: Any) -> date | None:
    if v in (None, ""):
        return None
    if isinstance(v, date):
        return v
    try:
        return date.fromisoformat(str(v)[:10])
    except ValueError as e:
        raise NodeError(f"invalid date {v!r} (expected YYYY-MM-DD)") from e


async def create_report(ctx: NodeContext, p: dict[str, Any]) -> dict[str, Any]:
    """``ReportService.create`` (deterministic data pack rendered inline; optional AI narrative) — idempotent per step."""
    from app.content import _compat
    if ctx.state.get("report"):
        return ctx.state["report"]
    cls = _compat.optional_attr("app.services.report_service", "ReportService")
    if cls is None or not hasattr(cls, "create"):
        raise NodeError("report generation is not available in this build (ReportService is not installed)")
    kinds = _compat.optional_attr("app.services.report_service", "REPORT_KINDS") or ()
    kind = str(p.get("kind") or "weekly_performance")
    if kinds and kind not in kinds:
        raise NodeError(f"report kind must be one of {', '.join(kinds)}")
    brand_id = as_uuid(p["brand_id"], "brand_id") if p.get("brand_id") else ctx.require_brand()
    options = dict(p.get("options") or {})
    if p.get("instructions"):
        options["instructions"] = p["instructions"]
    rep = await cls.create(ctx.db, ctx.require_actor(), kind, brand_id, _date(p.get("period_start")), _date(p.get("period_end")),
                           p.get("recipients"), p.get("title"), options=options or None, enqueue=False,
                           automation_run_id=ctx.run.id)
    content = rep.content or {}
    if content.get("status") == "failed":
        raise NodeError(f"report generation failed: {content.get('error')}", {"report_id": str(rep.id)})
    out = {"report_id": str(rep.id), "title": rep.title, "kind": rep.kind, "status": content.get("status"),
           "summary": content.get("summary"), "period": content.get("period"),
           "narrative_status": content.get("narrative_status")}
    ctx.state["report"] = jsonable(out)
    return ctx.state["report"]


async def report_generate(ctx: NodeContext, p: dict[str, Any]) -> dict[str, Any]:
    return await create_report(ctx, p)


async def memory_write(ctx: NodeContext, p: dict[str, Any]) -> dict[str, Any]:
    from app.agents.orchestrator.memory import MemoryService
    text = str(p.get("text") or "").strip()
    if not text:
        raise NodeError("memory.write needs text")
    res = await MemoryService().remember(ctx.db, ctx.workspace_id, str(p.get("kind") or "note"), text[:8000],
                                         brand_id=ctx.brand_id, importance=float(p.get("importance") or 0.6),
                                         source_ref={"automation_run_id": str(ctx.run.id), "workflow_id": str(ctx.workflow.id)})
    return jsonable(res)


async def trends_scan(ctx: NodeContext, p: dict[str, Any]) -> dict[str, Any]:
    from app.services.trend_service import TrendService
    res = await TrendService.scan(ctx.db, ctx.workspace_id, ctx.require_brand(), window_days=int(p.get("window_days") or 14),
                                  actor={"type": "system", "id": f"automation:{ctx.workflow.id}"})
    return {k: res.get(k) for k in ("detected", "updated", "signals", "terms_scored", "top_terms")}


HANDLERS: dict[str, Callable[[NodeContext, dict[str, Any]], Awaitable[dict[str, Any]]]] = {
    "content.set_status": set_status, "ideas.add_to_planner": add_to_planner, "competitors.sync": competitors_sync,
    "report.generate": report_generate, "memory.write": memory_write, "trends.scan": trends_scan,
}


async def run(ctx: NodeContext, config: dict[str, Any]) -> dict[str, Any]:
    action = str(config.get("action") or "")
    fn = HANDLERS.get(action)
    if fn is None:
        raise NodeError(f"unknown action {action!r}")
    params = config.get("params") or {}
    if ctx.dry_run:
        return ctx.simulated(action=action, params=params)
    try:
        result = await fn(ctx, params)
    except ProblemError as e:
        raise NodeError(f"{action}: {problem_message(e)}") from e
    except (ValueError, LookupError) as e:
        raise NodeError(f"{action}: {e}") from e
    return {"action": action, "result": result, **{k: v for k, v in result.items() if k not in ("action", "result")}}

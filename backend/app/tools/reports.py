"""Report tools for the ``report`` agent (doc 06 §13, doc 13 §13.6).

``reports.get_data`` (READ) returns the deterministic data pack for a kind/period (or the pack stored on a report),
``reports.render`` (READ) previews Markdown for composed sections, ``reports.save`` (WRITE_INTERNAL) stores the composed
narrative on the report named by the task inputs (``report_id`` / ``competitor_report_id``) or creates a ``custom`` report.
"""
from __future__ import annotations

from datetime import date, timedelta
from typing import Any
from uuid import UUID

from pydantic import BaseModel, Field

from app.tools.registry import SideEffect, ToolContext, tool

AI_ROLES = {"approver", "editor", "admin", "owner"}
KINDS = ("weekly_performance", "competitor", "competitor_opportunities", "campaign", "research_brief", "custom")


class SectionItem(BaseModel):
    heading: str
    markdown: str
    charts: list[dict[str, Any]] = Field(default_factory=list)
    sources: list[str] = Field(default_factory=list)


def _uuid(v: Any) -> UUID | None:
    try:
        return UUID(str(v)) if v else None
    except ValueError:
        return None


async def _run_inputs(ctx: ToolContext) -> dict[str, Any]:
    if ctx.db is None or ctx.run_id is None:
        return {}
    from app.models.ai import AIRun
    run = await ctx.db.get(AIRun, ctx.run_id)
    return ((run.input or {}).get("inputs") or {}) if run is not None else {}


def _compact(pack: dict[str, Any], limit_chars: int = 40_000) -> dict[str, Any]:
    """Keep the pack within the agent's context: drop raw snapshot metrics first, then trim long lists."""
    import json
    out = dict(pack)
    if len(json.dumps(out, default=str)) <= limit_chars:
        return out
    out.pop("snapshots", None)
    for key in ("research", "competitors", "recommendations", "insights", "upcoming", "accounts", "campaigns"):
        if isinstance(out.get(key), list):
            out[key] = out[key][:8]
    return out


@tool("reports.get_data", side_effect=SideEffect.READ, timeout_s=60, idempotent=True)
async def reports_get_data(ctx: ToolContext, kind: str | None = None, report_id: str | None = None, brand_id: str | None = None,
                           period_start: str | None = None, period_end: str | None = None, period_days: int | None = None) -> dict:
    """Deterministic data pack for a report kind (weekly_performance, competitor, competitor_opportunities, campaign,
    research_brief, custom): KPIs vs previous period with coverage/basis, accounts, top posts, insights, recommendations,
    competitor deltas, upcoming schedule, research runs and sources. Every number you write must come from here."""
    from app.models.platform import Report
    from app.services.report_service import ReportService
    if ctx.db is None:
        return {"error": "no session"}
    inputs = await _run_inputs(ctx)
    rid = _uuid(report_id or inputs.get("report_id"))
    if rid is not None:
        report = await ctx.db.get(Report, rid)
        if report is None or report.workspace_id != ctx.workspace_id:
            return {"error": "report not found"}
        data = (report.content or {}).get("data")
        if not isinstance(data, dict):
            data = await ReportService.build_pack(ctx.db, ctx.workspace_id, report.kind, report.brand_id, report.period_start,
                                                  report.period_end, options=(report.content or {}).get("options"))
        return {"report_id": str(report.id), "kind": report.kind, "title": report.title, "data": _compact(data)}
    kind = kind or inputs.get("kind") or "custom"
    if kind not in KINDS:
        kind = {"single": "competitor", "comparison": "competitor", "monitoring": "competitor",
                "opportunities": "competitor_opportunities"}.get(kind, "custom")
    bid = _uuid(brand_id) or ctx.brand_id
    try:
        end = date.fromisoformat(period_end) if period_end else None
        start = date.fromisoformat(period_start) if period_start else None
    except ValueError:
        return {"error": "period_start/period_end must be ISO dates"}
    days = int(period_days or inputs.get("period_days") or 0)
    if start is None and end is None and days:
        end = date.today()
        start = end - timedelta(days=max(1, min(days, 366)) - 1)
    pack = await ReportService.build_pack(ctx.db, ctx.workspace_id, kind, bid, start, end)
    return {"kind": kind, "data": _compact(pack)}


@tool("reports.render", side_effect=SideEffect.READ, timeout_s=15, idempotent=True)
async def reports_render(ctx: ToolContext, title: str, summary: str, sections: list[SectionItem]) -> dict:
    """Render composed sections to Markdown (preview of what readers will see; HTML is produced when saved)."""
    from app.services import report_render as R
    secs = [R.section(s["heading"], s["markdown"], charts=s.get("charts"), sources=s.get("sources"), origin="ai")
            for s in ((x.model_dump() if hasattr(x, "model_dump") else dict(x)) for x in sections or [])]
    md = R.render_markdown(title, summary, secs, {})
    return {"markdown": md[:20000], "chars": len(md), "sections": len(secs)}


@tool("reports.save", side_effect=SideEffect.WRITE_INTERNAL, roles=AI_ROLES, timeout_s=30, idempotent=True)
async def reports_save(ctx: ToolContext, title: str, summary: str, sections: list[SectionItem], kind: str | None = None,
                       report_id: str | None = None) -> dict:
    """Save the composed report (title, summary, sections with markdown/charts/sources). Attaches it to the report this
    task was started for; otherwise creates a new report. Returns report_id."""
    from types import SimpleNamespace

    from app.models.ai import AIRun
    from app.services.report_service import ReportService
    if ctx.db is None:
        return {"error": "no session"}
    output = {"title": title, "summary": summary,
              "sections": [s.model_dump() if hasattr(s, "model_dump") else dict(s) for s in sections or []]}
    run = await ctx.db.get(AIRun, ctx.run_id) if ctx.run_id else None
    inputs = ((run.input or {}).get("inputs") or {}) if run is not None else {}
    target = report_id or inputs.get("report_id")
    if run is not None and (target or inputs.get("competitor_report_id")):
        res = await ReportService.apply_agent_output(ctx.db, run, output, report_id=target)
        if res.get("applied"):
            return {"report_id": res.get("report_id") or res.get("competitor_report_id"), "saved": True}
        return {"error": res.get("reason", "not saved")}
    if ctx.brand_id is None:
        return {"error": "brand_id required to create a report"}
    from app.models.identity import User
    user = await ctx.db.get(User, ctx.user_id) if ctx.user_id else None
    member = SimpleNamespace(user=user, workspace_id=ctx.workspace_id, role=ctx.role)
    k = kind if kind in KINDS else "custom"
    report = await ReportService.create(ctx.db, member, k, ctx.brand_id, title=title, enqueue=True, use_ai=False)
    holder = run or SimpleNamespace(id=ctx.run_id, workspace_id=ctx.workspace_id, input={}, result=None)
    await ReportService.apply_agent_output(ctx.db, holder, output, report_id=report.id)
    return {"report_id": str(report.id), "saved": True, "status": (report.content or {}).get("status")}

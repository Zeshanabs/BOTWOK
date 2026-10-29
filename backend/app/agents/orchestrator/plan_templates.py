"""Plan templates per intent (doc 05 §5.2.3): deterministic seeds the planner adapts; also the no-LLM fallback plan."""
from __future__ import annotations

from typing import Any

from app.agents.schemas.orchestrator import Plan, PlanTask

MAX_FAN_OUT = 10
# Per-task cost estimates by tier used by PlanValidator when a task sets no budget.
TIER_COST_USD = {"cheap": 0.02, "balanced": 0.08, "powerful": 0.25}


def _t(id_: str, agent: str, action: str, label: str, inputs: dict[str, Any] | None = None, depends_on: list[str] | None = None,
       fan_out: str | None = None, optional: bool = False, requires_approval: bool = False) -> PlanTask:
    return PlanTask(id=id_, agent=agent, action=action, label=label, inputs=inputs or {}, depends_on=depends_on or [],
                    fan_out=fan_out, optional=optional, requires_approval=requires_approval)


def _count(entities: dict[str, Any], default: int = 5, cap: int = MAX_FAN_OUT) -> int:
    try:
        return max(1, min(int(entities.get("count") or default), cap))
    except (TypeError, ValueError):
        return default


def _topic(entities: dict[str, Any], message: str) -> str:
    return str(entities.get("topic") or message)


def _platforms(entities: dict[str, Any]) -> list[str]:
    p = entities.get("platforms") or ([entities["platform"]] if entities.get("platform") else [])
    return [str(x) for x in p]


# Each template: (entities, message, prev) -> (tasks, last_task_id, deliverables)
def research_topic(e: dict[str, Any], msg: str, prev: str | None, n: int) -> tuple[list[PlanTask], str, list[str]]:
    tid = f"t{n}"
    return ([_t(tid, "research", "research", "Researching web",
                {"query": _topic(e, msg), "scope": e.get("scope") or ["web", "news"], "depth": e.get("depth") or "standard",
                 "recency_days": e.get("recency_days") or 90}, depends_on=[prev] if prev else [])], tid, [f"{tid}.summary", f"{tid}.key_findings"])


def find_news(e: dict[str, Any], msg: str, prev: str | None, n: int) -> tuple[list[PlanTask], str, list[str]]:
    tid = f"t{n}"
    return ([_t(tid, "research", "research", "Checking industry news",
                {"query": _topic(e, msg), "scope": ["news"], "depth": "quick", "recency_days": e.get("recency_days") or 14},
                depends_on=[prev] if prev else [])], tid, [f"{tid}.key_findings"])


def research_competitors(e: dict[str, Any], msg: str, prev: str | None, n: int) -> tuple[list[PlanTask], str, list[str]]:
    t1, t2, t3, t4, t5 = (f"t{n + i}" for i in range(5))
    tasks = [
        _t(t1, "competitor_intel", "resolve_competitors", "Resolving competitors", {"limit": _count(e, 5), "names": e.get("competitors") or []}),
        _t(t2, "research", "research", "Researching competitor sites", {"query": f"{t1}.competitors[*].website", "scope": ["web", "competitor_sites"],
                                                                      "depth": "standard"}, depends_on=[t1], fan_out=f"{t1}.competitors"),
        _t(t3, "social_listening", "collect_public_posts", "Checking competitors on social", {"targets": f"{t1}.competitors[*].handles"},
           depends_on=[t1], fan_out=f"{t1}.competitors", optional=True),
        _t(t4, "competitor_intel", "analyze", "Analyzing competitors", {"competitor": "item", "sources_from": [t2, t3]},
           depends_on=[t2, t3], fan_out=f"{t1}.competitors"),
        _t(t5, "competitor_intel", "find_gaps", "Finding opportunities", {"analysis_from": t4, "brand": "$brand"}, depends_on=[t4]),
    ]
    return tasks, t5, [f"{t4}", f"{t5}.gaps"]


def analyze_competitor_content(e: dict[str, Any], msg: str, prev: str | None, n: int) -> tuple[list[PlanTask], str, list[str]]:
    t1, t2, t3 = (f"t{n + i}" for i in range(3))
    tasks = [
        _t(t1, "competitor_intel", "resolve_competitors", "Resolving competitors", {"limit": _count(e, 3), "names": e.get("competitors") or []}),
        _t(t2, "competitor_intel", "analyze", "Analyzing competitor content", {"competitor": "item"}, depends_on=[t1], fan_out=f"{t1}.competitors"),
        _t(t3, "competitor_intel", "compare", "Comparing competitors", {"analyses_from": t2}, depends_on=[t2]),
    ]
    return tasks, t3, [f"{t3}", f"{t2}"]


def find_trends(e: dict[str, Any], msg: str, prev: str | None, n: int) -> tuple[list[PlanTask], str, list[str]]:
    t1, t2, t3 = (f"t{n + i}" for i in range(3))
    tasks = [
        _t(t1, "research", "research", "Researching web", {"query": _topic(e, msg), "scope": ["web", "news"], "depth": "quick",
                                                          "recency_days": e.get("window_days") or 14}),
        _t(t2, "social_listening", "search_topic", "Listening on social", {"query": _topic(e, msg), "platforms": _platforms(e) or None,
                                                                          "since_days": e.get("window_days") or 14}, optional=True),
        _t(t3, "trend", "detect", "Finding trends", {"industry": _topic(e, msg), "window_days": e.get("window_days") or 14,
                                                     "sources_from": [t1, t2]}, depends_on=[t1, t2]),
    ]
    return tasks, t3, [f"{t3}.trends"]


def strategy_recommendation(e: dict[str, Any], msg: str, prev: str | None, n: int) -> tuple[list[PlanTask], str, list[str]]:
    tid = f"t{n}"
    inputs: dict[str, Any] = {"goals": e.get("goals") or msg, "platforms": _platforms(e), "horizon": e.get("period") or "quarter", "brand": "$brand"}
    if prev:
        inputs["evidence_from"] = prev
    return ([_t(tid, "strategy", "build_strategy", "Building strategy", inputs, depends_on=[prev] if prev else [])], tid, [tid])


def generate_ideas(e: dict[str, Any], msg: str, prev: str | None, n: int) -> tuple[list[PlanTask], str, list[str]]:
    tid = f"t{n}"
    inputs: dict[str, Any] = {"count": _count(e, 10, cap=30), "pillars": e.get("pillars"), "platforms": _platforms(e), "brief": msg}
    if prev:
        inputs["evidence_from"] = prev
    return ([_t(tid, "ideation", "generate", "Generating ideas", inputs, depends_on=[prev] if prev else [])], tid, [f"{tid}.ideas"])


def write_post(e: dict[str, Any], msg: str, prev: str | None, n: int) -> tuple[list[PlanTask], str, list[str]]:
    count = _count(e, 1)
    platform = (_platforms(e) or ["linkedin"])[0]
    tasks: list[PlanTask] = []
    i = n
    if prev:
        sel = f"t{i}"
        tasks.append(_t(sel, "strategy", "select_opportunities", "Selecting opportunities", {"candidates_from": prev, "n": count, "platform": platform},
                        depends_on=[prev]))
        i += 1
        writer_inputs = {"brief": {"opportunity": "item", "platform": platform, "format": e.get("format") or "text",
                                   "content_type": e.get("content_type"), "cta_goal": e.get("cta_goal"), "user_request": msg}}
        fan = f"{sel}.selected"
        dep = [sel]
    else:
        writer_inputs = {"brief": {"prompt": msg, "topic": e.get("topic"), "platform": platform, "format": e.get("format") or "text",
                                   "content_type": e.get("content_type"), "cta_goal": e.get("cta_goal"), "count_index": "index"}}
        fan = None
        dep = []
        if count > 1:
            writer_inputs["brief"]["variation"] = "item"
            writer_inputs["_fan_out_items"] = list(range(1, count + 1))
            fan = "$inputs._fan_out_items"
    tw, tc, tf = f"t{i}", f"t{i + 1}", f"t{i + 2}"
    tasks += [
        _t(tw, "writer", "write", "Generating posts" if count > 1 else "Writing post", writer_inputs, depends_on=dep, fan_out=fan),
        _t(tc, "critic", "critique", "Quality checking", {"draft_from": tw, "brief": msg}, depends_on=[tw], fan_out=f"{tw}.items" if fan else None),
        _t(tf, "fact_check", "check", "Fact checking", {"draft_from": tw, "critique_from": tc}, depends_on=[tw, tc],
           fan_out=f"{tw}.items" if fan else None, optional=True),
    ]
    return tasks, tf, [tw, tc, tf]


def repurpose(e: dict[str, Any], msg: str, prev: str | None, n: int) -> tuple[list[PlanTask], str, list[str]]:
    tid = f"t{n}"
    platforms = _platforms(e) or ["x", "instagram"]
    inputs = {"content_id": e.get("content_id"), "target_platform": "item", "format": e.get("format"), "_fan_out_items": platforms}
    if prev:
        inputs["content_from"] = prev
    return ([_t(tid, "repurposer", "adapt", "Adapting for platforms", inputs, depends_on=[prev] if prev else [], fan_out="$inputs._fan_out_items")],
            tid, [tid])


def generate_media(e: dict[str, Any], msg: str, prev: str | None, n: int) -> tuple[list[PlanTask], str, list[str]]:
    t1, t2 = f"t{n}", f"t{n + 1}"
    inputs = {"content_id": e.get("content_id"), "brief": msg}
    if prev:
        inputs["content_from"] = prev
    return ([_t(t1, "visual", "concept", "Designing visual concept", inputs, depends_on=[prev] if prev else []),
             _t(t2, "visual", "generate_image", "Generating image", {"concept_from": t1, "content_id": e.get("content_id"), "style": e.get("style")},
                depends_on=[t1])], t2, [t1, f"{t2}.assets"])


def build_calendar(e: dict[str, Any], msg: str, prev: str | None, n: int) -> tuple[list[PlanTask], str, list[str]]:
    tid = f"t{n}"
    inputs = {"period": e.get("period") or "next 2 weeks", "slots": e.get("count") or 10, "platforms": _platforms(e), "brand": "$brand"}
    if prev:
        inputs["candidates_from"] = prev
    return ([_t(tid, "strategy", "plan_calendar", "Planning calendar", inputs, depends_on=[prev] if prev else [])], tid, [f"{tid}.slots"])


def schedule(e: dict[str, Any], msg: str, prev: str | None, n: int) -> tuple[list[PlanTask], str, list[str]]:
    tid = f"t{n}"
    inputs = {"variant_ids": e.get("variant_ids") or [], "content_id": e.get("content_id"), "when": e.get("deadline") or e.get("period"),
              "platforms": _platforms(e), "request": msg}
    if prev:
        inputs["content_from"] = prev
    return ([_t(tid, "strategy", "propose_schedule", "Proposing schedule (needs approval)", inputs, depends_on=[prev] if prev else [],
                requires_approval=True)], tid, [tid])


def analyze_performance(e: dict[str, Any], msg: str, prev: str | None, n: int) -> tuple[list[PlanTask], str, list[str]]:
    tid = f"t{n}"
    return ([_t(tid, "performance_analyst", "analyze", "Analyzing performance",
                {"period": e.get("period") or "last_30_days", "dimensions": e.get("dimensions") or ["pillar", "format", "platform", "hour"],
                 "platforms": _platforms(e)}, depends_on=[prev] if prev else [])], tid, [f"{tid}.insights", f"{tid}.recommendations"])


def report(e: dict[str, Any], msg: str, prev: str | None, n: int) -> tuple[list[PlanTask], str, list[str]]:
    tid = f"t{n}"
    kind = e.get("report_kind") or ("weekly_performance" if "performance" in msg.lower() or "weekly" in msg.lower() else "custom")
    inputs: dict[str, Any] = {"kind": kind, "audience": e.get("audience") or "team", "length": e.get("length") or "standard",
                              "period": e.get("period"), "request": msg}
    if prev:
        inputs["from"] = [prev]
    return ([_t(tid, "report", "compose", "Composing report", inputs, depends_on=[prev] if prev else [])], tid, [f"{tid}"])


TEMPLATES = {
    "research_topic": research_topic, "find_news": find_news, "research_competitors": research_competitors,
    "analyze_competitor_content": analyze_competitor_content, "find_trends": find_trends,
    "strategy_recommendation": strategy_recommendation, "generate_ideas": generate_ideas, "write_post": write_post,
    "repurpose": repurpose, "generate_media": generate_media, "build_calendar": build_calendar, "schedule": schedule,
    "publish": schedule, "analyze_performance": analyze_performance, "report": report,
}
NO_PLAN_INTENTS = {"smalltalk", "question_about_data", "configure_automation", "unknown"}


def compose_plan(intents: list[str], entities: dict[str, Any], message: str) -> Plan | None:
    """Chain templates for the routed intents in order. Returns None when no template applies."""
    tasks: list[PlanTask] = []
    deliverables: list[str] = []
    approval_points: list[str] = []
    prev: str | None = None
    n = 1
    for intent in intents:
        fn = TEMPLATES.get(intent)
        if fn is None:
            continue
        new_tasks, last, dels = fn(entities or {}, message, prev, n)
        tasks.extend(new_tasks)
        deliverables.extend(dels)
        approval_points.extend(t.id for t in new_tasks if t.requires_approval)
        prev = last
        n += len(new_tasks)
    if not tasks:
        return None
    return Plan(goal=message[:300], tasks=tasks, approval_points=approval_points, deliverables=deliverables)


def template_hints(intents: list[str], entities: dict[str, Any], message: str) -> list[dict[str, Any]]:
    plan = compose_plan(intents, entities, message)
    return [t.model_dump() for t in plan.tasks] if plan else []

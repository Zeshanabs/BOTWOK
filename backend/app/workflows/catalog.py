"""Node type catalog (doc 14 §14.2): config JSON schema, side-effect class, outputs and branches per node type.

Served by ``GET /automations/node-types`` (the builder generates each node's config panel from ``config_schema``).
String config values may contain ``{{ }}`` templates (rendered over the run context before the node runs) except
the ``raw_fields`` (expressions evaluated by the node itself).
"""
from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any

PLATFORMS = ["facebook", "instagram", "threads", "linkedin", "x", "tiktok", "youtube", "pinterest", "gbp"]
FORMATS = ["text", "image", "carousel", "video", "short_video", "story", "article", "poll", "document", "link"]
CONTENT_TYPES = ["educational", "authority", "promotional", "engagement", "storytelling", "industry_news", "case_study",
                 "behind_the_scenes", "ugc", "thought_leadership", "announcement"]
RESEARCH_SCOPES = ["web", "news", "rss", "competitor_sites", "social", "instagram", "x", "threads", "youtube", "keywords"]
ROLES = ["owner", "admin", "editor", "approver", "viewer"]

# Event names (doc 00 §8) a trigger.event node may listen to (+ IDEAS_ADDED from doc 31 Scenario B).
TRIGGER_EVENTS = [
    "CONTENT_CREATED", "CONTENT_UPDATED", "CONTENT_STATUS_CHANGED", "VARIANT_CREATED",
    "APPROVAL_REQUESTED", "CONTENT_APPROVED", "CONTENT_REJECTED",
    "POST_SCHEDULED", "POST_RESCHEDULED", "POST_CANCELLED", "POST_PAUSED",
    "PUBLISH_STARTED", "PUBLISH_SUCCESS", "PUBLISH_FAILED", "PUBLISH_DEAD_LETTERED",
    "ANALYTICS_SYNC_STARTED", "ANALYTICS_UPDATED", "ANALYTICS_SYNC_FAILED",
    "RESEARCH_STARTED", "RESEARCH_COMPLETED", "RESEARCH_FAILED",
    "COMPETITOR_ADDED", "COMPETITOR_UPDATED", "COMPETITOR_SNAPSHOT_TAKEN",
    "TREND_DETECTED", "TREND_UPDATED",
    "AI_RUN_COMPLETED", "AI_RUN_FAILED", "AI_ANALYSIS_COMPLETED", "RECOMMENDATION_CREATED",
    "SOCIAL_ACCOUNT_CONNECTED", "SOCIAL_ACCOUNT_TOKEN_EXPIRING", "SOCIAL_ACCOUNT_EXPIRED", "SOCIAL_ACCOUNT_REVOKED",
    "AUTOMATION_COMPLETED", "AUTOMATION_FAILED",
    "MEDIA_GENERATED", "MEDIA_PROCESSED", "BUDGET_THRESHOLD_REACHED", "BUDGET_EXCEEDED", "REPORT_GENERATED",
    "IDEAS_ADDED",
]

ACTIONS = ["content.set_status", "ideas.add_to_planner", "competitors.sync", "report.generate", "memory.write", "trends.scan"]
GENERATE_KINDS = ["ideas", "post", "variants", "image", "report"]


def _agents() -> list[str]:
    try:
        from app.agents.specs import SPECS
        return sorted(SPECS)
    except Exception:  # noqa: BLE001 - AI core optional
        return ["research", "social_listening", "competitor_intel", "trend", "strategy", "ideation", "writer",
                "repurposer", "visual", "critic", "fact_check", "performance_analyst", "report"]


def agent_actions() -> dict[str, list[str]]:
    try:
        from app.agents.specs import SPECS
        return {k: sorted(v.actions) for k, v in SPECS.items()}
    except Exception:  # noqa: BLE001
        return {}


ON_ERROR = {"type": "string", "enum": ["stop", "continue", "notify"],
            "description": "Override the workflow's on_error policy for this node"}
TEMPLATE_STR = {"type": "string", "description": "Text; may use {{ }} templates over the run context"}
ID_STR = {"type": "string", "description": "An id or a {{ }} template resolving to one"}
APPROVAL_MODE = {"type": "string", "enum": ["required", "auto_if_content_approved"], "default": "required",
                 "description": "required (default): pause for a human approval of this exact action; "
                                "auto_if_content_approved: proceed only when the content is already approved"}


@dataclass(frozen=True)
class NodeType:
    type: str
    category: str
    label: str
    description: str
    side_effect: str | None
    config_schema: dict[str, Any]
    outputs: dict[str, str]
    branches: tuple[str | None, ...] = (None, "error")
    raw_fields: tuple[str, ...] = ()
    requires_autonomous_actions: bool = False
    dry_run: str = "run"               # run | simulate
    yields: bool = False
    extra: dict[str, Any] = field(default_factory=dict)

    @property
    def is_trigger(self) -> bool:
        return self.type.startswith("trigger.")

    def public(self) -> dict[str, Any]:
        d = asdict(self)
        d["branches"] = [b for b in self.branches if b is not None]
        d["default_branch"] = None in self.branches
        d.pop("extra", None)
        return d


def _obj(props: dict[str, Any], required: list[str] | None = None, **kw: Any) -> dict[str, Any]:
    return {"type": "object", "properties": props, "required": required or [], "additionalProperties": False, **kw}


def _with_common(schema: dict[str, Any]) -> dict[str, Any]:
    props = dict(schema.get("properties") or {})
    props.setdefault("on_error", ON_ERROR)
    return {**schema, "properties": props}


def _build() -> dict[str, NodeType]:
    agents = _agents()
    nodes = [
        NodeType("trigger.cron", "trigger", "Schedule", "Fires on a cron expression or RRULE in a timezone.", None,
                 _obj({"cron": {"type": "string", "description": "5-field cron, e.g. '0 9 * * 1' (Mondays 09:00)"},
                       "rrule": {"type": "string", "description": "RFC 5545 RRULE, e.g. FREQ=WEEKLY;BYDAY=MO;BYHOUR=9"},
                       "timezone": {"type": "string", "description": "IANA timezone; defaults to the brand timezone"},
                       "misfire_grace_minutes": {"type": "integer", "minimum": 1, "maximum": 10080, "default": 60}},
                      anyOf=[{"required": ["cron"]}, {"required": ["rrule"]}]),
                 {"fired_at": "When the trigger fired (ISO)", "scheduled_for": "The scheduled slot (ISO)"},
                 branches=(None,)),
        NodeType("trigger.event", "trigger", "Event", "Fires when a platform event occurs and the filter matches.",
                 None,
                 _obj({"event": {"type": "string", "enum": TRIGGER_EVENTS},
                       "filter": {"type": "object", "description": "min_<field>/max_<field> bounds, list fields "
                                  "(any-of match) or exact values, e.g. {min_score: 80, kinds: ['news']}"},
                       "condition": {"type": "string", "description": "Optional boolean expression over the payload",
                                     "x-expression": True}}, ["event"]),
                 {"event": "Event name", "payload": "Event payload (also spread at the top level of trigger)"},
                 branches=(None,), raw_fields=("condition", "filter")),
        NodeType("trigger.webhook", "trigger", "Webhook", "Fires on POST /automations/{id}/webhook/{secret}.", None,
                 _obj({"schema": {"type": "object", "description": "JSON schema the request body must satisfy"}}),
                 {"body": "Request body (also spread at the top level of trigger)", "received_at": "ISO time"},
                 branches=(None,), raw_fields=("schema",)),
        NodeType("trigger.manual", "trigger", "Manual", "Started from the UI or API with an optional payload.", None,
                 _obj({"input_schema": {"type": "object", "description": "JSON schema for the run payload"}}),
                 {"input": "The payload given to POST /automations/{id}/run", "user_id": "Who started it"},
                 branches=(None,), raw_fields=("input_schema",)),
        NodeType("condition", "logic", "Condition", "Branches true/false on a sandboxed boolean expression.", None,
                 _with_common(_obj({"expression": {"type": "string", "minLength": 1, "x-expression": True,
                                                   "description": "e.g. trigger.score >= 80 and \"news\" in trigger.kinds"}},
                                   ["expression"])),
                 {"result": "Boolean result", "branch": "'true' or 'false'"},
                 branches=("true", "false", "error"), raw_fields=("expression",)),
        NodeType("ai_agent", "ai", "AI agent", "Runs one agent action through the orchestrator (tool mode).",
                 "per agent",
                 _with_common(_obj({"agent": {"type": "string", "enum": agents}, "action": {"type": "string", "minLength": 1},
                                    "inputs": {"type": "object"}, "message": TEMPLATE_STR,
                                    "budget_usd": {"type": "number", "minimum": 0.01, "maximum": 50},
                                    "timeout_minutes": {"type": "integer", "minimum": 1, "maximum": 1440, "default": 60}},
                                   ["agent", "action"])),
                 {"ai_run_id": "AI run id", "output": "The agent's structured output", "deliverables": "All deliverables",
                  "reasoning_summary": "Bullets", "cost_usd": "Run cost"}, yields=True),
        NodeType("research", "ai", "Research", "Starts a research run (search → fetch → extract → rank) and waits.",
                 "EXTERNAL_READ",
                 _with_common(_obj({"query": {"type": "string", "minLength": 2, "maxLength": 500},
                                    "scope": {"type": "array", "items": {"type": "string", "enum": RESEARCH_SCOPES},
                                              "maxItems": 8},
                                    "depth": {"type": "string", "enum": ["quick", "standard", "deep"]},
                                    "recency_days": {"type": "integer", "minimum": 1, "maximum": 3650},
                                    "domains_allow": {"type": "array", "items": {"type": "string"}},
                                    "domains_deny": {"type": "array", "items": {"type": "string"}},
                                    "timeout_minutes": {"type": "integer", "minimum": 1, "maximum": 1440, "default": 60}},
                                   ["query"])),
                 {"research_run_id": "Research run id", "summary": "Synthesis", "findings": "[{text, source_ids}]",
                  "topics": "Topics", "source_count": "Ranked sources", "sources": "Top sources", "cost_usd": "Cost"},
                 yields=True),
        NodeType("generate", "content", "Generate", "Generates ideas, a post, platform variants, an image or a report.",
                 "WRITE_INTERNAL / SPEND",
                 _with_common(_obj({"kind": {"type": "string", "enum": GENERATE_KINDS},
                                    "count": {"type": "integer", "minimum": 1, "maximum": 50},
                                    "from": {"description": "Evidence for ideas: {research_run_id, trend_ids, …}"},
                                    "pillars": {"type": "array", "items": {"type": "string"}},
                                    "platforms": {"type": "array", "items": {"type": "string", "enum": PLATFORMS}},
                                    "platform": {"type": "string", "enum": PLATFORMS},
                                    "format": {"type": "string", "enum": FORMATS},
                                    "idea": ID_STR, "prompt": TEMPLATE_STR, "title": TEMPLATE_STR,
                                    "content_type": {"type": "string", "enum": CONTENT_TYPES},
                                    "instructions": TEMPLATE_STR, "length": {"type": "string"},
                                    "source_ids": {"type": "array", "items": {"type": "string"}},
                                    "content_item_id": ID_STR,
                                    "targets": {"type": "array", "maxItems": 9, "items": _obj(
                                        {"platform": {"type": "string", "enum": PLATFORMS},
                                         "format": {"type": "string", "enum": FORMATS}}, ["platform", "format"])},
                                    "size": {"type": "string"}, "n": {"type": "integer", "minimum": 1, "maximum": 4},
                                    "report_kind": {"type": "string"}, "inputs": {"type": "object"},
                                    "budget_usd": {"type": "number", "minimum": 0.01, "maximum": 50},
                                    "timeout_minutes": {"type": "integer", "minimum": 1, "maximum": 1440, "default": 60}},
                                   ["kind"])),
                 {"ideas": "ideas: [{id,title,angle}]", "idea_ids": "ideas: ids", "content_item_id": "post",
                  "variant_id": "post: variant for the platform", "variant_ids": "post/variants",
                  "media_asset_ids": "image", "report": "report deliverable", "ai_run_id": "AI run id"}, yields=True),
        NodeType("transform", "logic", "Transform", "Maps values: Jinja template over the context, or a cheap-model "
                 "AI mapping.", None,
                 _with_common(_obj({"mode": {"type": "string", "enum": ["template", "ai"]},
                                    "template": {"description": "Any JSON; strings rendered as templates"},
                                    "input": {"description": "ai: data to transform"},
                                    "instructions": {"type": "string", "maxLength": 4000},
                                    "output_schema": {"type": "object"}}, ["mode"])),
                 {"value": "The mapped value (dict keys are also spread at the top level)"},
                 raw_fields=("output_schema",)),
        NodeType("approve", "control", "Approval", "Pauses the run until a human approves or rejects.", "APPROVAL",
                 _with_common(_obj({"approvers": _obj({"roles": {"type": "array", "items": {"type": "string", "enum": ROLES}},
                                                       "users": {"type": "array", "items": {"type": "string"}}}),
                                    "timeout_hours": {"type": "integer", "minimum": 1, "maximum": 720, "default": 72},
                                    "title": TEMPLATE_STR, "description": TEMPLATE_STR,
                                    "show": {"description": "What the approver sees (templated JSON)"},
                                    "content_item_id": {**ID_STR, "description": "Approve this content item (content "
                                                        "approval: approving moves it and its variants to approved)"}})),
                 {"decision": "approved|rejected|expired", "branch": "approved|rejected", "comment": "Decision comment",
                  "approval_id": "Approval id", "decided_by": "User id"},
                 branches=("approved", "rejected", "error"), dry_run="simulate", yields=True),
        NodeType("schedule", "publishing", "Schedule", "Schedules approved variants (fixed time, best time or next "
                 "free slot).", "APPROVAL",
                 _with_common(_obj({"variant": ID_STR, "variants": {"description": "List of variant ids (or template)"},
                                    "account": ID_STR, "platform": {"type": "string", "enum": PLATFORMS},
                                    "strategy": {"type": "string", "enum": ["fixed", "best_time", "next_slot"]},
                                    "at": {"type": "string", "description": "fixed: ISO datetime"},
                                    "window_days": {"type": "integer", "minimum": 1, "maximum": 60, "default": 7},
                                    "approval": APPROVAL_MODE,
                                    "timeout_hours": {"type": "integer", "minimum": 1, "maximum": 720, "default": 72}},
                                   ["strategy"])),
                 {"scheduled_post_ids": "Created scheduled posts", "slots": "[{variant_id, account_id, at}]"},
                 requires_autonomous_actions=True, dry_run="simulate", yields=True),
        NodeType("publish", "publishing", "Publish now", "Publishes already-approved variants immediately.",
                 "APPROVAL",
                 _with_common(_obj({"variant": ID_STR, "variants": {"description": "List of variant ids"},
                                    "account": ID_STR, "approval": APPROVAL_MODE,
                                    "timeout_hours": {"type": "integer", "minimum": 1, "maximum": 720, "default": 72}})),
                 {"scheduled_post_ids": "Publish jobs (scheduled posts at now())"},
                 requires_autonomous_actions=True, dry_run="simulate", yields=True),
        NodeType("wait", "control", "Wait", "Waits for a duration, until a time, or until an expression is true. "
                 "Bounded loops must go through a wait with max_iterations.", None,
                 _with_common(_obj({"minutes": {"type": "number", "minimum": 0, "maximum": 525600},
                                    "hours": {"type": "number", "minimum": 0, "maximum": 8760},
                                    "days": {"type": "number", "minimum": 0, "maximum": 365},
                                    "until": {"type": "string", "description": "ISO datetime (or template)"},
                                    "until_expression": {"type": "string", "x-expression": True,
                                                         "description": "Poll until true"},
                                    "poll_minutes": {"type": "integer", "minimum": 1, "maximum": 1440, "default": 15},
                                    "timeout_hours": {"type": "number", "minimum": 0.1, "maximum": 8760, "default": 24},
                                    "max_iterations": {"type": "integer", "minimum": 1, "maximum": 100}})),
                 {"waited_until": "ISO time", "timed_out": "until_expression only", "iteration": "Loop iteration"},
                 raw_fields=("until_expression",), dry_run="simulate", yields=True),
        NodeType("webhook", "integration", "Webhook", "Signed outbound HTTP call to an allowlisted public host.",
                 "EXTERNAL_WRITE",
                 _with_common(_obj({"url": {"type": "string", "minLength": 8, "maxLength": 2000},
                                    "method": {"type": "string", "enum": ["POST", "PUT", "PATCH"], "default": "POST"},
                                    "body": {"description": "JSON body (templated)"},
                                    "headers": {"type": "object"},
                                    "sign": {"type": "boolean", "default": True},
                                    "timeout_seconds": {"type": "integer", "minimum": 1, "maximum": 30, "default": 10}},
                                   ["url"])),
                 {"status": "HTTP status", "ok": "2xx", "response": "Parsed JSON or text (truncated)"},
                 requires_autonomous_actions=True, dry_run="simulate"),
        NodeType("notification", "integration", "Notification", "In-app / email / Slack / webhook notification.",
                 "WRITE_INTERNAL",
                 _with_common(_obj({"title": {"type": "string", "minLength": 1, "maxLength": 500},
                                    "body": TEMPLATE_STR, "link": {"type": "string"},
                                    "severity": {"type": "string", "enum": ["info", "success", "warning", "error"]},
                                    "channels": {"type": "array", "items": {"type": "string",
                                                                            "enum": ["in_app", "email", "slack", "webhook"]}},
                                    "roles": {"type": "array", "items": {"type": "string", "enum": ROLES}},
                                    "user_ids": {"type": "array", "items": {"type": "string"}}}, ["title"])),
                 {"notification_ids": "Created notifications"}, dry_run="simulate"),
        NodeType("analytics", "data", "Analytics", "Reads normalized metrics (KPIs/breakdown) or runs insights.analyze.",
                 None,
                 _with_common(_obj({"mode": {"type": "string", "enum": ["query", "insights"], "default": "query"},
                                    "metric": {"type": "string", "default": "engagement_rate"},
                                    "group_by": {"type": "string", "enum": ["pillar", "format", "platform", "campaign",
                                                                            "hour", "weekday", "account"]},
                                    "period_days": {"type": "integer", "minimum": 1, "maximum": 365, "default": 30},
                                    "platform": {"type": "string", "enum": PLATFORMS},
                                    "dimensions": {"type": "array", "items": {"type": "string"}},
                                    "timeout_minutes": {"type": "integer", "minimum": 1, "maximum": 1440, "default": 60}})),
                 {"kpis": "query: KPIs", "groups": "query+group_by: groups", "posts": "posts considered",
                  "insights": "insights mode: analyst output"}, yields=True),
        NodeType("action", "data", "Action", "Built-in deterministic service actions.", "WRITE_INTERNAL",
                 _with_common(_obj({"action": {"type": "string", "enum": ACTIONS}, "params": {"type": "object"}},
                                   ["action"])),
                 {"result": "Action result"}, dry_run="simulate"),
    ]
    return {n.type: n for n in nodes}


NODE_TYPES: dict[str, NodeType] = _build()
TRIGGER_TYPES = frozenset(t for t in NODE_TYPES if t.startswith("trigger."))
GUARDED_TYPES = frozenset(t for t, n in NODE_TYPES.items() if n.requires_autonomous_actions)

SETTINGS_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "on_error": {"type": "string", "enum": ["stop", "continue", "notify"], "default": "stop"},
        "max_cost_usd": {"type": "number", "minimum": 0, "maximum": 1000},
        "timeout_minutes": {"type": "integer", "minimum": 1, "maximum": 43200},
        "concurrency": {"type": "string", "enum": ["single", "parallel"], "default": "single"},
        "notify_user_ids": {"type": "array", "items": {"type": "string"}},
    },
}


def get_node_type(type_: str) -> NodeType | None:
    return NODE_TYPES.get(type_)


def catalog() -> list[dict[str, Any]]:
    out = []
    actions = agent_actions()
    for n in NODE_TYPES.values():
        d = n.public()
        if n.type == "ai_agent" and actions:
            d["agent_actions"] = actions
        out.append(d)
    return out

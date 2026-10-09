"""Workflow definition validation (doc 14 §14.3) + graph helpers + templates."""
from __future__ import annotations

import copy

import pytest

from app.core.errors import ProblemError
from app.workflows import templates as tpl
from app.workflows.graph import Graph
from app.workflows.validation import normalize_definition, schema_errors, validate_definition

BASE = {
    "nodes": [
        {"key": "t", "type": "trigger.manual", "config": {}},
        {"key": "c", "type": "condition", "config": {"expression": "trigger.score >= 80"}},
        {"key": "x", "type": "transform", "config": {"mode": "template", "template": {"title": "Hot: {{ trigger.topic }}"}}},
        {"key": "a", "type": "approve", "config": {"timeout_hours": 24}},
        {"key": "n", "type": "notification", "config": {"title": "{{ steps.x.title }}"}},
        {"key": "skip", "type": "notification", "config": {"title": "below threshold"}},
    ],
    "edges": [
        {"from": "t", "to": "c"}, {"from": "c", "to": "x", "branch": "true"}, {"from": "c", "to": "skip", "branch": "false"},
        {"from": "x", "to": "a"}, {"from": "a", "to": "n", "branch": "approved"},
    ],
}


def errs(defn, autonomous=False, settings=None):
    n, e = normalize_definition(defn["nodes"], defn["edges"])
    return validate_definition(n, e, autonomous_actions_enabled=autonomous, settings=settings)


def codes(defn, **kw):
    return {x["code"] for x in errs(defn, **kw)}


def mutate(fn):
    d = copy.deepcopy(BASE)
    fn(d)
    return d


def test_valid_definition():
    assert errs(BASE) == []


def test_trigger_count():
    assert "trigger_count" in codes(mutate(lambda d: d["nodes"].pop(0) or d["edges"].pop(0)))
    two = mutate(lambda d: d["nodes"].append({"key": "t2", "type": "trigger.cron", "config": {"cron": "0 9 * * 1"}}))
    assert "trigger_count" in codes(two)
    assert codes({"nodes": [], "edges": []}) == {"empty"}


def test_keys_types_and_edges():
    assert "duplicate_key" in codes(mutate(lambda d: d["nodes"].append({"key": "c", "type": "condition",
                                                                        "config": {"expression": "true"}})))
    assert "invalid_key" in codes(mutate(lambda d: d["nodes"][1].update(key="1bad")))
    assert "unknown_type" in codes(mutate(lambda d: d["nodes"][1].update(type="shell.exec")))
    assert "unknown_node" in codes(mutate(lambda d: d["edges"].append({"from": "x", "to": "ghost"})))
    assert "edge_into_trigger" in codes(mutate(lambda d: d["edges"].append({"from": "x", "to": "t"})))
    assert "duplicate_edge" in codes(mutate(lambda d: d["edges"].append({"from": "t", "to": "c"})))


def test_branches():
    # condition edges need true/false; approve edges approved/rejected; plain nodes no branch
    assert "invalid_branch" in codes(mutate(lambda d: d["edges"][1].update(branch=None)))
    assert "invalid_branch" in codes(mutate(lambda d: d["edges"][4].update(branch="true")))
    assert "invalid_branch" in codes(mutate(lambda d: d["edges"][3].update(branch="approved")))
    # error edges are allowed from any non-trigger node
    ok = mutate(lambda d: d["edges"].append({"from": "x", "to": "skip", "branch": "error"}))
    assert errs(ok) == []


def test_cycles_need_bounded_wait():
    loop = mutate(lambda d: d["edges"].append({"from": "a", "to": "c", "branch": "rejected"}))
    assert "cycle" in codes(loop)

    def with_wait(d, max_it):
        d["nodes"].append({"key": "w", "type": "wait", "config": {"minutes": 30, **({"max_iterations": max_it} if max_it else {})}})
        d["edges"] += [{"from": "a", "to": "w", "branch": "rejected"}, {"from": "w", "to": "c"}]
    assert "cycle" in codes(mutate(lambda d: with_wait(d, None)))
    assert errs(mutate(lambda d: with_wait(d, 3))) == []
    g = Graph.build(*normalize_definition(*(lambda d: (d["nodes"], d["edges"]))(mutate(lambda d: with_wait(d, 3)))))
    back = [e for e in g.edges if e.index in g.back_edges]
    assert [(e.src, e.dst) for e in back] == [("w", "c")]
    assert g.loop_body("c") == {"c", "x", "a", "w"}


def test_reachability():
    assert "unreachable" in codes(mutate(lambda d: d["nodes"].append({"key": "orphan", "type": "notification",
                                                                      "config": {"title": "x"}})))


def test_config_schema_and_node_rules():
    assert "invalid_config" in codes(mutate(lambda d: d["nodes"][1].update(config={})))
    assert "invalid_config" in codes(mutate(lambda d: d["nodes"][1].update(config={"expression": "__import__('os')"})))
    assert "invalid_config" in codes(mutate(lambda d: d["nodes"][1].update(config={"expression": "x", "bogus": 1})))
    assert "invalid_config" in codes(mutate(lambda d: d["nodes"][3].update(config={"timeout_hours": 0})))
    assert "invalid_config" in codes(mutate(lambda d: d["nodes"][4].update(config={"title": "{{ broken"})))
    assert "invalid_config" in codes(mutate(lambda d: d["nodes"][0].update(type="trigger.cron", config={"cron": "61 * * * *"})))
    assert "invalid_config" in codes(mutate(lambda d: d["nodes"][0].update(type="trigger.event", config={"event": "NOPE"})))
    assert "invalid_config" in codes(mutate(lambda d: d["nodes"].append({"key": "wt", "type": "wait", "config": {}})
                                            or d["edges"].append({"from": "x", "to": "wt"})))
    ok = mutate(lambda d: d["nodes"][0].update(type="trigger.event", config={"event": "TREND_DETECTED",
                                                                              "filter": {"min_score": 80}}))
    assert errs(ok) == []


def test_unknown_step_reference():
    assert "unknown_step_ref" in codes(mutate(lambda d: d["nodes"][4].update(config={"title": "{{ steps.nope.title }}"})))


def test_autonomous_actions_guardrail():
    def add(d):
        d["nodes"].append({"key": "s", "type": "schedule", "config": {"variant": "{{ steps.x.value }}", "strategy": "best_time"}})
        d["edges"].append({"from": "a", "to": "s", "branch": "approved"})
    defn = mutate(add)
    e = errs(defn)
    assert [x["code"] for x in e] == ["autonomous_actions_disabled"]
    assert "autonomous actions" in e[0]["message"] and e[0]["node_key"] == "s"
    assert errs(defn, autonomous=True) == []
    for t in ("publish", "webhook"):
        cfg = {"variant": "v"} if t == "publish" else {"url": "https://example.com/hook"}
        d = mutate(lambda d, t=t, cfg=cfg: d["nodes"].append({"key": "z", "type": t, "config": cfg})
                   or d["edges"].append({"from": "x", "to": "z"}))
        assert "autonomous_actions_disabled" in codes(d)
    http = mutate(lambda d: d["nodes"].append({"key": "z", "type": "webhook", "config": {"url": "http://example.com"}})
                  or d["edges"].append({"from": "x", "to": "z"}))
    assert any("https" in x["message"] for x in errs(http, autonomous=True))


def test_settings_validation():
    assert errs(BASE, settings={"on_error": "continue", "max_cost_usd": 3}) == []
    assert "invalid_settings" in codes(BASE, settings={"on_error": "explode"})


def test_schema_errors_templates():
    schema = {"type": "object", "properties": {"n": {"type": "integer", "minimum": 1}}, "required": ["n"],
              "additionalProperties": False}
    assert schema_errors({"n": "{{ steps.x.count }}"}, schema) == []
    assert schema_errors({"n": "{{ steps.x.count }}"}, schema, allow_templates=False) == ["n must be integer"]
    assert schema_errors({"n": 0}, schema) == ["n must be ≥ 1"]
    assert schema_errors({}, schema) == ["n is required"]
    assert schema_errors({"n": True}, schema) == ["n must be integer"]


@pytest.mark.parametrize("tmpl", [t["key"] for t in tpl.list_templates()])
def test_templates_validate(tmpl):
    d = tpl.instantiate(tmpl)
    n, e = normalize_definition(d["nodes"], d["edges"])
    assert validate_definition(n, e, autonomous_actions_enabled=d["requires_autonomous_actions"], settings=d["settings"]) == []


def test_template_params():
    d = tpl.instantiate("weekly_research_ideas", {"idea_count": 5, "cron": "0 8 * * 2"})
    nodes = {n["key"]: n for n in d["nodes"]}
    assert nodes["ideas"]["config"]["count"] == 5
    assert nodes["t"]["config"] == {"cron": "0 8 * * 2"}          # timezone None → dropped
    news = tpl.instantiate("industry_news_linkedin", {"platform": "x"})
    assert {n["key"]: n for n in news["nodes"]}["s"]["config"]["account"] == "{{ brand.default_accounts.x }}"
    assert news["requires_autonomous_actions"] is True
    with pytest.raises(ProblemError):
        tpl.instantiate("weekly_research_ideas", {"idea_count": "ten"})
    with pytest.raises(ProblemError):
        tpl.instantiate("weekly_research_ideas", {"nope": 1})
    keys = [t["key"] for t in tpl.list_templates()]
    assert keys[:2] == ["industry_news_linkedin", "weekly_research_ideas"] and len(keys) == 6


def test_event_filter_matching():
    from app.workflows.triggers import event_trigger_payload, filter_matches
    payload = {"score": 85.5, "kinds": ["news", "keyword"], "brand_id": "b1", "status": "active"}
    assert filter_matches({"filter": {"min_score": 80, "kinds": ["news"]}}, payload)
    assert not filter_matches({"filter": {"min_score": 90}}, payload)
    assert not filter_matches({"filter": {"max_score": 50}}, payload)
    assert not filter_matches({"filter": {"kinds": ["social"]}}, payload)
    assert filter_matches({"filter": {"status": "active"}}, payload)
    assert not filter_matches({"filter": {"min_score": 1}}, {"kinds": []})          # missing field never matches
    assert filter_matches({"condition": "trigger.score > 85 and contains(kinds, \"keyword\")"}, payload)
    assert not filter_matches({"condition": "__import__('os')"}, payload)
    trig = event_trigger_payload({"name": "TREND_DETECTED", "event_id": "e1", "payload": {"label": "AI", "score": 3}})
    assert trig["trend"]["label"] == "AI" and trig["event"] == "TREND_DETECTED" and trig["label"] == "AI"


def test_consumers_registered_for_trigger_and_resume_events():
    import app.events.consumers_automation as cons
    from app.core.events import consumers_for
    from app.workflows.catalog import TRIGGER_EVENTS
    for name in [*TRIGGER_EVENTS, "CONTENT_STATUS_CHANGED", "RESEARCH_FAILED"]:
        assert cons.automation_event in consumers_for(name)

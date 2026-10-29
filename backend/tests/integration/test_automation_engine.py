"""Automation engine against the real local Postgres (doc 14, doc 31 Scenario B).

Seeds an isolated workspace (owner/editor/approver/viewer + brand), drives the API with httpx and plays the worker by
calling ``AutomationEngine.execute`` directly. Job enqueueing is replaced by a recorder so the live worker never sees
these runs; AI is absent, so AI-backed node types are swapped for fakes where needed (the real ai_agent yield/resume
path is exercised by completing the AIRun row by hand). Everything created is deleted afterwards.
"""
from __future__ import annotations

import asyncio
import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy import delete, text

pytestmark = pytest.mark.integration


@pytest_asyncio.fixture
async def env(monkeypatch):
    from app.core.db import SessionLocal, engine
    from app.core.security import create_access_token
    from app.main import app
    from app.models import Brand, User, Workspace, WorkspaceMember
    from app.models.enums import MemberRole
    from app.workflows import engine as eng
    from app.workflows.nodes import base as node_base

    await engine.dispose()
    enqueued: list[dict[str, Any]] = []

    async def fake_enqueue(run_id, workspace_id, workflow_id=None, *, exclusive=True, delay_s=None):
        enqueued.append({"run_id": str(run_id), "workspace_id": str(workspace_id), "workflow_id": str(workflow_id),
                         "exclusive": exclusive, "delay_s": delay_s})
        return True

    def fake_enqueue_ai(run_id, workspace_id):
        async def go():
            enqueued.append({"ai_run_id": str(run_id)})
        return go

    monkeypatch.setattr(eng, "enqueue_execute", fake_enqueue)
    monkeypatch.setattr(node_base, "_enqueue_ai", fake_enqueue_ai)

    tag = uuid.uuid4().hex[:10]
    roles = ("owner", "editor", "approver", "viewer")
    async with SessionLocal() as db:
        users = {r: User(email=f"auto-{r}-{tag}@test.local", full_name=f"{r.title()} {tag}") for r in roles}
        db.add_all(users.values())
        await db.flush()
        ws = Workspace(name=f"Automation WS {tag}", slug=f"automation-ws-{tag}", created_by=users["owner"].id)
        db.add(ws)
        await db.flush()
        for r, u in users.items():
            db.add(WorkspaceMember(workspace_id=ws.id, user_id=u.id, role=MemberRole(r)))
        brand = Brand(workspace_id=ws.id, name="Acme Billing", slug=f"acme-{tag}", industry="medical billing",
                      timezone="Europe/Paris", created_by=users["owner"].id)
        db.add(brand)
        await db.commit()
        ids = {"ws": ws.id, "brand": brand.id, **{r: u.id for r, u in users.items()}}

    def headers(role: str) -> dict[str, str]:
        return {"Authorization": f"Bearer {create_access_token(ids[role], ids['ws'], role)}", "X-Workspace-Id": str(ids["ws"])}

    async def member(role: str):
        from app.api.deps import Member
        async with SessionLocal() as db:
            u = await db.get(User, ids[role])
        return Member(user=u, workspace_id=ids["ws"], role=MemberRole(role))

    async def execute(run_id):
        async with SessionLocal() as db:
            run = await eng.AutomationEngine.execute(db, uuid.UUID(str(run_id)))
            await db.commit()
            return run

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        yield {"client": client, "h": headers, "member": member, "execute": execute, "enqueued": enqueued, **ids}

    async with SessionLocal() as db:
        await db.execute(text("DELETE FROM events_outbox WHERE workspace_id = :ws"), {"ws": str(ids["ws"])})
        await db.execute(delete(Workspace).where(Workspace.id == ids["ws"]))
        await db.execute(delete(User).where(User.id.in_([ids[r] for r in roles])))
        await db.commit()
    await engine.dispose()


async def _q(sql: str, **params: Any) -> list[Any]:
    from app.core.db import SessionLocal
    async with SessionLocal() as db:
        res = await db.execute(text(sql), params)
        rows = list(res.all()) if res.returns_rows else []
        await db.commit()
        return rows


async def _steps(run_id: str) -> dict[str, str]:
    rows = await _q("SELECT node_key, status FROM automation_run_steps WHERE run_id = :r", r=run_id)
    return {k: s for k, s in rows}


async def _run_status(run_id: str) -> str:
    return (await _q("SELECT status FROM automation_runs WHERE id = :r", r=run_id))[0][0]


async def _make_due(run_id: str, node_key: str = "w") -> None:
    await _q("UPDATE automation_run_steps SET output = jsonb_set(output, '{_state,due}', '\"2020-01-01T00:00:00+00:00\"') "
             "WHERE run_id = :r AND node_key = :k", r=run_id, k=node_key)
    await _q("UPDATE automation_runs SET waiting_until = now() - interval '1 minute' WHERE id = :r", r=run_id)


APPROVAL_FLOW = {
    "name": "Hot topic approval flow",
    "nodes": [
        {"key": "t", "type": "trigger.manual", "config": {"input_schema": {
            "type": "object", "properties": {"score": {"type": "number"}, "topic": {"type": "string"}}, "required": ["score"]}}},
        {"key": "c", "type": "condition", "config": {"expression": "trigger.score >= 80"}},
        {"key": "x", "type": "transform", "config": {"mode": "template",
                                                     "template": {"title": "Hot: {{ trigger.topic }}", "score": "{{ trigger.score }}"}}},
        {"key": "w", "type": "wait", "config": {"minutes": 30}},
        {"key": "a", "type": "approve", "config": {"title": "Approve {{ steps.x.title }}", "timeout_hours": 24}},
        {"key": "n", "type": "notification", "config": {"title": "{{ steps.x.title }} approved", "body": "score {{ steps.x.score }}"}},
        {"key": "plan", "type": "action", "config": {"action": "ideas.add_to_planner",
                                                     "params": {"idea_ids": "{{ trigger.idea_ids }}", "week": "2026-W42"}}},
        {"key": "low", "type": "notification", "config": {"title": "Score too low: {{ trigger.score }}"}},
        {"key": "rej", "type": "notification", "config": {"title": "Rejected: {{ steps.a.comment }}"}},
    ],
    "edges": [
        {"from": "t", "to": "c"}, {"from": "c", "to": "x", "branch": "true"}, {"from": "c", "to": "low", "branch": "false"},
        {"from": "x", "to": "w"}, {"from": "w", "to": "a"}, {"from": "a", "to": "n", "branch": "approved"},
        {"from": "a", "to": "rej", "branch": "rejected"}, {"from": "n", "to": "plan"},
    ],
}


async def _create(c, h, body=APPROVAL_FLOW) -> dict[str, Any]:
    r = await c.post("/api/v1/automations", json=body, headers=h("owner"))
    assert r.status_code == 201, r.text
    return r.json()


async def _idea(env) -> str:
    from app.core.db import SessionLocal
    from app.models import ContentIdea
    async with SessionLocal() as db:
        idea = ContentIdea(workspace_id=env["ws"], brand_id=env["brand"], title=f"Idea {uuid.uuid4().hex[:6]}")
        db.add(idea)
        await db.commit()
        return str(idea.id)


async def test_approval_path_wait_approve_resume(env):
    c, h = env["client"], env["h"]
    assert (await c.post("/api/v1/automations", json=APPROVAL_FLOW, headers=h("editor"))).status_code == 403
    assert (await c.post("/api/v1/automations", json=APPROVAL_FLOW, headers=h("viewer"))).status_code == 403
    wf = await _create(c, h)
    assert wf["status"] == "draft" and wf["version"] == 1 and wf["trigger_summary"] == "Manual"
    assert {n["key"] for n in wf["nodes"]} == {n["key"] for n in APPROVAL_FLOW["nodes"]}
    assert {"from": "c", "to": "x", "branch": "true", "condition": None} in wf["edges"]
    idea_id = await _idea(env)

    # viewer can't run; bad payload → 422; editor runs
    assert (await c.post(f"/api/v1/automations/{wf['id']}/run", json={"payload": {"score": 90}}, headers=h("viewer"))).status_code == 403
    r = await c.post(f"/api/v1/automations/{wf['id']}/run", json={"payload": {"topic": "x"}}, headers=h("editor"))
    assert r.status_code == 422, r.text
    r = await c.post(f"/api/v1/automations/{wf['id']}/run", headers=h("editor"),
                     json={"payload": {"score": 91, "topic": "AI denials", "idea_ids": [idea_id]}})
    assert r.status_code == 202, r.text
    run_id = r.json()["run_id"]
    assert env["enqueued"][-1] == {"run_id": run_id, "workspace_id": str(env["ws"]), "workflow_id": wf["id"],
                                   "exclusive": True, "delay_s": None}

    # worker: runs to the wait node
    run = await env["execute"](run_id)
    assert run.status.value == "waiting" and run.waiting_until > datetime.now(UTC) + timedelta(minutes=25)
    assert await _steps(run_id) == {"t": "succeeded", "c": "succeeded", "x": "succeeded", "low": "skipped", "w": "waiting"}

    # one active run per workflow
    r = await c.post(f"/api/v1/automations/{wf['id']}/run", json={"payload": {"score": 99}}, headers=h("editor"))
    assert r.status_code == 409 and r.json()["type"].endswith("automation_run_active")

    # scheduler: not due yet → nothing; once due → re-enqueued → approve pauses the run
    from app.core.db import SessionLocal
    from app.workflows.triggers import dispatch_waiting
    async with SessionLocal() as db:
        assert await dispatch_waiting(db, workspace_id=env["ws"]) == 0
    await _make_due(run_id)
    n_before = len(env["enqueued"])
    async with SessionLocal() as db:
        assert await dispatch_waiting(db, workspace_id=env["ws"]) == 1
    assert env["enqueued"][n_before]["run_id"] == run_id
    run = await env["execute"](run_id)
    assert run.status.value == "awaiting_approval" and run.approval_id is not None
    ap = (await _q("SELECT id, kind, target_type, target_id, status, payload->>'title' FROM approvals WHERE id = :i",
                   i=str(run.approval_id)))[0]
    assert ap[1:5] == ("automation_step", "automation_run", uuid.UUID(run_id), "pending")
    assert ap[5] == "Approve Hot: AI denials"

    # editor may not approve; approver approves via the API → hook marks the run due and enqueues after commit
    assert (await c.post(f"/api/v1/approvals/{ap[0]}/approve", json={}, headers=h("editor"))).status_code == 403
    n_before = len(env["enqueued"])
    r = await c.post(f"/api/v1/approvals/{ap[0]}/approve", json={"comment": "ship it"}, headers=h("approver"))
    assert r.status_code == 200, r.text
    await asyncio.sleep(0.05)
    assert any(e.get("run_id") == run_id for e in env["enqueued"][n_before:])
    assert await _run_status(run_id) == "waiting"

    run = await env["execute"](run_id)
    assert run.status.value == "succeeded", run.error
    assert await _steps(run_id) == {"t": "succeeded", "c": "succeeded", "x": "succeeded", "low": "skipped", "w": "succeeded",
                                    "a": "succeeded", "rej": "skipped", "n": "succeeded", "plan": "succeeded"}
    detail = (await c.get(f"/api/v1/automations/runs/{run_id}", headers=h("viewer"))).json()
    assert "_workflow" not in detail["context"] and detail["status"] == "succeeded"
    steps = {s["node_key"]: s for s in detail["steps"]}
    assert steps["a"]["output"]["decision"] == "approved" and steps["a"]["output"]["comment"] == "ship it"
    assert steps["x"]["output"]["title"] == "Hot: AI denials" and steps["x"]["node_type"] == "transform"
    assert steps["plan"]["output"]["planner_week"] == "2026-W42"
    notes = await _q("SELECT title, body FROM notifications WHERE workspace_id = :w AND kind = 'automation'", w=str(env["ws"]))
    assert ("Hot: AI denials approved", "score 91") in [tuple(n) for n in notes]
    ev = (await _q("SELECT evidence->>'planner_week', evidence->>'automation_run_id' FROM content_ideas WHERE id = :i",
                   i=idea_id))[0]
    assert ev == ("2026-W42", run_id)
    names = [r[0] for r in await _q("SELECT name FROM events_outbox WHERE workspace_id = :w ORDER BY id", w=str(env["ws"]))]
    for name in ("AUTOMATION_TRIGGERED", "AUTOMATION_STEP_COMPLETED", "IDEAS_ADDED", "AUTOMATION_COMPLETED"):
        assert name in names
    r = await c.get(f"/api/v1/automations/{wf['id']}/runs", headers=h("viewer"))
    assert r.status_code == 200 and [x["id"] for x in r.json()["items"]] == [run_id]

    # second run: rejected via the service path → 'rejected' branch
    r = await c.post(f"/api/v1/automations/{wf['id']}/run", json={"payload": {"score": 85, "topic": "B"}}, headers=h("editor"))
    run2 = r.json()["run_id"]
    await env["execute"](run2)
    await _make_due(run2)
    run = await env["execute"](run2)
    from app.services.approval_service import ApprovalService
    async with SessionLocal() as db:
        await ApprovalService.reject(db, await env["member"]("approver"), run.approval_id, "not on brand")
        await db.commit()
    run = await env["execute"](run2)
    assert run.status.value == "succeeded"
    s2 = await _steps(run2)
    assert s2["a"] == "succeeded" and s2["rej"] == "succeeded" and s2["n"] == "skipped" and s2["plan"] == "skipped"


async def test_dry_run_simulates_side_effects(env):
    c, h = env["client"], env["h"]
    wf = await _create(c, h)
    r = await c.post(f"/api/v1/automations/{wf['id']}/run", json={"payload": {"score": 95, "topic": "T"}, "dry_run": True},
                     headers=h("editor"))
    assert r.status_code == 202 and r.json()["dry_run"] is True
    run_id = r.json()["run_id"]
    assert env["enqueued"][-1]["exclusive"] is False
    # a second dry run is not blocked by the one-active-run rule
    r2 = await c.post(f"/api/v1/automations/{wf['id']}/run", json={"payload": {"score": 10}, "dry_run": True}, headers=h("editor"))
    assert r2.status_code == 202
    run = await env["execute"](run_id)
    assert run.status.value == "succeeded", run.error
    detail = (await c.get(f"/api/v1/automations/runs/{run_id}", headers=h("viewer"))).json()
    steps = {s["node_key"]: s for s in detail["steps"]}
    assert steps["w"]["output"]["simulated"] is True and steps["a"]["output"]["branch"] == "approved"
    assert steps["n"]["output"]["simulated"] is True and steps["plan"]["output"]["simulated"] is True
    assert steps["x"]["output"]["title"] == "Hot: T"          # non side-effect nodes really run
    run = await env["execute"](r2.json()["run_id"])
    assert run.status.value == "succeeded"
    assert (await _steps(r2.json()["run_id"]))["low"] == "succeeded"
    assert await _q("SELECT id FROM approvals WHERE workspace_id = :w", w=str(env["ws"])) == []
    assert await _q("SELECT id FROM notifications WHERE workspace_id = :w AND kind = 'automation'", w=str(env["ws"])) == []


async def test_cancel_and_single_active_run(env):
    c, h = env["client"], env["h"]
    wf = await _create(c, h)
    run_id = (await c.post(f"/api/v1/automations/{wf['id']}/run", json={"payload": {"score": 90}}, headers=h("editor"))).json()["run_id"]
    await env["execute"](run_id)
    await _make_due(run_id)
    run = await env["execute"](run_id)
    assert run.status.value == "awaiting_approval"
    assert (await c.post(f"/api/v1/automations/runs/{run_id}/cancel", headers=h("viewer"))).status_code == 403
    r = await c.post(f"/api/v1/automations/runs/{run_id}/cancel", headers=h("editor"))
    assert r.status_code == 200, r.text
    assert r.json()["status"] == "cancelled"
    assert {s["node_key"]: s["status"] for s in r.json()["steps"]}["a"] == "skipped"
    assert (await _q("SELECT status FROM approvals WHERE id = :i", i=str(run.approval_id)))[0][0] == "expired"
    assert (await c.post(f"/api/v1/automations/runs/{run_id}/cancel", headers=h("editor"))).status_code == 409
    run = await env["execute"](run_id)                   # a stale job is a no-op
    assert run.status.value == "cancelled"
    r = await c.post(f"/api/v1/automations/{wf['id']}/run", json={"payload": {"score": 90}}, headers=h("editor"))
    assert r.status_code == 202                          # the lock is free again
    # deleting a workflow with history archives it and cancels its active run
    assert (await c.delete(f"/api/v1/automations/{wf['id']}", headers=h("editor"))).status_code == 403
    assert (await c.delete(f"/api/v1/automations/{wf['id']}", headers=h("owner"))).status_code == 204
    assert await _run_status(r.json()["run_id"]) == "cancelled"
    assert (await c.get(f"/api/v1/automations/{wf['id']}", headers=h("viewer"))).json()["status"] == "archived"
    assert (await c.get("/api/v1/automations", headers=h("viewer"))).json()["items"] == []


async def test_ai_step_yields_and_resumes_on_ai_run_completed(env):
    c, h = env["client"], env["h"]
    body = {"name": "AI flow", "brand_id": str(env["brand"]), "nodes": [
        {"key": "t", "type": "trigger.manual", "config": {}},
        {"key": "ai", "type": "ai_agent", "config": {"agent": "trend", "action": "detect",
                                                     "inputs": {"industry": "{{ brand.industry }}", "window_days": 14}}},
        {"key": "x", "type": "transform", "config": {"mode": "template", "template": {"first": "{{ steps.ai.output.trends[0] }}"}}},
    ], "edges": [{"from": "t", "to": "ai"}, {"from": "ai", "to": "x"}], "settings": {"max_cost_usd": 2}}
    wf = await _create(c, h, body)
    run_id = (await c.post(f"/api/v1/automations/{wf['id']}/run", json={}, headers=h("editor"))).json()["run_id"]
    run = await env["execute"](run_id)
    assert run.status.value == "waiting"
    step = (await _q("SELECT ai_run_id, status FROM automation_run_steps WHERE run_id = :r AND node_key = 'ai'", r=run_id))[0]
    assert step[1] == "waiting" and step[0] is not None
    ai = (await _q("SELECT mode, status, automation_run_id, input->>'agent', input->'inputs'->>'industry' FROM ai_runs WHERE id = :i",
                   i=str(step[0])))[0]
    assert ai == ("tool", "queued", uuid.UUID(run_id), "trend", "medical billing")
    assert {"ai_run_id": str(step[0])} in env["enqueued"]       # AI job enqueued after the commit
    run = await env["execute"](run_id)                          # still running → stays waiting, nothing duplicated
    assert run.status.value == "waiting"
    assert len(await _q("SELECT id FROM ai_runs WHERE automation_run_id = :r", r=run_id)) == 1

    # the AI run completes → AI_RUN_COMPLETED consumer wakes the run → execute continues
    await _q("UPDATE ai_runs SET status = 'completed', cost_usd = 0.12, result = CAST(:res AS jsonb) WHERE id = :i",
             i=str(step[0]), res='{"deliverables": {"t1": {"trends": ["denial automation"]}}, "reasoning_summary": "- ok"}')
    from app.workflows.triggers import handle_event
    n_before = len(env["enqueued"])
    await handle_event({"name": "AI_RUN_COMPLETED", "workspace_id": str(env["ws"]), "event_id": str(uuid.uuid4()),
                        "payload": {"run_id": str(step[0])}})
    assert env["enqueued"][n_before]["run_id"] == run_id
    run = await env["execute"](run_id)
    assert run.status.value == "succeeded", run.error
    assert float(run.cost_usd) == pytest.approx(0.12)
    detail = (await c.get(f"/api/v1/automations/runs/{run_id}", headers=h("viewer"))).json()
    steps = {s["node_key"]: s for s in detail["steps"]}
    assert steps["ai"]["output"]["output"] == {"trends": ["denial automation"]}
    assert steps["x"]["output"]["first"] == "denial automation"


async def test_bounded_wait_loop(env):
    c, h = env["client"], env["h"]

    def body(max_it: int) -> dict[str, Any]:
        return {"name": f"Loop {max_it}", "nodes": [
            {"key": "t", "type": "trigger.manual", "config": {}},
            {"key": "c", "type": "condition", "config": {"expression": "steps.w.iteration >= 2"}},
            {"key": "w", "type": "wait", "config": {"minutes": 0, "max_iterations": max_it}},
            {"key": "n", "type": "notification", "config": {"title": "done after {{ steps.w.iteration }}"}},
        ], "edges": [{"from": "t", "to": "c"}, {"from": "c", "to": "w", "branch": "false"}, {"from": "w", "to": "c"},
                     {"from": "c", "to": "n", "branch": "true"}]}
    wf = await _create(c, h, body(3))
    run_id = (await c.post(f"/api/v1/automations/{wf['id']}/run", json={}, headers=h("editor"))).json()["run_id"]
    run = await env["execute"](run_id)
    assert run.status.value == "succeeded", run.error
    assert run.context["_loops"] == {"w": 2}
    assert await _steps(run_id) == {"t": "succeeded", "c": "succeeded", "w": "skipped", "n": "succeeded"}
    wf = await _create(c, h, body(1))
    run_id = (await c.post(f"/api/v1/automations/{wf['id']}/run", json={}, headers=h("editor"))).json()["run_id"]
    run = await env["execute"](run_id)
    assert run.status.value == "failed" and "max_iterations=1" in run.error
    assert (await _q("SELECT title FROM notifications WHERE workspace_id = :w AND kind = 'automation_failed'",
                     w=str(env["ws"])))[0][0] == "Automation 'Loop 1' failed"


async def test_template_scenario_b_via_cron(env, monkeypatch):
    from app.core.db import SessionLocal
    from app.models import ContentIdea
    from app.workflows import nodes as reg
    from app.workflows.triggers import dispatch_cron

    async def fake_research(ctx, config):
        assert "medical billing" in config["query"] and config["recency_days"] == 7
        return {"research_run_id": str(uuid.uuid4()), "source_count": 4, "summary": "news"}

    async def fake_ai(ctx, config):
        return {"output": {"trends": [{"label": "prior auth"}]}, "ai_run_id": None}

    async def fake_generate(ctx, config):
        if "idea_ids" not in ctx.state:              # idempotent per (run, node)
            ideas = [ContentIdea(workspace_id=ctx.workspace_id, brand_id=ctx.brand_id, title=f"Idea {i}") for i in range(config["count"])]
            ctx.db.add_all(ideas)
            await ctx.db.flush()
            ctx.state["idea_ids"] = [str(i.id) for i in ideas]
        assert config["from"]["research_run_id"] and config["from"]["trends"] == {"trends": [{"label": "prior auth"}]}
        return {"idea_ids": ctx.state["idea_ids"], "count": len(ctx.state["idea_ids"])}

    monkeypatch.setitem(reg.REGISTRY, "research", fake_research)
    monkeypatch.setitem(reg.REGISTRY, "ai_agent", fake_ai)
    monkeypatch.setitem(reg.REGISTRY, "generate", fake_generate)
    c, h = env["client"], env["h"]
    r = await c.get("/api/v1/automations/templates", headers=h("viewer"))
    assert r.status_code == 200 and len(r.json()) == 6
    assert (await c.post("/api/v1/automations/from-template/weekly_research_ideas", json={}, headers=h("editor"))).status_code == 403
    r = await c.post("/api/v1/automations/from-template/weekly_research_ideas", headers=h("owner"),
                     json={"brand_id": str(env["brand"]), "params": {"idea_count": 3}, "enable": True})
    assert r.status_code == 201, r.text
    wf = r.json()
    assert wf["status"] == "active" and wf["trigger_summary"] == "Every Monday at 09:00 (Europe/Paris)"
    nxt = datetime.fromisoformat(wf["next_run_at"])
    assert nxt.astimezone(UTC).weekday() == 0 and nxt > datetime.now(UTC)
    await _q("UPDATE automation_workflows SET next_run_at = now() - interval '1 minute' WHERE id = :i", i=wf["id"])
    async with SessionLocal() as db:
        assert await dispatch_cron(db, workspace_id=env["ws"]) == 1
    row = (await _q("SELECT next_run_at FROM automation_workflows WHERE id = :i", i=wf["id"]))[0][0]
    assert row > datetime.now(UTC)
    run_id = env["enqueued"][-1]["run_id"]
    run = await env["execute"](run_id)
    assert run.status.value == "succeeded", run.error
    assert run.trigger_type == "cron" and run.context["trigger"]["timezone"] == "Europe/Paris"
    s = await _steps(run_id)
    assert set(s.values()) == {"succeeded"} and len(s) == 7
    week = datetime.now(__import__("zoneinfo").ZoneInfo("Europe/Paris")).isocalendar()
    weeks = {r[0] for r in await _q("SELECT evidence->>'planner_week' FROM content_ideas WHERE workspace_id = :w", w=str(env["ws"]))}
    assert weeks == {f"{week[0]}-W{week[1]:02d}"}
    title = (await _q("SELECT title FROM notifications WHERE workspace_id = :w AND kind = 'automation'", w=str(env["ws"])))[0][0]
    assert title == f"3 new ideas for week {week[0]}-W{week[1]:02d}"
    # the same slot does not fire twice
    async with SessionLocal() as db:
        assert await dispatch_cron(db, workspace_id=env["ws"]) == 0


async def test_api_validation_catalog_and_webhook_trigger(env):
    c, h = env["client"], env["h"]
    r = await c.get("/api/v1/automations/node-types", headers=h("viewer"))
    assert r.status_code == 200
    types = {t["type"]: t for t in r.json()}
    assert len(types) == 17 and types["schedule"]["requires_autonomous_actions"] is True
    assert types["condition"]["branches"] == ["true", "false", "error"] and "agent_actions" in types["ai_agent"]

    bad = {"name": "Needs autonomy", "nodes": [
        {"key": "t", "type": "trigger.manual"},
        {"key": "s", "type": "schedule", "config": {"variant": "{{ trigger.variant_id }}", "strategy": "best_time"}}],
        "edges": [{"from": "t", "to": "s"}]}
    r = await c.post("/api/v1/automations", json=bad, headers=h("owner"))
    assert r.status_code == 422
    assert r.json()["errors"][0]["node_key"] == "s" and r.json()["errors"][0]["code"] == "autonomous_actions_disabled"
    r = await c.post("/api/v1/automations", json={**bad, "autonomous_actions_enabled": True}, headers=h("owner"))
    assert r.status_code == 201 and r.json()["autonomous_actions_enabled"] is True
    r = await c.post("/api/v1/automations/from-template/industry_news_linkedin", json={}, headers=h("owner"))
    assert r.status_code == 422
    r = await c.post("/api/v1/automations/from-template/industry_news_linkedin", headers=h("owner"),
                     json={"autonomous_actions_enabled": True, "brand_id": str(env["brand"])})
    assert r.status_code == 201, r.text
    assert r.json()["trigger_summary"].startswith("When TREND_DETECTED")

    hook = {"name": "Webhook flow", "nodes": [
        {"key": "t", "type": "trigger.webhook", "config": {"schema": {"type": "object", "required": ["topic"]}}},
        {"key": "x", "type": "transform", "config": {"mode": "template", "template": {"echo": "{{ trigger.topic }}"}}}],
        "edges": [{"from": "t", "to": "x"}]}
    wf = await _create(c, h, hook)
    assert wf["webhook_url"] and "/webhook/" in wf["webhook_url"]
    assert (await c.get(f"/api/v1/automations/{wf['id']}", headers=h("viewer"))).json()["webhook_url"] is None
    path = "/api/v1/automations/" + wf["webhook_url"].split("/api/v1/automations/", 1)[1]
    assert (await c.post(path, json={"topic": "x"})).status_code == 404        # not active yet
    assert (await c.post(f"/api/v1/automations/{wf['id']}/enable", headers=h("owner"))).status_code == 200
    assert (await c.post(path[:-3] + "abc", json={"topic": "x"})).status_code == 404
    assert (await c.post(path, json={"nope": 1})).status_code == 422
    r = await c.post(path, json={"topic": "from outside"})
    assert r.status_code == 202, r.text
    run = await env["execute"](r.json()["run_id"])
    assert run.status.value == "succeeded" and run.trigger_type == "webhook"
    assert run.context["steps"]["x"]["echo"] == "from outside"

    # PUT replaces the definition and bumps the version; disable pauses it
    upd = {**hook, "nodes": hook["nodes"] + [{"key": "n", "type": "notification", "config": {"title": "hi"}}],
           "edges": hook["edges"] + [{"from": "x", "to": "n"}], "settings": {"on_error": "continue"}}
    r = await c.put(f"/api/v1/automations/{wf['id']}", json=upd, headers=h("owner"))
    assert r.status_code == 200 and r.json()["version"] == 2 and r.json()["settings"] == {"on_error": "continue"}
    assert len(r.json()["nodes"]) == 3
    r = await c.put(f"/api/v1/automations/{wf['id']}", json={**upd, "settings": {"bogus": 1}}, headers=h("owner"))
    assert r.status_code == 422
    r = await c.post(f"/api/v1/automations/{wf['id']}/disable", headers=h("owner"))
    assert r.status_code == 200 and r.json()["status"] == "paused"
    audit = [a[0] for a in await _q("SELECT action FROM audit_logs WHERE target_id = :i ORDER BY id", i=wf["id"])]
    assert audit[:2] == ["automation.create", "automation.enable"] and "automation.update" in audit


async def test_report_action_uses_report_service(env):
    c, h = env["client"], env["h"]
    body = {"name": "Report flow", "brand_id": str(env["brand"]), "nodes": [
        {"key": "t", "type": "trigger.manual", "config": {}},
        {"key": "r", "type": "action", "config": {"action": "report.generate",
                                                  "params": {"kind": "weekly_performance", "title": "Auto weekly"}}},
        {"key": "n", "type": "notification", "config": {"title": "{{ steps.r.title }} ({{ steps.r.status }})"}}],
        "edges": [{"from": "t", "to": "r"}, {"from": "r", "to": "n"}]}
    wf = await _create(c, h, body)
    run_id = (await c.post(f"/api/v1/automations/{wf['id']}/run", json={}, headers=h("editor"))).json()["run_id"]
    run = await env["execute"](run_id)
    assert run.status.value == "succeeded", run.error
    rep = (await _q("SELECT kind, title, automation_run_id, content->>'status' FROM reports WHERE workspace_id = :w",
                    w=str(env["ws"])))[0]
    assert rep == ("weekly_performance", "Auto weekly", uuid.UUID(run_id), "ready")
    assert run.context["steps"]["r"]["report_id"]

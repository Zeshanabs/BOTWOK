"""Insights + reports API against the real local Postgres with NO AI keys (deterministic paths).

signup (fixture) → brand → seeded posts/metrics → POST /insights/analyze (200 deterministic) → GET /insights →
recommendation decision + acknowledge → POST /reports (202 generating) → poll until ready (runs the job inline when no
worker picks it up within 10 s) → export markdown/html (pdf → 501) → list/delete. Everything created is deleted.
"""
from __future__ import annotations

import asyncio
import time
import uuid
from datetime import UTC, datetime, timedelta

import pytest
import pytest_asyncio
from sqlalchemy import delete, text

pytestmark = pytest.mark.integration


@pytest_asyncio.fixture
async def env(client, seeded_user, monkeypatch):
    from app.config import settings
    from app.core.db import SessionLocal, engine
    from app.integrations.embeddings.fake import FakeEmbeddingProvider
    from app.integrations.embeddings.registry import register_embedding_provider
    from app.models import User, Workspace
    from app.models.content import ContentItem, ContentVariant
    from app.models.enums import ContentFormat, ContentStatus, Platform
    from app.models.scheduling import PostMetric, PublishedPost
    from app.models.social import SocialAccount

    for key in ("anthropic_api_key", "openai_api_key", "xai_api_key", "google_api_key", "groq_api_key", "openrouter_api_key",
                "huggingface_api_key"):
        monkeypatch.setattr(settings, key, "")          # force the no-AI (deterministic) path
    monkeypatch.setattr(settings, "free_fallback_models", "")   # ... including the key-less free fallback
    register_embedding_provider(FakeEmbeddingProvider(settings.embedding_dims))
    h = dict(seeded_user["headers"])
    if not h.get("X-Workspace-Id"):          # the fixture reads `memberships`; signup returns `workspace` → ask /auth/me
        me = (await client.get("/api/v1/auth/me", headers=h)).json()
        h["X-Workspace-Id"] = str(me["memberships"][0]["workspace"]["id"])
    ws = uuid.UUID(h["X-Workspace-Id"])
    uid = uuid.UUID(str(seeded_user["user"]["id"]))
    try:
        r = await client.post("/api/v1/brands", headers=h, json={"name": "Pedal Co", "timezone": "UTC", "industry": "e-bikes"})
        assert r.status_code == 201, r.text
        brand_id = uuid.UUID(r.json()["id"])
        now = datetime.now(UTC)
        async with SessionLocal() as db:
            accounts = {p: SocialAccount(workspace_id=ws, brand_id=brand_id, platform=p, external_id=f"{p.value}-{uuid.uuid4().hex[:6]}",
                                         display_name=f"Pedal {p.value}", connected_by=uid)
                        for p in (Platform.linkedin, Platform.tiktok)}
            db.add_all(accounts.values())
            await db.flush()
            n = 0

            async def post(platform: Platform, fmt: ContentFormat, er: float | None, days_ago: int) -> None:
                nonlocal n
                n += 1
                item = ContentItem(workspace_id=ws, brand_id=brand_id, title=f"{fmt.value} post {n}", master_format=fmt,
                                   status=ContentStatus.approved, created_by=uid)
                db.add(item)
                await db.flush()
                v = ContentVariant(workspace_id=ws, content_item_id=item.id, platform=platform, format=fmt, text=f"Post {n} text",
                                   social_account_id=accounts[platform].id, status=ContentStatus.approved)
                db.add(v)
                await db.flush()
                published = (now - timedelta(days=days_ago)).replace(hour=10, minute=0, second=0, microsecond=0)
                pp = PublishedPost(workspace_id=ws, brand_id=brand_id, content_variant_id=v.id, social_account_id=accounts[platform].id,
                                   platform=platform, external_id=f"ext-{uuid.uuid4().hex[:10]}", published_at=published)
                db.add(pp)
                await db.flush()
                if er is None:     # TikTok: no impressions/engagement metrics reported
                    metrics = {"views": 500}
                    avail = {"views": "available", "likes": "not_available", "impressions": "not_available"}
                else:
                    metrics = {"impressions": 1000, "likes": int(er * 1000)}
                    avail = {"impressions": "available", "likes": "available"}
                db.add(PostMetric(workspace_id=ws, published_post_id=pp.id, platform=platform, captured_at=published + timedelta(days=4),
                                  window="lifetime", engagement_rate=er, engagement_rate_basis="impressions" if er is not None else None,
                                  availability=avail, **metrics))

            for i in range(6):
                await post(Platform.linkedin, ContentFormat.carousel, 0.05, 4 + i)
            for i in range(9):
                await post(Platform.linkedin, ContentFormat.image, 0.035, 4 + i)
            for i in range(3):
                await post(Platform.tiktok, ContentFormat.short_video, None, 5 + i)
            await db.commit()
        yield {"client": client, "h": h, "ws": ws, "brand_id": brand_id, "user_id": uid}
    finally:   # also runs when seeding fails half-way
        register_embedding_provider(None)
        async with SessionLocal() as db:
            await db.execute(text("UPDATE procrastinate_jobs SET status='cancelled' WHERE status='todo' "
                                  "AND args->>'workspace_id' = :ws"), {"ws": str(ws)})
            for t in ("published_posts", "events_outbox", "audit_logs", "usage_ledger"):
                await db.execute(text(f"DELETE FROM {t} WHERE workspace_id = :ws"), {"ws": str(ws)})
            await db.execute(delete(Workspace).where(Workspace.id == ws))
            await db.execute(delete(User).where(User.id == uid))
            await db.commit()
        await engine.dispose()


async def _report_job_state(report_id: str) -> str | None:
    from app.core.db import SessionLocal
    async with SessionLocal() as db:
        return (await db.execute(text("SELECT status::text FROM procrastinate_jobs WHERE task_name = 'jobs.reports.generate' "
                                      "AND args->>'report_id' = :rid ORDER BY id DESC LIMIT 1"), {"rid": report_id})).scalar()


async def test_insights_and_reports_flow(env) -> None:
    from app.core.db import SessionLocal, set_workspace
    from app.models.ai import Memory
    from app.services.report_service import ReportService
    c, h, bid = env["client"], env["h"], str(env["brand_id"])

    # ---- deterministic analysis (no AI key) ------------------------------------------------------------------
    r = await c.post("/api/v1/insights/analyze", headers=h, json={"brand_id": bid, "period_days": 30})
    assert r.status_code == 200, r.text
    res = r.json()
    assert res["mode"] == "deterministic" and "run_id" not in res
    assert res["insights_created"] >= 1 and res["recommendations_created"] >= 1
    assert res["coverage"] == {"posts": 18, "mature_posts": 18, "with_metric": 15}
    assert any("3 of 18 post(s) have no engagement rate" in n for n in res["data_notes"])

    r = await c.get(f"/api/v1/insights?brand_id={bid}", headers=h)
    assert r.status_code == 200, r.text
    items = r.json()["items"]
    fmt = next(i for i in items if i["kind"] == "format")
    assert fmt["statement"] == ("Carousel posts performed 43% better than single-image posts on engagement rate "
                                "(n=6 vs 9; early signal).")
    assert fmt["confidence"] == "low" and fmt["n"] == 15 and fmt["status"] == "new" and fmt["ai_run_id"] is None
    assert not any("TikTok" in i["statement"] or "short-video" in i["statement"] for i in items)   # missing ≠ zero
    r = await c.get(f"/api/v1/insights?brand_id={bid}&kind=timing", headers=h)
    assert r.status_code == 200 and r.json()["items"] == []

    r = await c.post("/api/v1/insights/analyze", headers=h, json={"brand_id": bid, "period_days": 30})
    assert r.status_code == 200 and r.json()["insights_created"] == 0         # same day, same statements → no duplicates

    r = await c.get(f"/api/v1/insights/recommendations?brand_id={bid}&status=proposed", headers=h)
    assert r.status_code == 200
    rec = next(x for x in r.json()["items"] if x["insight_id"] == fmt["id"])
    assert rec["target"]["format"] == "carousel" and rec["priority"] == "p3"
    r = await c.patch(f"/api/v1/insights/recommendations/{rec['id']}", headers=h, json={"status": "accepted"})
    assert r.status_code == 200, r.text
    dec = r.json()
    assert dec["status"] == "accepted" and dec["decided_by"] == str(env["user_id"]) and dec["applied_to"]["memory_id"]
    assert "ideation_run_id" not in dec["applied_to"]                           # no AI → no ideation run
    async with SessionLocal() as db:
        mem = await db.get(Memory, uuid.UUID(dec["applied_to"]["memory_id"]))
        assert mem is not None and mem.kind == "performance" and "Accepted recommendation" in mem.text
    r = await c.patch(f"/api/v1/insights/recommendations/{rec['id']}", headers=h, json={"status": "maybe"})
    assert r.status_code == 422
    r = await c.post(f"/api/v1/insights/{fmt['id']}/acknowledge", headers=h)
    assert r.status_code == 200 and r.json()["status"] == "acknowledged"
    r = await c.get(f"/api/v1/insights/{uuid.uuid4()}", headers=h)
    assert r.status_code == 404

    # ---- report: enqueue → ready → export --------------------------------------------------------------------
    today = datetime.now(UTC).date()
    r = await c.post("/api/v1/reports", headers=h, json={"kind": "weekly_performance", "brand_id": bid,
                                                         "period_start": (today - timedelta(days=29)).isoformat(),
                                                         "period_end": today.isoformat(),
                                                         "recipients": [str(env["user_id"]), "in_app"]})
    assert r.status_code == 202, r.text
    created = r.json()
    rid = created["report_id"]
    assert created["status"] == "generating" and created["run_id"] is None and created["id"] == rid

    deadline = time.monotonic() + 10
    report = None
    while time.monotonic() < deadline:
        r = await c.get(f"/api/v1/reports/{rid}", headers=h)
        assert r.status_code == 200
        report = r.json()
        if report["status"] != "generating" or await _report_job_state(rid) in ("failed", "succeeded", "cancelled"):
            break
        await asyncio.sleep(0.5)
    if report is None or report["status"] == "generating":   # no (up-to-date) worker running: run the job inline
        async with SessionLocal() as db:
            await set_workspace(db, env["ws"])
            out = await ReportService.generate(db, uuid.UUID(rid), workspace_id=env["ws"])
            await db.commit()
        assert out["status"] in ("ready",), out
        r = await c.get(f"/api/v1/reports/{rid}", headers=h)
        report = r.json()
    assert report["status"] == "ready", report
    headings = [s["heading"] for s in report["sections"]]
    assert headings[:3] == ["Highlights", "Accounts", "Top posts"] and "Insights" in headings and "Recommendations" in headings
    assert report["summary"].startswith("Pedal Co published 18 post(s)")
    assert report["data"]["kpis"]["impressions"]["coverage"] == 15 and report["data"]["kpis"]["impressions"]["value"] == 15000
    assert report["data_pack_version"] == 1 and report["narrative_status"] is None
    assert report["rendered_object_key"].endswith(f"{rid}.html")                 # HTML stored in the reports bucket
    assert [d["status"] for d in report["delivery"]] == ["sent", "queued"]       # user (in-app + HTML email), in_app channel
    async with SessionLocal() as db:   # automation template entry point
        weekly = await ReportService.weekly_performance_pack(db, env["brand_id"], today)
    start = datetime.fromisoformat(weekly["period"]["start"]).date()
    assert weekly["kind"] == "weekly_performance" and start.weekday() == 0 and weekly["period"]["days"] == 7
    assert "kpis" in weekly and "upcoming" in weekly and "competitors" in weekly

    r = await c.get(f"/api/v1/reports/{rid}/export?format=markdown", headers=h)
    assert r.status_code == 200, r.text
    assert r.headers["content-type"].startswith("text/markdown")
    assert r.headers["content-disposition"].startswith("attachment; filename=") and ".md" in r.headers["content-disposition"]
    assert r.text.startswith("# Weekly performance report — Pedal Co") and "## Highlights" in r.text
    r = await c.get(f"/api/v1/reports/{rid}/export?format=html", headers=h)
    assert r.status_code == 200 and r.text.startswith("<!doctype html>") and "<table" in r.text
    r = await c.get(f"/api/v1/reports/{rid}/export?format=pdf", headers=h)
    assert r.status_code == 501 and r.json()["type"].endswith("pdf_not_available")

    r = await c.get(f"/api/v1/reports?brand_id={bid}&status=ready", headers=h)
    assert r.status_code == 200 and [x["id"] for x in r.json()["items"]] == [rid]
    r = await c.post("/api/v1/reports", headers=h, json={"kind": "weekly_performance", "brand_id": bid,
                                                         "period_start": today.isoformat(),
                                                         "period_end": (today - timedelta(days=1)).isoformat()})
    assert r.status_code == 422
    r = await c.delete(f"/api/v1/reports/{rid}", headers=h)
    assert r.status_code == 204
    r = await c.get(f"/api/v1/reports/{rid}", headers=h)
    assert r.status_code == 404

    async with SessionLocal() as db:   # events were written in the outbox for the relay
        names = set((await db.execute(text("SELECT name FROM events_outbox WHERE workspace_id = :ws"),
                                      {"ws": str(env["ws"])})).scalars())
    assert {"AI_ANALYSIS_COMPLETED", "RECOMMENDATION_CREATED", "REPORT_GENERATED"} <= names


async def test_ai_path_and_agent_output(env, monkeypatch) -> None:
    """With a provider configured: analyze → 202 run; the analyst's output, the fallback after a failed run, the report
    narrative and the insights.save tool are persisted. Runs are created without being enqueued (no model call)."""
    import app.services.insight_service as IS
    import app.services.report_service as RS
    from app.agents.orchestrator.service import AIService
    from app.core.db import SessionLocal, set_workspace
    from app.models.ai import AIRun
    from app.services.insight_service import InsightService
    from app.services.report_service import ReportService
    from app.tools.insights import insights_save
    from app.tools.registry import ToolContext
    c, h, bid, ws = env["client"], env["h"], str(env["brand_id"]), env["ws"]

    async def configured(*_a, **_k) -> bool:
        return True

    async def start(db, member, *, agent, action, message, brand_id, inputs):
        return await AIService().create_run(db, member, message=message, brand_id=brand_id, mode="tool", agent=agent,
                                            action=action, inputs=inputs, enqueue=False)

    for mod in (IS, RS):
        monkeypatch.setattr(mod, "ai_configured", configured)
        monkeypatch.setattr(mod, "start_tool_run", start)

    r = await c.post("/api/v1/insights/analyze", headers=h, json={"brand_id": bid, "period_days": 30})
    assert r.status_code == 202, r.text
    run_id = uuid.UUID(r.json()["run_id"])
    assert r.json()["mode"] == "ai" and r.json()["status_url"].endswith(str(run_id))
    output = {"insights": [{"statement": "Carousel posts beat single images by 43% on engagement rate (stats.compare_groups)",
                            "metric": "engagement_rate", "effect": "+43% engagement rate", "n": 15, "confidence": 0.85,
                            "evidence_ids": ["cg-1"]}],
              "recommendations": [{"action": "Plan two more carousels next week", "rationale": "Carousels outperform",
                                   "priority": "high", "links_to": "format", "target": "carousel"}]}
    async with SessionLocal() as db:
        await set_workspace(db, ws)
        run = await db.get(AIRun, run_id)
        assert run.input["agent"] == "performance_analyst" and run.input["inputs"]["fallback"] == "deterministic"
        assert run.input["inputs"]["evidence_pack"]["coverage"]["with_metric"] == 15
        run.result = {"deliverables": {"t1": output}}
        first = await InsightService.apply_agent_output(db, run)
        again = await InsightService.apply_agent_output(db, run)
        await db.commit()
    assert first == {"applied": True, "insights_created": 1, "recommendations_created": 1}
    assert again["insights_created"] == 0 and again["recommendations_created"] == 0      # idempotent per run
    items = (await c.get(f"/api/v1/insights?brand_id={bid}", headers=h)).json()["items"]
    ai_ins = next(i for i in items if i["ai_run_id"] == str(run_id))
    assert ai_ins["kind"] == "format" and ai_ins["confidence"] == "medium" and ai_ins["effect_size"] == 0.43
    recs = (await c.get(f"/api/v1/insights/recommendations?insight_id={ai_ins['id']}", headers=h)).json()["items"]
    assert len(recs) == 1 and recs[0]["priority"] == "p1" and recs[0]["target"]["format"] == "carousel"

    # a failed AI analysis falls back to the deterministic insights from the stored evidence pack (once)
    r = await c.post("/api/v1/insights/analyze", headers=h, json={"brand_id": bid, "period_days": 30})
    run2_id = uuid.UUID(r.json()["run_id"])
    async with SessionLocal() as db:
        await set_workspace(db, ws)
        run2 = await db.get(AIRun, run2_id)
        fb = await InsightService.fallback_after_failed_run(db, run2)
        fb2 = await InsightService.fallback_after_failed_run(db, run2)
        await db.commit()
    assert fb["mode"] == "deterministic" and fb["insights_created"] == 1 and fb2["applied"] is False

    # the tool path (performance_analyst calling insights.save inside its run)
    async with SessionLocal() as db:
        await set_workspace(db, ws)
        ctx = ToolContext(workspace_id=ws, brand_id=env["brand_id"], user_id=env["user_id"], role="owner", run_id=run2_id,
                          agent_id="performance_analyst", db=db)
        saved = await insights_save(ctx, insights=[{"statement": "Posts at 10:00 performed best", "n": 5}])
        await db.commit()
    assert saved["saved"] == 1
    tool_ins = (await c.get(f"/api/v1/insights/{saved['insight_ids'][0]}", headers=h)).json()
    assert tool_ins["kind"] == "timing" and tool_ins["statement"].endswith("(early signal).")

    # report with an AI narrative: deterministic report first, narrative merged when the run completes
    r = await c.post("/api/v1/reports", headers=h, json={"kind": "custom", "brand_id": bid})
    assert r.status_code == 202, r.text
    rid, run3_id = r.json()["report_id"], r.json()["run_id"]
    assert run3_id and r.json()["narrative_status"] == "pending"
    async with SessionLocal() as db:
        await set_workspace(db, ws)
        await ReportService.generate(db, uuid.UUID(rid), workspace_id=ws)
        run3 = await db.get(AIRun, uuid.UUID(run3_id))
        assert run3.input["agent"] == "report" and run3.input["inputs"]["report_id"] == rid
        run3.result = {"deliverables": {"t1": {"title": "Custom report", "summary": "Carousels carried the month.",
                                               "sections": [{"heading": "What worked", "markdown": "- Carousels",
                                                             "sources": []}]}}}
        applied = await ReportService.apply_agent_output(db, run3)
        await db.commit()
    assert applied == {"applied": True, "report_id": rid}
    rep = (await c.get(f"/api/v1/reports/{rid}", headers=h)).json()
    assert rep["status"] == "ready" and rep["narrative_status"] == "ready"
    assert rep["sections"][0]["heading"] == "Narrative summary ✦" and rep["sections"][0]["origin"] == "ai"
    assert rep["summary"] == "Carousels carried the month." and rep["sections"][1]["heading"] == "Highlights"
    md = (await c.get(f"/api/v1/reports/{rid}/export?format=md", headers=h)).text
    assert "## Narrative summary ✦" in md and "### What worked" in md

    # the AI run can't start → the analysis still completes deterministically and no queued run is left behind
    async def boom(*_a, **_k):
        raise RuntimeError("provider down")
    monkeypatch.setattr(IS, "start_tool_run", boom)
    async with SessionLocal() as db:
        before = (await db.execute(text("SELECT count(*) FROM ai_runs WHERE workspace_id = :ws"), {"ws": str(ws)})).scalar()
    r = await c.post("/api/v1/insights/analyze", headers=h, json={"brand_id": bid, "period_days": 30})
    assert r.status_code == 200 and r.json()["mode"] == "deterministic"
    async with SessionLocal() as db:
        after = (await db.execute(text("SELECT count(*) FROM ai_runs WHERE workspace_id = :ws"), {"ws": str(ws)})).scalar()
    assert after == before

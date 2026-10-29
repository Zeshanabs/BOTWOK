"""Content → variant → approval flow against the real local Postgres (doc 17, doc 19 §19.7).

Seeds an isolated workspace (owner, editor, viewer) + brand directly through the ORM, drives the API with httpx,
then deletes everything it created.
"""
from __future__ import annotations

import uuid

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy import delete, select, text

pytestmark = pytest.mark.integration


@pytest_asyncio.fixture
async def env():
    from app.core.db import SessionLocal, engine
    from app.core.security import create_access_token
    from app.main import app
    from app.models import Brand, BrandSettings, User, Workspace, WorkspaceMember
    from app.models.enums import MemberRole

    await engine.dispose()  # fresh pool on this test's event loop
    tag = uuid.uuid4().hex[:10]
    async with SessionLocal() as db:
        users = {r: User(email=f"{r}-{tag}@test.local", full_name=f"{r.title()} {tag}") for r in ("owner", "editor", "viewer")}
        db.add_all(users.values())
        await db.flush()
        ws = Workspace(name=f"Content WS {tag}", slug=f"content-ws-{tag}", created_by=users["owner"].id)
        db.add(ws)
        await db.flush()
        for r, u in users.items():
            db.add(WorkspaceMember(workspace_id=ws.id, user_id=u.id, role=MemberRole(r)))
        brand = Brand(workspace_id=ws.id, name="Acme", slug=f"acme-{tag}", created_by=users["owner"].id)
        db.add(brand)
        await db.flush()
        db.add(BrandSettings(brand_id=brand.id, workspace_id=ws.id,
                             topics={"hashtags": {"core": ["RevenueCycle"], "banned": ["followme"]},
                                     "keywords": ["claim denials"]},
                             policies={"forbidden_topics": ["casino"]}))
        await db.commit()
        ids = {"ws": ws.id, "brand": brand.id, **{r: u.id for r, u in users.items()}}

    def headers(role: str) -> dict[str, str]:
        tok = create_access_token(ids[role], ids["ws"], role)
        return {"Authorization": f"Bearer {tok}", "X-Workspace-Id": str(ids["ws"])}

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        yield {"client": client, "h": headers, **ids}

    async with SessionLocal() as db:
        await db.execute(text("DELETE FROM events_outbox WHERE workspace_id = :ws"), {"ws": str(ids["ws"])})
        await db.execute(delete(Workspace).where(Workspace.id == ids["ws"]))
        await db.execute(delete(User).where(User.id.in_([ids["owner"], ids["editor"], ids["viewer"]])))
        await db.commit()
    await engine.dispose()


async def _outbox_names(ws: uuid.UUID) -> list[str]:
    from app.core.db import SessionLocal
    async with SessionLocal() as db:
        rows = (await db.execute(text("SELECT name FROM events_outbox WHERE workspace_id = :ws ORDER BY id"),
                                 {"ws": str(ws)})).scalars().all()
    return list(rows)


async def test_content_variant_approval_flow(env):
    c, h, brand = env["client"], env["h"], str(env["brand"])

    # viewer cannot create content
    r = await c.post("/api/v1/content", json={"brand_id": brand, "title": "nope"}, headers=h("viewer"))
    assert r.status_code == 403, r.text

    # editor creates a draft
    r = await c.post("/api/v1/content", headers=h("editor"), json={
        "brand_id": brand, "title": "Five ways to cut claim denials", "content_type": "educational",
        "master_format": "text", "body": {"hook": "Denials are eating your margin.", "body_md": "Here is how.",
                                          "hashtags": ["RevenueCycle"]}})
    assert r.status_code == 201, r.text
    item = r.json()
    cid = item["id"]
    assert item["status"] == "draft" and item["approval_required"] is True and item["current_version"] == 1

    # variant with validation
    r = await c.post(f"/api/v1/content/{cid}/variants", headers=h("editor"), json={
        "platform": "linkedin", "format": "text", "text": "Denials are eating your margin. Here is how to fix it.",
        "hashtags": ["RevenueCycle", "MedicalBilling"]})
    assert r.status_code == 201, r.text
    variant = r.json()
    assert variant["status"] == "draft" and variant["validation"]["ok"] is True
    vid = variant["id"]

    # invalid variant: X text over 280 → stored with validation errors; unsupported format → 422
    r = await c.post(f"/api/v1/content/{cid}/variants", headers=h("editor"),
                     json={"platform": "x", "format": "text", "text": "a" * 300})
    assert r.status_code == 201 and r.json()["validation"]["ok"] is False
    assert any(i["code"] == "text_too_long" for i in r.json()["validation"]["issues"])
    r = await c.post(f"/api/v1/content/{cid}/variants", headers=h("editor"),
                     json={"platform": "tiktok", "format": "text", "text": "hi"})
    assert r.status_code == 422, r.text

    # edit body → new version; variant edit → new variant version
    r = await c.patch(f"/api/v1/content/{cid}", headers=h("editor"), json={"body": {"cta": "Book a 15-min audit"}})
    assert r.status_code == 200, r.text
    assert r.json()["current_version"] == 2 and r.json()["body"]["hook"] == "Denials are eating your margin."
    r = await c.patch(f"/api/v1/content/{cid}/variants/{vid}", headers=h("editor"), json={"text": "Shorter text."})
    assert r.status_code == 200 and r.json()["current_version"] == 2
    r = await c.get(f"/api/v1/content/{cid}/versions", headers=h("viewer"))
    assert r.status_code == 200
    versions = {(v["target_type"], v["version"]) for v in r.json()}
    assert {("item", 1), ("item", 2), ("variant", 1), ("variant", 2)} <= versions
    r = await c.post(f"/api/v1/content/{cid}/versions/1/restore", headers=h("editor"))
    assert r.status_code == 200, r.text
    assert r.json()["current_version"] == 3 and "cta" not in r.json()["body"]
    r = await c.get("/api/v1/content", headers=h("viewer"), params={"cursor": "not-a-cursor"})
    assert r.status_code == 422

    # list with filters
    r = await c.get("/api/v1/content", headers=h("viewer"), params={"brand_id": brand, "platform": "linkedin", "q": "denials"})
    assert r.status_code == 200 and [i["id"] for i in r.json()["items"]] == [cid]

    # request approval → needs_review + pending approval
    r = await c.post(f"/api/v1/content/{cid}/request-approval", headers=h("editor"), json={"comment": "ready"})
    assert r.status_code == 201, r.text
    approval = r.json()
    assert approval["status"] == "pending" and approval["kind"] == "content"
    assert set(approval["required_roles"]) == {"approver", "admin", "owner"}
    aid = approval["id"]
    r = await c.get(f"/api/v1/content/{cid}", headers=h("editor"))
    assert r.json()["status"] == "needs_review"

    # editor cannot approve
    r = await c.post(f"/api/v1/approvals/{aid}/approve", headers=h("editor"), json={})
    assert r.status_code == 403, r.text

    # approvals inbox + detail preview
    r = await c.get("/api/v1/approvals", headers=h("owner"))
    assert r.status_code == 200 and aid in [a["id"] for a in r.json()["items"]]
    r = await c.get(f"/api/v1/approvals/{aid}", headers=h("owner"))
    assert r.status_code == 200, r.text
    detail = r.json()
    assert detail["target"]["item"]["id"] == cid and len(detail["target"]["variants"]) == 2

    # owner approves
    r = await c.post(f"/api/v1/approvals/{aid}/approve", headers=h("owner"), json={"comment": "ship it"})
    assert r.status_code == 200, r.text
    assert r.json()["status"] == "approved" and r.json()["decided_by"] == str(env["owner"])
    r = await c.get(f"/api/v1/content/{cid}", headers=h("editor"))
    body = r.json()
    assert body["status"] == "approved"
    assert {v["status"] for v in body["variants"]} == {"approved"}

    # second decision on the same approval → 409; approved content is locked
    r = await c.post(f"/api/v1/approvals/{aid}/approve", headers=h("owner"), json={})
    assert r.status_code == 409
    r = await c.patch(f"/api/v1/content/{cid}", headers=h("editor"), json={"title": "changed"})
    assert r.status_code == 409 and "content_locked" in r.json()["type"]

    # back to draft (no live schedules), then request changes path
    r = await c.post(f"/api/v1/content/{cid}/transition", headers=h("editor"), json={"to": "draft"})
    assert r.status_code == 200 and r.json()["status"] == "draft"
    r = await c.post(f"/api/v1/content/{cid}/transition", headers=h("editor"), json={"to": "approved"})
    assert r.status_code == 409  # draft → approved is not a valid transition
    r = await c.post(f"/api/v1/content/{cid}/request-approval", headers=h("editor"), json={})
    aid2 = r.json()["id"]
    r = await c.post(f"/api/v1/approvals/{aid2}/reject", headers=h("owner"), json={"comment": ""})
    assert r.status_code == 422
    r = await c.post(f"/api/v1/approvals/{aid2}/reject", headers=h("owner"),
                     json={"comment": "tighten the hook", "decision": "request_changes"})
    assert r.status_code == 200 and r.json()["status"] == "rejected"
    r = await c.get(f"/api/v1/content/{cid}", headers=h("editor"))
    assert r.json()["status"] == "draft"

    # archive is admin-only
    r = await c.post(f"/api/v1/content/{cid}/transition", headers=h("editor"), json={"to": "archived"})
    assert r.status_code == 403
    r = await c.post(f"/api/v1/content/{cid}/transition", headers=h("owner"), json={"to": "archived"})
    assert r.status_code == 200 and r.json()["status"] == "archived"

    names = await _outbox_names(env["ws"])
    for ev in ("CONTENT_CREATED", "VARIANT_CREATED", "CONTENT_UPDATED", "CONTENT_STATUS_CHANGED", "APPROVAL_REQUESTED",
               "CONTENT_APPROVED", "CONTENT_REJECTED"):
        assert ev in names, ev


async def test_ideas_campaigns_and_promotion(env):
    from app.core.db import SessionLocal
    from app.models import ContentVersion
    c, h, brand = env["client"], env["h"], str(env["brand"])

    r = await c.post("/api/v1/campaigns", headers=h("editor"), json={"brand_id": brand, "name": "Q1 denial push",
                                                                     "starts_on": "2026-01-05", "ends_on": "2026-03-31"})
    assert r.status_code == 201, r.text
    camp = r.json()["id"]
    r = await c.post("/api/v1/campaigns", headers=h("editor"), json={"brand_id": brand, "name": "bad", "starts_on": "2026-03-01",
                                                                     "ends_on": "2026-01-01"})
    assert r.status_code == 422
    r = await c.delete(f"/api/v1/campaigns/{camp}", headers=h("editor"))
    assert r.status_code == 403

    idea = {"brand_id": brand, "title": "Why prior authorization delays cost clinics money", "angle": "cost of delay",
            "campaign_id": camp, "platforms": ["linkedin", "x"], "formats": ["text"], "hooks": ["Prior auth is a tax."]}
    r = await c.post("/api/v1/ideas", headers=h("editor"), json=idea)
    assert r.status_code == 201, r.text
    iid = r.json()["id"]
    r = await c.post("/api/v1/ideas", headers=h("editor"), json=idea)  # near-duplicate is flagged, not blocked
    assert r.status_code == 201 and r.json()["evidence"]["possible_duplicate"]["id"] == iid

    r = await c.get("/api/v1/ideas", headers=h("viewer"), params={"brand_id": brand})
    assert r.status_code == 200 and len(r.json()["items"]) == 2
    r = await c.patch(f"/api/v1/ideas/{iid}", headers=h("editor"), json={"status": "shortlisted"})
    assert r.status_code == 200 and r.json()["status"] == "shortlisted"

    r = await c.post(f"/api/v1/ideas/{iid}/promote", headers=h("editor"), json={})
    assert r.status_code == 201, r.text
    item = r.json()
    assert item["idea_id"] == iid and item["campaign_id"] == camp and item["body"]["hook"] == "Prior auth is a tax."
    r = await c.post(f"/api/v1/ideas/{iid}/promote", headers=h("editor"), json={})
    assert r.status_code == 409
    async with SessionLocal() as db:
        n = (await db.execute(select(ContentVersion).where(ContentVersion.target_id == uuid.UUID(item["id"])))).scalars().all()
    assert len(n) == 1 and n[0].author_type == "user"

    r = await c.delete(f"/api/v1/content/{item['id']}", headers=h("editor"))
    assert r.status_code == 204
    r = await c.get(f"/api/v1/content/{item['id']}", headers=h("editor"))
    assert r.status_code == 404


async def test_agent_tools_persist_drafts_and_route_risk(env):
    """Agent path: content.create_draft → content.save_critique / content.save_factcheck → status routing (never approved)."""
    from app.core.db import SessionLocal
    from app.models import ContentItem, ContentSource, ContentVersion, ResearchSource
    from app.tools.content import (
        content_create_draft,
        content_create_variant,
        content_get,
        content_save_critique,
        content_save_factcheck,
        hashtags_suggest,
        ideas_save,
        platform_rules,
        policy_check_tool,
    )
    from app.tools.registry import ToolContext

    c, h, ws, brand = env["client"], env["h"], env["ws"], env["brand"]
    run_id = uuid.uuid4()
    async with SessionLocal() as db:
        src = ResearchSource(workspace_id=ws, canonical_url="https://example.org/denials", domain="example.org",
                             title="Denial report")
        db.add(src)
        await db.flush()

        def ctx(agent: str) -> ToolContext:
            return ToolContext(workspace_id=ws, brand_id=brand, user_id=env["editor"], role="editor", run_id=run_id,
                               agent_id=agent, db=db)

        # 1. writer saves a claim-free draft → ai_generated, version authored by the agent, first variant validated
        res = await content_create_draft(ctx("writer"), title="how we plan the week", hook="planning beats hustle.",
                                         body_md="here is the simple routine our team follows every monday.",
                                         cta="what does your routine look like?", hashtags=["planning"],
                                         keywords=["planning"], visual_concept="desk flat-lay", alt_text="a desk",
                                         platform="linkedin", format="text", content_type="educational",
                                         sources=[{"claim": "routine", "source_id": str(src.id)},
                                                  {"claim": "ghost", "source_id": str(uuid.uuid4())}],
                                         generation_metadata={"model": "fake", "prompt_version": 3})
        cid = uuid.UUID(res["content_id"])
        assert res["status"] == "ai_generated" and res["validation"]["ok"] is True
        assert res["sources"] == {"attached": 1, "skipped": [res["sources"]["skipped"][0]]}
        item = (await db.execute(select(ContentItem).where(ContentItem.id == cid))).scalar_one()
        assert item.ai_generated and item.generation_metadata["model"] == "fake"
        assert item.generation_metadata["run_id"] == str(run_id)
        vers = (await db.execute(select(ContentVersion).where(ContentVersion.target_id == cid))).scalars().all()
        assert {(v.author_type, v.author_id) for v in vers} >= {("agent", "writer")}
        assert (await db.execute(select(ContentSource).where(ContentSource.content_item_id == cid))).scalars().all()

        # 2. repurposer adds an X thread variant; critic passes → needs_review (no claims → no fact-check needed)
        v = await content_create_variant(ctx("repurposer"), content_id=str(cid), platform="x", format="text",
                                         segments=["1/ planning beats hustle", "2/ our monday routine"],
                                         changes_made=["split into a thread"])
        assert v["validation"]["ok"] is True and v["status"] == "ai_generated"
        r = await content_save_critique(ctx("critic"), target_type="item", target_id=str(cid),
                                        critique={"scores": {"quality": 0.8, "risk": 0.1}, "recommend": "approve",
                                                  "risk_level": "low"})
        assert r["status"] == "needs_review" and r["risk_level"] == "low"
        got = await content_get(ctx("critic"), content_id=str(cid))
        assert len(got["variants"]) == 2 and got["critique"]["recommend"] == "approve"

        # 3. a draft with a factual claim waits for fact-check; a contradicted claim → high risk, approval blocked
        res2 = await content_create_draft(ctx("writer"), title="denials", hook="Denials cost clinics 5% of revenue.",
                                          body_md="fix the top three causes.", platform="linkedin", format="text")
        cid2 = res2["content_id"]
        r = await content_save_critique(ctx("critic"), target_type="item", target_id=cid2,
                                        critique={"scores": {"quality": 0.7, "risk": 0.2}, "recommend": "approve"})
        assert r["status"] == "ai_generated"  # fact-check still pending
        r = await content_save_factcheck(ctx("fact_check"), target_type="item", target_id=cid2, factcheck={
            "claims": [{"text": "Denials cost clinics 5% of revenue.", "verdict": "contradicted"}],
            "overall_risk": "high"})
        assert r["status"] == "needs_review" and r["risk_level"] == "high"

        # 4. deterministic policy block (forbidden topic) → rejected, never approved
        res3 = await content_create_draft(ctx("writer"), title="weekend fun", hook="our team night at the casino",
                                          body_md="good times", platform="linkedin", format="text")
        assert res3["status"] == "rejected"

        # 5. read tools
        tags = await hashtags_suggest(ctx("writer"), platform="instagram", text="fixing claim denials fast", k=5)
        names = [t["tag"] for t in tags["hashtags"]]
        assert "RevenueCycle" in names and "followme" not in [n.lower() for n in names]
        pr = await platform_rules(ctx("repurposer"), platform="x", format="text")
        assert pr["rules"]["text"]["max"] == 280 and "PLATFORM RULES" in pr["summary"]
        pc = await policy_check_tool(ctx("critic"), text="visit the casino")
        assert pc["blocked"] is True

        # 6. ideas.save dedupes within the batch and against the DB
        saved = await ideas_save(ctx("ideation"), ideas=[
            {"title": "prior auth myths", "angle": "myth busting", "hook_options": ["myth 1"], "platforms": ["linkedin"]},
            {"title": "Prior auth myths", "angle": "myth busting"},
        ])
        assert saved["saved_count"] == 1 and saved["dropped"][0]["reason"] == "duplicate_in_batch"
        again = await ideas_save(ctx("ideation"), ideas=[{"title": "prior auth myths", "angle": "myth busting"}])
        assert again["saved_count"] == 0 and again["dropped"][0]["reason"] == "duplicate"
        await db.commit()

    # contradicted claims block approval even for the owner; high risk demands admin/owner on the approval
    r = await c.post(f"/api/v1/content/{cid2}/request-approval", headers=h("editor"), json={})
    assert r.status_code == 201 and set(r.json()["required_roles"]) == {"admin", "owner"}
    r = await c.post(f"/api/v1/approvals/{r.json()['id']}/approve", headers=h("owner"), json={})
    assert r.status_code == 409 and "contradicted_claims" in r.json()["type"]
    r = await c.get(f"/api/v1/content/{cid2}", headers=h("viewer"))
    assert r.json()["status"] == "needs_review"

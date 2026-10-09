"""Idempotent seed: `python -m app.seed`.

- ai_agents registry (13 agents, doc 00 §5) — only when the table is empty (the AI builder may seed richer rows).
- APP_ENV=local: demo user demo@botwok.local / botwok-demo, owner of "Demo Workspace" (slug `demo`).
- Default usage_budgets for the demo workspace (ai_cost: month 50, day 10).
"""
from __future__ import annotations

import asyncio
from typing import Any

from sqlalchemy import func, select

from app.config import settings
from app.core.db import SessionLocal
from app.core.logging import configure_logging, get_logger
from app.core.security import hash_password
from app.models.ai import AIAgent
from app.models.enums import MemberRole
from app.models.identity import User, Workspace, WorkspaceMember
from app.services.audit_service import audit
from app.services.workspace_service import WorkspaceService

log = get_logger("seed")

DEMO_EMAIL = "demo@botwok.local"
DEMO_PASSWORD = "botwok-demo"
DEMO_WORKSPACE = "Demo Workspace"
DEMO_SLUG = "demo"

# (id, name, tier, description, tools)
AGENTS: list[tuple[str, str, str, str, list[str]]] = [
    ("research", "Research", "balanced", "Web search, fetch, extract, rank, dedupe, summarize, cite",
     ["web.search", "web.fetch", "research.save_source", "research.read_source", "research.find_similar"]),
    ("social_listening", "Social Listening", "balanced", "Public social content via permitted APIs; audience signals",
     ["web.search", "research.find_similar"]),
    ("competitor_intel", "Competitor Intel", "powerful", "Build and analyze competitor profiles from allowed sources",
     ["web.search", "web.fetch", "research.read_source"]),
    ("trend", "Trend", "balanced", "Detect and label trends across news, social and keyword signals",
     ["web.search", "research.find_similar"]),
    ("strategy", "Strategy", "powerful", "Pillars, mix, platform strategy, campaigns, planning recommendations",
     ["brand.get_context", "research.find_similar"]),
    ("ideation", "Ideation", "cheap", "High-volume content ideas from strategy, research and performance",
     ["brand.get_context", "research.find_similar"]),
    ("writer", "Writer", "powerful", "Master content and first-platform drafts (hook/body/CTA/hashtags)",
     ["brand.get_context", "content.create_draft", "platform.rules", "hashtags.suggest", "research.read_source"]),
    ("repurposer", "Repurposer", "balanced", "Master → per-platform variants under platform rules",
     ["brand.get_context", "content.create_variant", "platform.rules", "hashtags.suggest"]),
    ("visual", "Visual", "balanced", "Visual concepts, image prompts, carousel layouts, video scripts",
     ["brand.get_context", "media.generate_image"]),
    ("critic", "Critic", "balanced", "Quality, brand, platform and policy scoring with rewrite suggestions",
     ["brand.get_context", "platform.rules"]),
    ("fact_check", "Fact Check", "balanced", "Claim extraction and verification against sources",
     ["web.search", "web.fetch", "research.read_source"]),
    ("performance_analyst", "Performance Analyst", "powerful", "Insights and recommendations from normalized metrics",
     ["brand.get_context"]),
    ("report", "Report", "balanced", "Compose reports (competitor, weekly, performance) from stored data",
     ["brand.get_context", "research.read_source"]),
]


async def seed_agents(db: Any) -> int:
    if (await db.execute(select(func.count()).select_from(AIAgent))).scalar_one() > 0:
        return 0
    for agent_id, name, tier, description, tools in AGENTS:
        db.add(AIAgent(id=agent_id, name=name, tier=tier, description=description, tools=tools,
                       actions={"default": {"description": description}}, limits={"max_turns": 8, "max_tool_calls": 20},
                       enabled=True))
    await db.flush()
    return len(AGENTS)


async def seed_demo(db: Any) -> Workspace | None:
    user = (await db.execute(select(User).where(User.email == DEMO_EMAIL))).scalar_one_or_none()
    if user is None:
        user = User(email=DEMO_EMAIL, password_hash=await asyncio.to_thread(hash_password, DEMO_PASSWORD), full_name="Demo User",
                    preferences={})
        db.add(user)
        await db.flush()
        await audit(db, {"type": "system", "id": "seed"}, "seed.demo_user", "user", user.id)
    ws = (await db.execute(select(Workspace).where(Workspace.slug == DEMO_SLUG))).scalar_one_or_none()
    if ws is None:
        owned = (await db.execute(select(Workspace).join(WorkspaceMember, WorkspaceMember.workspace_id == Workspace.id)
                                  .where(WorkspaceMember.user_id == user.id, Workspace.name == DEMO_WORKSPACE))).scalars().first()
        ws = owned or await WorkspaceService.create(db, user, DEMO_WORKSPACE, DEMO_SLUG, with_default_budgets=False)
    if await WorkspaceService.membership(db, ws.id, user.id) is None:
        db.add(WorkspaceMember(workspace_id=ws.id, user_id=user.id, role=MemberRole.owner))
    await WorkspaceService.ensure_default_budgets(db, ws.id)
    await db.flush()
    return ws


async def main() -> None:
    configure_logging(settings.log_level)
    async with SessionLocal() as db:
        n = await seed_agents(db)
        ws = await seed_demo(db) if settings.app_env == "local" else None
        await db.commit()
    log.info("seed.done", agents_inserted=n, demo_workspace=str(ws.id) if ws else None)
    demo = f"{ws.slug} ({ws.id})" if ws else "skipped (APP_ENV != local)"
    print(f"seed: agents inserted={n}; demo workspace={demo}")


if __name__ == "__main__":
    asyncio.run(main())

"""RunContext + ContextBuilder (doc 05 §5.2.2): brand context, preferences, conversation (last 6 turns + summary),
top-k memories, budget, AI settings, trust policy, canary."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any
from uuid import UUID

from sqlalchemy import select

from app.agents.base import new_canary
from app.agents.orchestrator.memory import MemoryBundle, MemoryService
from app.config import settings
from app.core.logging import get_logger
from app.core.ports.ai_provider import Message
from app.models.ai import AIMessage, AIRun
from app.tools.brand import build_brand_context

log = get_logger("ai.context")


@dataclass
class Budget:
    max_cost_usd: float = settings.default_run_budget_usd
    max_tokens: int = 400_000
    max_tool_calls: int = 120
    max_wall_seconds: int = 900

    @classmethod
    def from_run(cls, run: AIRun, ai_settings: dict[str, Any] | None = None) -> Budget:
        b = run.budget or {}
        budgets = (ai_settings or {}).get("budgets", {})
        return cls(max_cost_usd=float(b.get("max_cost_usd") or budgets.get("per_run_usd") or settings.default_run_budget_usd),
                   max_tokens=int(b.get("max_tokens") or 400_000), max_tool_calls=int(b.get("max_tool_calls") or 120),
                   max_wall_seconds=int(b.get("max_wall_seconds") or 900))

    def as_dict(self) -> dict[str, Any]:
        return {"max_cost_usd": self.max_cost_usd, "max_tokens": self.max_tokens, "max_tool_calls": self.max_tool_calls,
                "max_wall_seconds": self.max_wall_seconds}


@dataclass
class TrustPolicy:
    wrap_untrusted: bool = True
    exclude_injection_flagged: bool = True
    canary_check: bool = True
    require_approval_for_ai_content: bool = True


@dataclass
class RunContext:
    run_id: UUID
    workspace_id: UUID
    brand_id: UUID | None
    user_id: UUID | None
    role: str = "editor"
    mode: str = "chat"
    message: str = ""
    brand: str = "BRAND: (not configured)"
    brand_name: str | None = None
    industry: str | None = None
    platforms: list[str] = field(default_factory=list)
    preferences: dict[str, Any] = field(default_factory=dict)
    conversation: list[Message] = field(default_factory=list)
    conversation_summary: str | None = None
    memory: MemoryBundle = field(default_factory=MemoryBundle)
    budget: Budget = field(default_factory=Budget)
    settings: dict[str, Any] = field(default_factory=dict)
    trust_policy: TrustPolicy = field(default_factory=TrustPolicy)
    canary: str | None = None
    run: AIRun | None = None
    conversation_id: UUID | None = None
    intent: dict[str, Any] | None = None
    tool_context: Any = None               # set per task by the runtime (used by agent post-processing hooks)

    @property
    def safety(self) -> dict[str, Any]:
        return self.settings.get("safety", {})

    @property
    def confirm_above_usd(self) -> float:
        return float(self.settings.get("budgets", {}).get("confirm_above_usd", settings.confirm_above_usd))

    @property
    def max_parallel(self) -> int:
        return int(self.settings.get("budgets", {}).get("max_parallel_tasks", settings.max_parallel_tasks))


class ContextBuilder:
    async def build(self, db: Any, run: AIRun, *, memory_k: int = 8) -> RunContext:
        inp = run.input or {}
        message = str(inp.get("message") or "")
        ai_settings = await self._ai_settings(db, run.workspace_id)
        ctx = RunContext(run_id=run.id, workspace_id=run.workspace_id, brand_id=run.brand_id, user_id=run.user_id,
                         role=str(inp.get("role") or "editor"), mode=run.mode, message=message,
                         budget=Budget.from_run(run, ai_settings), settings=ai_settings, run=run,
                         conversation_id=run.conversation_id, intent=run.intent,
                         canary=new_canary() if ai_settings.get("safety", {}).get("canary_check", True) else None)
        ctx.trust_policy = TrustPolicy(exclude_injection_flagged=bool(ai_settings.get("safety", {}).get("exclude_injection_flagged", True)),
                                       canary_check=ctx.canary is not None)
        if run.brand_id:
            ctx.brand = await build_brand_context(db, run.brand_id, mode="compact")
            await self._brand_meta(db, ctx)
        ctx.preferences = await self._preferences(db, run.user_id)
        ctx.conversation, ctx.conversation_summary = await self._conversation(db, run)
        query = message or f"{inp.get('agent', '')} {inp.get('action', '')} {str(inp.get('inputs', ''))[:300]}"
        ctx.memory = await MemoryService().read_bundle(db, run.workspace_id, brand_id=run.brand_id, user_id=run.user_id,
                                                       query=query, k=memory_k)
        if ctx.conversation_summary:
            ctx.memory.conversation_summary = ctx.conversation_summary
        return ctx

    async def _ai_settings(self, db: Any, workspace_id: UUID) -> dict[str, Any]:
        try:
            from app.services.ai_settings_service import AISettingsService
            return await AISettingsService().get(db, workspace_id)
        except Exception as e:  # noqa: BLE001
            log.warning("context.settings_failed", error=str(e)[:200])
            from app.services.ai_settings_service import default_settings
            return default_settings()

    async def _brand_meta(self, db: Any, ctx: RunContext) -> None:
        try:
            from app.models.brand import Brand
            brand = await db.get(Brand, ctx.brand_id)
            if brand is not None:
                ctx.brand_name = brand.name
                ctx.industry = brand.industry
                bs = getattr(brand, "settings", None)
                plats = (bs.platforms if bs is not None else {}) or {}
                ctx.platforms = [p for p, v in plats.items() if not isinstance(v, dict) or v.get("enabled", True)]
        except Exception as e:  # noqa: BLE001
            log.info("context.brand_meta_skipped", error=str(e)[:120])

    async def _preferences(self, db: Any, user_id: UUID | None) -> dict[str, Any]:
        if db is None or user_id is None:
            return {}
        try:
            from app.models.identity import User
            user = await db.get(User, user_id)
            return dict(user.preferences or {}) if user is not None else {}
        except Exception:  # noqa: BLE001
            return {}

    async def _conversation(self, db: Any, run: AIRun) -> tuple[list[Message], str | None]:
        if db is None or run.conversation_id is None:
            return [], None
        try:
            from app.models.ai import AIConversation
            conv = await db.get(AIConversation, run.conversation_id)
            summary = conv.summary if conv is not None else None
            rows = (await db.execute(select(AIMessage).where(AIMessage.conversation_id == run.conversation_id,
                                                             AIMessage.workspace_id == run.workspace_id)
                                     .order_by(AIMessage.created_at.desc()).limit(13))).scalars().all()
            msgs: list[Message] = []
            for r in reversed(list(rows or [])):
                if r.run_id == run.id:
                    continue
                content = r.content or {}
                text = content.get("text") if isinstance(content, dict) else str(content)
                if text and r.role in ("user", "assistant"):
                    msgs.append(Message(role=r.role, content=str(text)))
            return msgs[-6:], summary
        except Exception as e:  # noqa: BLE001
            log.info("context.conversation_skipped", error=str(e)[:120])
            return [], None

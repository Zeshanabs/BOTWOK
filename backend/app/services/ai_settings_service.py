"""AISettingsService: ai_settings (routing/providers/media/search/safety/budgets), provider keys (sealed), prompt
templates with versions (global defaults from app/agents/prompts/*.md), provider status/test, usage summaries."""
from __future__ import annotations

import copy
import time
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.core.crypto import seal, unseal
from app.core.errors import ProblemError, not_found, validation
from app.core.logging import get_logger
from app.integrations.ai.registry import (
    KNOWN_PROVIDERS,
    default_routing,
    env_api_key,
    get_provider,
    merge_routing,
    resolve_model,
)
from app.models.ai import AICall, AISettings, PromptTemplate, ProviderSecret
from app.models.platform import UsageBudget, UsageLedger

log = get_logger("ai.settings")
PROMPTS_DIR = Path(__file__).resolve().parent.parent / "agents" / "prompts"
SECTIONS = ("routing", "providers", "media", "search", "safety", "budgets")
PROVIDERS_WITH_KEYS = ("anthropic", "openai", "xai", "google", "openrouter")


def default_settings() -> dict[str, Any]:
    return {
        "routing": default_routing(),
        "providers": {p: {"enabled": True} for p in KNOWN_PROVIDERS if p != "fake"} | {"ollama": {"enabled": True, "base_url": settings.ollama_base_url}},
        "media": {"image_provider": "openai/gpt-image-1", "video_provider": None, "speech_provider": None,
                  "spend_confirm_above_usd": 1.0, "max_generations_per_day": 50},
        "search": {"providers": ["tavily", "brave", "exa", "searxng"], "cache_ttl_hours": 24, "news_cache_ttl_hours": 1},
        "safety": {"auto_approve": "never", "critic_min_score": 0.6, "high_risk_requires_admin": True,
                   "require_fact_check_for": ["health", "finance", "legal"], "exclude_injection_flagged": True,
                   "canary_check": True},
        "budgets": {"per_run_usd": settings.default_run_budget_usd, "confirm_above_usd": settings.confirm_above_usd,
                    "max_parallel_tasks": settings.max_parallel_tasks, "max_concurrent_runs": 3, "economy_mode": False},
    }


def _deep_merge(base: dict[str, Any], patch: dict[str, Any]) -> dict[str, Any]:
    out = copy.deepcopy(base)
    for k, v in (patch or {}).items():
        if isinstance(v, dict) and isinstance(out.get(k), dict):
            out[k] = _deep_merge(out[k], v)
        else:
            out[k] = copy.deepcopy(v)
    return out


def _aad(workspace_id: UUID, provider: str) -> str:
    return f"provider_secret:{workspace_id}:{provider}"


def load_prompt_file(agent_id: str) -> str | None:
    p = PROMPTS_DIR / f"{agent_id}.md"
    return p.read_text(encoding="utf-8") if p.exists() else None


def list_prompt_files() -> list[str]:
    return sorted(p.stem for p in PROMPTS_DIR.glob("*.md"))


class AISettingsService:
    # -- settings ---------------------------------------------------------------------------------------------------
    async def _row(self, db: AsyncSession, workspace_id: UUID) -> AISettings | None:
        return (await db.execute(select(AISettings).where(AISettings.workspace_id == workspace_id))).scalar_one_or_none()

    async def get(self, db: AsyncSession, workspace_id: UUID) -> dict[str, Any]:
        """Effective settings = defaults deep-merged with the stored row. Provider keys are never returned (status only)."""
        row = await self._row(db, workspace_id)
        eff = default_settings()
        if row is not None:
            for s in SECTIONS:
                stored = getattr(row, s, None) or {}
                if s == "routing":
                    eff["routing"] = merge_routing(eff["routing"], stored)
                else:
                    eff[s] = _deep_merge(eff[s], stored)
        eff["updated_at"] = row.updated_at.isoformat() if row is not None and row.updated_at else None
        return eff

    async def update(self, db: AsyncSession, workspace_id: UUID, patch: dict[str, Any], *, member: Any = None) -> dict[str, Any]:
        unknown = [k for k in patch if k not in SECTIONS]
        if unknown:
            raise validation(f"unknown settings sections: {', '.join(unknown)}")
        for tier in ("cheap", "balanced", "powerful", "embeddings"):
            v = (patch.get("routing") or {}).get(tier)
            spec = v if isinstance(v, str) else (v or {}).get("primary") if isinstance(v, dict) else None
            if spec:
                try:
                    resolve_model(spec)
                except ValueError as e:
                    raise validation(f"routing.{tier}: {e}") from e
        row = await self._row(db, workspace_id)
        before = {s: copy.deepcopy(getattr(row, s)) for s in SECTIONS} if row else None
        if row is None:
            row = AISettings(workspace_id=workspace_id)
            db.add(row)
        for s in SECTIONS:
            if s in patch and isinstance(patch[s], dict):
                setattr(row, s, _deep_merge(getattr(row, s) or {}, patch[s]))
        row.updated_at = datetime.now(UTC)
        await db.flush()
        await self._audit(db, member, "ai_settings.update", "ai_settings", str(workspace_id), before,
                          {s: getattr(row, s) for s in SECTIONS})
        return await self.get(db, workspace_id)

    # -- provider keys ----------------------------------------------------------------------------------------------
    async def set_provider_key(self, db: AsyncSession, workspace_id: UUID, provider: str, api_key: str, *,
                               user_id: UUID | None = None, member: Any = None) -> dict[str, Any]:
        provider = provider.lower()
        if provider not in KNOWN_PROVIDERS or provider == "fake":
            raise validation(f"unknown provider {provider!r}")
        api_key = (api_key or "").strip()
        if len(api_key) < 8:
            raise validation("api_key too short")
        sealed = seal(api_key, aad=_aad(workspace_id, provider))
        row = (await db.execute(select(ProviderSecret).where(ProviderSecret.workspace_id == workspace_id,
                                                             ProviderSecret.provider == provider))).scalar_one_or_none()
        if row is None:
            row = ProviderSecret(workspace_id=workspace_id, provider=provider, ciphertext=sealed.ciphertext, nonce=sealed.nonce,
                                 key_version=sealed.key_version, last4=api_key[-4:], status="active", created_by=user_id)
            db.add(row)
        else:
            row.ciphertext, row.nonce, row.key_version = sealed.ciphertext, sealed.nonce, sealed.key_version
            row.last4 = api_key[-4:]
            row.status = "active"
            row.last_verified_at = None
        await db.flush()
        from app.integrations.ai.registry import clear_provider_cache
        clear_provider_cache()
        await self._audit(db, member, "ai_settings.set_provider_key", "provider_secret", provider, None, {"last4": row.last4})
        return {"provider": provider, "configured": True, "last4": row.last4, "source": "workspace"}

    async def delete_provider_key(self, db: AsyncSession, workspace_id: UUID, provider: str, *, member: Any = None) -> None:
        row = (await db.execute(select(ProviderSecret).where(ProviderSecret.workspace_id == workspace_id,
                                                             ProviderSecret.provider == provider.lower()))).scalar_one_or_none()
        if row is None:
            raise not_found("Provider key")
        await db.delete(row)
        await db.flush()
        await self._audit(db, member, "ai_settings.delete_provider_key", "provider_secret", provider, None, None)

    async def get_provider_key(self, db: AsyncSession, workspace_id: UUID, provider: str) -> str | None:
        """Decrypted workspace key, else the environment key (settings.*_api_key), else None."""
        provider = provider.lower()
        row = (await db.execute(select(ProviderSecret).where(ProviderSecret.workspace_id == workspace_id,
                                                             ProviderSecret.provider == provider,
                                                             ProviderSecret.status == "active"))).scalar_one_or_none()
        if row is not None:
            try:
                return unseal(row.ciphertext, row.nonce, row.key_version, aad=_aad(workspace_id, provider))
            except Exception as e:  # noqa: BLE001
                log.error("provider_key.unseal_failed", provider=provider, error=str(e)[:200])
        return env_api_key(provider) if provider != "ollama" else "ollama"

    async def list_providers(self, db: AsyncSession, workspace_id: UUID) -> list[dict[str, Any]]:
        rows = (await db.execute(select(ProviderSecret).where(ProviderSecret.workspace_id == workspace_id))).scalars().all()
        by_provider = {r.provider: r for r in rows}
        out: list[dict[str, Any]] = []
        for p in PROVIDERS_WITH_KEYS + ("ollama",):
            r = by_provider.get(p)
            env = env_api_key(p)
            if p == "ollama":
                out.append({"provider": p, "configured": True, "source": "local", "last4": None, "verified_at": None,
                            "base_url": settings.ollama_base_url})
                continue
            if r is not None:
                out.append({"provider": p, "configured": True, "source": "workspace", "last4": r.last4,
                            "verified_at": r.last_verified_at.isoformat() if r.last_verified_at else None, "status": r.status})
            else:
                out.append({"provider": p, "configured": bool(env), "source": "env" if env else None,
                            "last4": env[-4:] if env else None, "verified_at": None, "status": "active" if env else "missing"})
        return out

    async def test_provider(self, db: AsyncSession, workspace_id: UUID, provider: str, model: str | None = None) -> dict[str, Any]:
        """One tiny completion to verify the key/model. Marks the secret verified on success."""
        from app.core.ports.ai_provider import Message
        provider = provider.lower()
        key = await self.get_provider_key(db, workspace_id, provider)
        if not key and provider != "ollama":
            return {"ok": False, "provider": provider, "error": "no API key configured"}
        routing = (await self.get(db, workspace_id))["routing"]
        if not model:
            for tier in ("cheap", "balanced", "powerful"):
                p, m = resolve_model(routing[tier]["primary"])
                if p == provider:
                    model = m
                    break
        model = model or {"anthropic": "claude-haiku-4-5", "openai": "gpt-5-mini", "xai": "grok-3-mini",
                          "google": "gemini-2.5-flash", "ollama": "llama3.1", "openrouter": "openai/gpt-5-mini"}.get(provider, "")
        t0 = time.perf_counter()
        try:
            prov = get_provider(provider, key)
            comp = await prov.complete([Message(role="user", content="Reply with the single word OK.")], model=model,
                                       temperature=0.0, max_tokens=16)
            ok = True
            err = None
            sample = comp.content[:40]
        except Exception as e:  # noqa: BLE001
            ok, err, sample = False, f"{type(e).__name__}: {str(e)[:300]}", None
        ms = int((time.perf_counter() - t0) * 1000)
        if ok:
            row = (await db.execute(select(ProviderSecret).where(ProviderSecret.workspace_id == workspace_id,
                                                                 ProviderSecret.provider == provider))).scalar_one_or_none()
            if row is not None:
                row.last_verified_at = datetime.now(UTC)
                await db.flush()
        return {"ok": ok, "provider": provider, "model": model, "latency_ms": ms, "error": err, "sample": sample}

    # -- prompt templates -------------------------------------------------------------------------------------------
    async def ensure_global_defaults(self, db: AsyncSession) -> int:
        """Load app/agents/prompts/*.md as global (workspace NULL) version-1 active templates when none exist."""
        try:
            from app.agents.registry import seed_agents
            await seed_agents(db)
        except Exception as e:  # noqa: BLE001
            log.warning("prompts.seed_agents_failed", error=str(e)[:200])
        existing = set((await db.execute(select(PromptTemplate.agent_id).where(PromptTemplate.workspace_id.is_(None)))).scalars().all())
        n = 0
        for agent_id in list_prompt_files():
            if agent_id in existing:
                continue
            body = load_prompt_file(agent_id) or ""
            db.add(PromptTemplate(workspace_id=None, agent_id=agent_id, action=None, version=1, body=body,
                                  variables=_variables_of(body), is_active=True))
            n += 1
        if n:
            await db.flush()
        return n

    async def get_prompt(self, db: AsyncSession, workspace_id: UUID | None, agent_id: str, action: str | None = None) -> dict[str, Any]:
        """Active workspace template → active global template → file default."""
        for ws in ([workspace_id] if workspace_id else []) + [None]:
            q = select(PromptTemplate).where(PromptTemplate.agent_id == agent_id, PromptTemplate.is_active.is_(True),
                                             PromptTemplate.workspace_id == ws if ws else PromptTemplate.workspace_id.is_(None))
            q = q.where(PromptTemplate.action == action if action else PromptTemplate.action.is_(None))
            try:
                row = (await db.execute(q.order_by(PromptTemplate.version.desc()).limit(1))).scalars().first()
            except Exception as e:  # noqa: BLE001
                log.warning("prompts.query_failed", error=str(e)[:200])
                row = None
            if row is not None:
                return {"agent_id": agent_id, "action": action, "version": row.version, "body": row.body,
                        "source": "workspace" if ws else "global", "template_id": str(row.id), "variables": row.variables}
        body = load_prompt_file(agent_id)
        if body is None:
            raise not_found(f"Prompt for agent {agent_id}")
        return {"agent_id": agent_id, "action": action, "version": 0, "body": body, "source": "file", "template_id": None,
                "variables": _variables_of(body)}

    async def set_prompt(self, db: AsyncSession, workspace_id: UUID, agent_id: str, body: str, *, user_id: UUID | None = None,
                         action: str | None = None, model_hints: dict[str, Any] | None = None, member: Any = None) -> dict[str, Any]:
        if not body or len(body.strip()) < 20:
            raise validation("prompt body too short")
        try:
            from jinja2.sandbox import SandboxedEnvironment
            SandboxedEnvironment().parse(body)
        except Exception as e:  # noqa: BLE001
            raise validation(f"prompt template is not valid Jinja2: {e}") from e
        base_q = select(PromptTemplate).where(PromptTemplate.workspace_id == workspace_id, PromptTemplate.agent_id == agent_id,
                                              PromptTemplate.action == action if action else PromptTemplate.action.is_(None))
        rows = (await db.execute(base_q)).scalars().all()
        version = max((r.version for r in rows), default=0) + 1
        for r in rows:
            r.is_active = False
        row = PromptTemplate(workspace_id=workspace_id, agent_id=agent_id, action=action, version=version, body=body,
                             variables=_variables_of(body), model_hints=model_hints or {}, is_active=True, created_by=user_id)
        db.add(row)
        await db.flush()
        await self._audit(db, member, "ai_prompt.update", "prompt_template", f"{agent_id}:{version}", None, {"version": version})
        return {"agent_id": agent_id, "action": action, "version": version, "body": body, "source": "workspace",
                "template_id": str(row.id), "variables": row.variables}

    async def activate_prompt_version(self, db: AsyncSession, workspace_id: UUID, agent_id: str, version: int,
                                      action: str | None = None) -> dict[str, Any]:
        rows = (await db.execute(select(PromptTemplate).where(PromptTemplate.workspace_id == workspace_id,
                                                              PromptTemplate.agent_id == agent_id))).scalars().all()
        target = next((r for r in rows if r.version == version and (r.action or None) == action), None)
        if target is None:
            raise not_found("Prompt version")
        for r in rows:
            if (r.action or None) == action:
                r.is_active = r.id == target.id
        await db.flush()
        return await self.get_prompt(db, workspace_id, agent_id, action)

    async def list_prompt_versions(self, db: AsyncSession, workspace_id: UUID, agent_id: str) -> list[dict[str, Any]]:
        rows = (await db.execute(select(PromptTemplate).where(PromptTemplate.agent_id == agent_id,
                                                              (PromptTemplate.workspace_id == workspace_id) | PromptTemplate.workspace_id.is_(None))
                                 .order_by(PromptTemplate.workspace_id.desc().nulls_last(), PromptTemplate.version.desc()))).scalars().all()
        return [{"template_id": str(r.id), "version": r.version, "action": r.action, "is_active": r.is_active,
                 "scope": "workspace" if r.workspace_id else "global", "created_at": r.created_at.isoformat() if r.created_at else None,
                 "created_by": str(r.created_by) if r.created_by else None, "chars": len(r.body)} for r in rows]

    # -- usage ------------------------------------------------------------------------------------------------------
    async def usage_summary(self, db: AsyncSession, workspace_id: UUID, from_: datetime | None = None, to: datetime | None = None,
                            group_by: str = "day") -> dict[str, Any]:
        to = to or datetime.now(UTC)
        from_ = from_ or (to - timedelta(days=30))
        base = [AICall.workspace_id == workspace_id, AICall.created_at >= from_, AICall.created_at < to]
        totals = (await db.execute(select(func.count(AICall.id), func.coalesce(func.sum(AICall.cost_usd), 0),
                                          func.coalesce(func.sum(AICall.tokens_in), 0), func.coalesce(func.sum(AICall.tokens_out), 0),
                                          func.coalesce(func.sum(AICall.cached_tokens), 0)).where(*base))).one()
        key_col = {"agent": AICall.agent_id, "model": AICall.model, "provider": AICall.provider,
                   "day": func.date_trunc("day", AICall.created_at)}.get(group_by, func.date_trunc("day", AICall.created_at))
        grouped = (await db.execute(select(key_col, func.count(AICall.id), func.coalesce(func.sum(AICall.cost_usd), 0),
                                           func.coalesce(func.sum(AICall.tokens_in), 0), func.coalesce(func.sum(AICall.tokens_out), 0))
                                    .where(*base).group_by(key_col).order_by(key_col))).all()
        series = [{"key": (k.isoformat() if isinstance(k, datetime) else (k or "unknown")), "calls": int(c), "cost_usd": float(cost),
                   "tokens_in": int(ti), "tokens_out": int(to_)} for k, c, cost, ti, to_ in grouped]
        ledger = (await db.execute(select(UsageLedger.kind, func.coalesce(func.sum(UsageLedger.cost_usd), 0),
                                          func.coalesce(func.sum(UsageLedger.quantity), 0))
                                   .where(UsageLedger.workspace_id == workspace_id, UsageLedger.occurred_at >= from_,
                                          UsageLedger.occurred_at < to).group_by(UsageLedger.kind))).all()
        budgets = (await db.execute(select(UsageBudget).where(UsageBudget.workspace_id == workspace_id))).scalars().all()
        from app.services.budget_guard import BudgetGuard
        guard = BudgetGuard()
        budget_rows = []
        for b in budgets:
            spent = await guard.spent_in_period(db, workspace_id, b.kind, b.period)
            budget_rows.append({"kind": b.kind, "period": b.period, "limit": float(b.limit_value), "spent": spent, "hard": b.hard,
                                "ratio": (spent / float(b.limit_value)) if float(b.limit_value) else 0.0})
        return {"from": from_.isoformat(), "to": to.isoformat(), "group_by": group_by,
                "totals": {"calls": int(totals[0]), "cost_usd": float(totals[1]), "tokens_in": int(totals[2]),
                           "tokens_out": int(totals[3]), "cached_tokens": int(totals[4])},
                "series": series,
                "by_kind": [{"kind": k, "cost_usd": float(c), "quantity": float(q)} for k, c, q in ledger],
                "budgets": budget_rows}

    # -- helpers ----------------------------------------------------------------------------------------------------
    @staticmethod
    async def _audit(db: AsyncSession, member: Any, action: str, target_type: str, target_id: str, before: Any, after: Any) -> None:
        if member is None:
            return
        try:
            from app.services.audit_service import audit
        except ImportError:
            return
        try:
            await audit(db, member, action, target_type, target_id, before=before, after=after)
        except Exception as e:  # noqa: BLE001
            log.warning("audit.failed", action=action, error=str(e)[:200])


def _variables_of(body: str) -> list[str]:
    try:
        from jinja2 import meta
        from jinja2.sandbox import SandboxedEnvironment
        env = SandboxedEnvironment()
        return sorted(meta.find_undeclared_variables(env.parse(body)))
    except Exception:  # noqa: BLE001
        return []


__all__ = ["AISettingsService", "default_settings", "load_prompt_file", "list_prompt_files", "ProblemError"]

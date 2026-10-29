"""Provider registry & model routing.

- resolve_model("anthropic/claude-sonnet-5-5") -> ("anthropic", "claude-sonnet-5-5")
- get_provider(provider_name, api_key=None) -> AIProvider (cached; constructed lazily, no network)
- get_routing(db, workspace_id) -> routing table (settings defaults merged with ai_settings.routing)
- provider_for_tier(db, workspace_id, tier, agent_id=None) -> (provider, model)   (first viable candidate)
- providers_for_tier(...) -> [(provider, model), ...]                              (primary + fallbacks)

Candidates whose provider has no API key (workspace secret or environment) are skipped instead of being handed to an
SDK that would fail at request time. When nothing routed is usable, the first provider that *does* have a key is used
with a sensible default model for the tier, then the key-less free fallbacks (FREE_FALLBACK_MODELS, local Ollama).
Only when all of that is empty does `NoProviderConfigured` explain exactly how to configure AI.
"""
from __future__ import annotations

import copy
import hashlib
from typing import Any
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.core.logging import get_logger
from app.core.ports.ai_provider import AIProvider
from app.integrations.ai.base import KEYLESS_PROVIDERS, configuration_hint

log = get_logger("ai.registry")

TIERS = ("cheap", "balanced", "powerful")
PROVIDER_BASE_URLS: dict[str, str | None] = {
    "openai": None,
    "xai": "https://api.x.ai/v1",
    "openrouter": "https://openrouter.ai/api/v1",
    "google": "https://generativelanguage.googleapis.com/v1beta/openai/",
    "groq": "https://api.groq.com/openai/v1",
    "huggingface": "https://router.huggingface.co/v1",
    "pollinations": "https://text.pollinations.ai/openai",
    "ollama": settings.ollama_base_url,
}
KNOWN_PROVIDERS = ("anthropic", "openai", "google", "xai", "groq", "openrouter", "huggingface", "pollinations", "ollama", "fake")
#: Order in which a provider that has a key is auto-selected when the routed provider has none.
AUTO_PROVIDER_ORDER = ("anthropic", "openai", "google", "groq", "xai", "openrouter", "huggingface")
#: Default model per provider and tier (editable per workspace in Settings → AI → routing).
DEFAULT_MODELS: dict[str, dict[str, str]] = {
    "anthropic": {"cheap": "claude-haiku-4-5-20251001", "balanced": "claude-sonnet-5-5", "powerful": "claude-opus-5-5"},
    "openai": {"cheap": "gpt-5-mini", "balanced": "gpt-5-mini", "powerful": "gpt-5"},
    "google": {"cheap": "gemini-2.5-flash-lite", "balanced": "gemini-2.5-flash", "powerful": "gemini-2.5-pro"},
    "groq": {"cheap": "llama-3.1-8b-instant", "balanced": "llama-3.3-70b-versatile", "powerful": "llama-3.3-70b-versatile"},
    "xai": {"cheap": "grok-3-mini", "balanced": "grok-3-mini", "powerful": "grok-4"},
    "openrouter": {"cheap": "openai/gpt-5-mini", "balanced": "openai/gpt-5-mini", "powerful": "anthropic/claude-sonnet-5-5"},
    "huggingface": {"cheap": "meta-llama/Llama-3.1-8B-Instruct", "balanced": "Qwen/Qwen2.5-72B-Instruct",
                    "powerful": "Qwen/Qwen2.5-72B-Instruct"},
    "pollinations": {"cheap": "openai", "balanced": "openai", "powerful": "openai-large"},
    "ollama": {"cheap": "llama3.1", "balanced": "llama3.1", "powerful": "llama3.1"},
}

_cache: dict[str, AIProvider] = {}
_overrides: dict[str, AIProvider] = {}


class NoProviderConfigured(ValueError):
    """No routed, keyed or free provider is available; the message says how to fix it."""


# ----------------------------------------------------------------------------- model specs

def resolve_model(spec: str) -> tuple[str, str]:
    """'provider/model' → (provider, model). Without a slash the provider is inferred from the model name."""
    if not spec or not isinstance(spec, str):
        raise ValueError("empty model spec")
    s = spec.strip()
    if "/" in s:
        provider, model = s.split("/", 1)
        provider = provider.strip().lower()
        model = model.strip()
        if provider == "local":
            provider = "ollama"
        if not model:
            raise ValueError(f"model missing in spec {spec!r}")
        return provider, model
    m = s.lower()
    if m.startswith("claude"):
        return "anthropic", s
    if m.startswith(("gpt", "o1", "o3", "o4", "text-embedding", "chatgpt")):
        return "openai", s
    if m.startswith("grok"):
        return "xai", s
    if m.startswith("gemini"):
        return "google", s
    if m.startswith("fake"):
        return "fake", s
    return "ollama", s


def model_spec(provider: str, model: str) -> str:
    return f"{provider}/{model}"


# ----------------------------------------------------------------------------- providers

def env_api_key(provider: str) -> str | None:
    return {"anthropic": settings.anthropic_api_key, "openai": settings.openai_api_key, "xai": settings.xai_api_key,
            "google": settings.google_api_key, "groq": settings.groq_api_key, "openrouter": settings.openrouter_api_key,
            "huggingface": settings.huggingface_api_key, "pollinations": settings.pollinations_api_key,
            "ollama": "ollama"}.get(provider) or None


def needs_key(provider: str) -> bool:
    return provider not in KEYLESS_PROVIDERS


def free_fallback_specs() -> list[str]:
    """Model specs from FREE_FALLBACK_MODELS (comma-separated); empty disables the key-less fallback."""
    return [s.strip() for s in (settings.free_fallback_models or "").split(",") if s.strip()]


def register_provider(name: str, provider: AIProvider | None) -> None:
    """Test hook: force `get_provider(name)` to return `provider` (None clears)."""
    if provider is None:
        _overrides.pop(name, None)
    else:
        _overrides[name] = provider


def clear_provider_cache() -> None:
    _cache.clear()


def get_provider(provider_name: str, api_key: str | None = None, base_url: str | None = None) -> AIProvider:
    """Construct (lazily, no network) and cache a provider for `provider_name`. Keys fall back to settings.*_api_key."""
    name = (provider_name or "").lower()
    if name in _overrides:
        return _overrides[name]
    key = api_key or env_api_key(name)
    cache_key = f"{name}:{hashlib.sha256((key or '').encode()).hexdigest()[:12]}:{base_url or ''}"
    if cache_key in _cache:
        return _cache[cache_key]
    if name == "anthropic":
        from app.integrations.ai.anthropic import AnthropicProvider
        p: AIProvider = AnthropicProvider(api_key=key, base_url=base_url)
    elif name == "fake":
        from app.integrations.ai.fake import FakeProvider
        p = FakeProvider()
    elif name in PROVIDER_BASE_URLS or name == "local":
        from app.integrations.ai.openai_compatible import OpenAICompatibleProvider
        if name == "local":
            name = "ollama"
        url = base_url or PROVIDER_BASE_URLS.get(name)
        headers = {"HTTP-Referer": settings.public_base_url, "X-Title": "Botwok"} if name == "openrouter" else None
        p = OpenAICompatibleProvider(name, base_url=url, api_key=key, extra_headers=headers)
    else:
        raise ValueError(f"unknown AI provider {provider_name!r}")
    _cache[cache_key] = p
    return p


# ----------------------------------------------------------------------------- routing

def _tier_default(tier: str, fallback_spec: str) -> str:
    """AI_PROVIDER=<name> routes the tier to that provider's default model; otherwise the DEFAULT_*_MODEL spec."""
    p = (settings.ai_provider or "").strip().lower()
    if p == "local":
        p = "ollama"
    model = DEFAULT_MODELS.get(p, {}).get(tier) if p else None
    return f"{p}/{model}" if model else fallback_spec


def default_routing() -> dict[str, Any]:
    return {
        "cheap": {"primary": _tier_default("cheap", settings.default_cheap_model), "fallback": []},
        "balanced": {"primary": _tier_default("balanced", settings.default_balanced_model), "fallback": []},
        "powerful": {"primary": _tier_default("powerful", settings.default_powerful_model), "fallback": []},
        "embeddings": {"primary": settings.default_embedding_model, "fallback": []},
        "per_agent": {},
        "economy_mode": False,
        "critic_distinct_family": True,
    }


def _norm_tier(value: Any) -> dict[str, Any]:
    if isinstance(value, str):
        return {"primary": value, "fallback": []}
    if isinstance(value, dict):
        out = dict(value)
        fb = out.get("fallback") or out.get("fallbacks") or []
        if isinstance(fb, str):
            fb = [fb]
        out["fallback"] = [f for f in fb if isinstance(f, str) and f]
        return out
    return {}


def merge_routing(base: dict[str, Any], override: dict[str, Any] | None) -> dict[str, Any]:
    out = copy.deepcopy(base)
    for k, v in (override or {}).items():
        if k in ("cheap", "balanced", "powerful", "embeddings"):
            tier = _norm_tier(v)
            merged = dict(out.get(k, {}))
            if tier.get("primary"):
                merged["primary"] = tier["primary"]
            if "fallback" in tier:
                merged["fallback"] = tier["fallback"]
            out[k] = merged
        elif k == "per_agent" and isinstance(v, dict):
            out["per_agent"] = {**out.get("per_agent", {}), **{a: _norm_tier(x) for a, x in v.items()}}
        else:
            out[k] = v
    return out


async def get_routing(db: AsyncSession | None, workspace_id: UUID | str | None) -> dict[str, Any]:
    routing = default_routing()
    if db is None or workspace_id is None:
        return routing
    try:
        from sqlalchemy import select

        from app.models.ai import AISettings
        row = (await db.execute(select(AISettings).where(AISettings.workspace_id == UUID(str(workspace_id))))).scalar_one_or_none()
    except Exception as e:  # noqa: BLE001 - settings are optional; defaults always work
        log.warning("routing.settings_unavailable", error=str(e)[:200])
        row = None
    if row is not None and row.routing:
        routing = merge_routing(routing, row.routing)
    return routing


def _lower_tier(tier: str) -> str:
    return {"powerful": "balanced", "balanced": "cheap", "cheap": "cheap"}.get(tier, tier)


def candidate_specs(routing: dict[str, Any], tier: str, agent_id: str | None = None) -> list[str]:
    """Ordered model specs for a tier honoring per-agent overrides, economy mode, and fallback lists."""
    specs: list[str] = []
    per_agent = routing.get("per_agent") or {}
    if agent_id and agent_id in per_agent:
        o = _norm_tier(per_agent[agent_id])
        if o.get("primary"):
            specs.append(o["primary"])
        specs.extend(o.get("fallback", []))
    if routing.get("economy_mode"):
        tier = _lower_tier(tier)
    t = _norm_tier(routing.get(tier) or {})
    if t.get("primary"):
        specs.append(t["primary"])
    specs.extend(t.get("fallback", []))
    seen: set[str] = set()
    out: list[str] = []
    for s in specs:
        if s not in seen:
            seen.add(s)
            out.append(s)
    return out


async def _key_for(db: AsyncSession | None, workspace_id: UUID | str | None, provider: str) -> str | None:
    if db is not None and workspace_id is not None:
        try:
            from app.services.ai_settings_service import AISettingsService
            return await AISettingsService().get_provider_key(db, UUID(str(workspace_id)), provider)
        except Exception as e:  # noqa: BLE001
            log.warning("routing.key_lookup_failed", provider=provider, error=str(e)[:200])
    return env_api_key(provider)


async def _usable(db: AsyncSession | None, workspace_id: UUID | str | None, provider_name: str) -> tuple[bool, str | None]:
    """(usable, key): overrides and key-less providers are always usable; others need a workspace or env key."""
    if provider_name in _overrides:
        return True, None
    key = await _key_for(db, workspace_id, provider_name)
    if needs_key(provider_name) and not key:
        return False, None
    return True, key


async def providers_for_tier(db: AsyncSession | None, workspace_id: UUID | str | None, tier: str,
                             agent_id: str | None = None, *, routing: dict[str, Any] | None = None
                             ) -> list[tuple[AIProvider, str]]:
    routing = routing or await get_routing(db, workspace_id)
    out: list[tuple[AIProvider, str]] = []
    unconfigured: list[str] = []
    for spec in candidate_specs(routing, tier, agent_id):
        try:
            provider_name, model = resolve_model(spec)
            usable, key = await _usable(db, workspace_id, provider_name)
            if not usable:
                unconfigured.append(spec)
                continue
            out.append((get_provider(provider_name, key), model))
        except Exception as e:  # noqa: BLE001
            log.warning("routing.candidate_skipped", spec=spec, error=str(e)[:200])
    if out:
        return out

    # Nothing routed is usable: prefer any provider the operator did give a key, then the free key-less fallbacks.
    eff_tier = _lower_tier(tier) if routing.get("economy_mode") else tier
    for name in AUTO_PROVIDER_ORDER:
        model = DEFAULT_MODELS.get(name, {}).get(eff_tier)
        usable, key = await _usable(db, workspace_id, name)
        if model and usable and (key or name in _overrides):
            out.append((get_provider(name, key), model))
            break
    for spec in free_fallback_specs():
        try:
            provider_name, model = resolve_model(spec)
            usable, key = await _usable(db, workspace_id, provider_name)
            if usable:
                out.append((get_provider(provider_name, key), model))
        except Exception as e:  # noqa: BLE001
            log.warning("routing.free_fallback_skipped", spec=spec, error=str(e)[:200])
    if out:
        log.warning("routing.fallback_in_use", tier=tier, unconfigured=unconfigured,
                    using=[f"{p.name}/{m}" for p, m in out])
        return out
    routed = ", ".join(unconfigured) or "nothing"
    raise NoProviderConfigured(f"No AI provider is configured for the {tier!r} tier (routed to {routed}, no API key found). "
                               f"{configuration_hint()}")


async def provider_for_tier(db: AsyncSession | None, workspace_id: UUID | str | None, tier: str,
                            agent_id: str | None = None) -> tuple[AIProvider, str]:
    return (await providers_for_tier(db, workspace_id, tier, agent_id))[0]


async def ai_available(db: AsyncSession | None, workspace_id: UUID | str | None, tier: str = "powerful",
                       agent_id: str | None = None) -> bool:
    """True when some provider (routed, keyed, or free fallback) can serve `tier`. No network calls."""
    try:
        await providers_for_tier(db, workspace_id, tier, agent_id)
        return True
    except NoProviderConfigured:
        return False
    except Exception as e:  # noqa: BLE001
        log.info("ai_available.failed", error=str(e)[:200])
        return False


def model_family(spec_or_model: str) -> str:
    """Rough family label used by the critic-vs-writer distinct-model rule."""
    m = spec_or_model.lower().rsplit("/", 1)[-1]
    for fam in ("claude", "gpt", "grok", "gemini", "llama", "qwen", "mistral", "deepseek"):
        if fam in m:
            return fam
    return m.split("-")[0]

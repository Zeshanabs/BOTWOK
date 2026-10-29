import pytest

from app.config import settings
from app.integrations.ai import registry as reg
from app.integrations.ai.fake import FakeProvider


def test_resolve_model_with_provider_prefix():
    assert reg.resolve_model("anthropic/claude-sonnet-5-5") == ("anthropic", "claude-sonnet-5-5")
    assert reg.resolve_model("openrouter/openai/gpt-5-mini") == ("openrouter", "openai/gpt-5-mini")
    assert reg.resolve_model("local/llama3.1") == ("ollama", "llama3.1")


def test_resolve_model_infers_provider():
    assert reg.resolve_model("claude-haiku-4-5") == ("anthropic", "claude-haiku-4-5")
    assert reg.resolve_model("gpt-5") == ("openai", "gpt-5")
    assert reg.resolve_model("grok-4") == ("xai", "grok-4")
    assert reg.resolve_model("gemini-2.5-flash") == ("google", "gemini-2.5-flash")
    assert reg.resolve_model("qwen2.5:7b") == ("ollama", "qwen2.5:7b")


def test_resolve_model_rejects_empty():
    with pytest.raises(ValueError):
        reg.resolve_model("")
    with pytest.raises(ValueError):
        reg.resolve_model("anthropic/")


def test_default_routing_uses_settings():
    r = reg.default_routing()
    assert r["cheap"]["primary"] == settings.default_cheap_model
    assert r["balanced"]["primary"] == settings.default_balanced_model
    assert r["powerful"]["primary"] == settings.default_powerful_model
    assert r["embeddings"]["primary"] == settings.default_embedding_model


def test_merge_routing_overrides_and_fallbacks():
    merged = reg.merge_routing(reg.default_routing(), {
        "balanced": "openai/gpt-5-mini",
        "powerful": {"primary": "xai/grok-4", "fallback": ["anthropic/claude-opus-5-5"]},
        "per_agent": {"critic": "openai/gpt-5"},
        "economy_mode": True,
    })
    assert merged["balanced"] == {"primary": "openai/gpt-5-mini", "fallback": []}
    assert merged["powerful"]["primary"] == "xai/grok-4"
    assert merged["powerful"]["fallback"] == ["anthropic/claude-opus-5-5"]
    assert merged["cheap"]["primary"] == settings.default_cheap_model    # untouched
    assert merged["per_agent"]["critic"]["primary"] == "openai/gpt-5"
    assert merged["economy_mode"] is True


def test_candidate_specs_honors_per_agent_and_economy():
    routing = reg.merge_routing(reg.default_routing(), {
        "powerful": {"primary": "anthropic/claude-opus-5-5", "fallback": ["openai/gpt-5"]},
        "balanced": {"primary": "anthropic/claude-sonnet-5-5"},
        "per_agent": {"writer": {"primary": "xai/grok-4", "fallback": ["anthropic/claude-opus-5-5"]}},
    })
    assert reg.candidate_specs(routing, "powerful") == ["anthropic/claude-opus-5-5", "openai/gpt-5"]
    # per-agent override first, then tier primary + fallbacks, de-duplicated
    assert reg.candidate_specs(routing, "powerful", "writer") == ["xai/grok-4", "anthropic/claude-opus-5-5", "openai/gpt-5"]
    routing["economy_mode"] = True
    assert reg.candidate_specs(routing, "powerful")[0] == "anthropic/claude-sonnet-5-5"   # dropped one tier


async def test_get_routing_without_db_returns_defaults():
    r = await reg.get_routing(None, None)
    assert r["cheap"]["primary"] == settings.default_cheap_model


def test_get_provider_caches_and_overrides():
    reg.clear_provider_cache()
    a = reg.get_provider("xai", "k1")
    b = reg.get_provider("xai", "k1")
    c = reg.get_provider("xai", "k2")
    assert a is b and a is not c
    assert a.name == "xai"
    fake = FakeProvider(name="fake")
    reg.register_provider("anthropic", fake)
    try:
        assert reg.get_provider("anthropic") is fake
    finally:
        reg.register_provider("anthropic", None)
    with pytest.raises(ValueError):
        reg.get_provider("nope")


async def test_providers_for_tier_without_db(monkeypatch):
    fake = FakeProvider(name="fake")
    reg.register_provider("anthropic", fake)
    try:
        cands = await reg.providers_for_tier(None, None, "balanced", "research")
        assert cands and cands[0][0] is fake
    finally:
        reg.register_provider("anthropic", None)


def test_model_family():
    assert reg.model_family("anthropic/claude-sonnet-5-5") == "claude"
    assert reg.model_family("gpt-5") == "gpt"
    assert reg.model_family("xai/grok-4") == "grok"


# ----------------------------------------------------------------------------- key handling & free fallbacks

ALL_KEYS = ("anthropic_api_key", "openai_api_key", "xai_api_key", "google_api_key", "groq_api_key", "openrouter_api_key",
            "huggingface_api_key", "pollinations_api_key")


def _no_keys(monkeypatch, **keep: str) -> None:
    for k in ALL_KEYS:
        monkeypatch.setattr(settings, k, keep.get(k, ""))
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    reg.clear_provider_cache()


async def test_unkeyed_candidates_fall_back_to_free_endpoint(monkeypatch):
    _no_keys(monkeypatch)
    monkeypatch.setattr(settings, "free_fallback_models", "pollinations/openai")
    cands = await reg.providers_for_tier(None, None, "cheap", "ideation")      # routed to anthropic, which has no key
    assert [(p.name, m) for p, m in cands] == [("pollinations", "openai")]


async def test_any_configured_key_is_preferred_over_free_fallback(monkeypatch):
    _no_keys(monkeypatch, google_api_key="g-test-key")
    monkeypatch.setattr(settings, "free_fallback_models", "pollinations/openai")
    cands = await reg.providers_for_tier(None, None, "cheap", "ideation")
    assert [(p.name, m) for p, m in cands] == [("google", reg.DEFAULT_MODELS["google"]["cheap"]), ("pollinations", "openai")]


async def test_routed_provider_with_key_is_used_as_is(monkeypatch):
    _no_keys(monkeypatch, anthropic_api_key="sk-ant-test")
    cands = await reg.providers_for_tier(None, None, "balanced")
    assert cands[0][0].name == "anthropic" and cands[0][1] == reg.resolve_model(settings.default_balanced_model)[1]


async def test_nothing_configured_raises_actionable_error(monkeypatch):
    _no_keys(monkeypatch)
    monkeypatch.setattr(settings, "free_fallback_models", "")
    with pytest.raises(reg.NoProviderConfigured) as ei:
        await reg.providers_for_tier(None, None, "cheap", "ideation")
    msg = str(ei.value)
    assert "No AI provider is configured" in msg and "Settings → AI" in msg and "FREE_FALLBACK_MODELS" in msg
    assert await reg.ai_available(None, None, "cheap", "ideation") is False
    monkeypatch.setattr(settings, "free_fallback_models", "pollinations/openai")
    assert await reg.ai_available(None, None, "cheap", "ideation") is True


async def test_adapters_fail_fast_without_a_key(monkeypatch):
    from app.core.ports.ai_provider import Message
    from app.integrations.ai.anthropic import AnthropicProvider
    from app.integrations.ai.base import ProviderError
    from app.integrations.ai.openai_compatible import OpenAICompatibleProvider
    _no_keys(monkeypatch)
    msgs = [Message(role="user", content="hi")]
    with pytest.raises(ProviderError) as ei:
        await AnthropicProvider(api_key=None).complete(msgs, model="claude-haiku-4-5")
    assert ei.value.kind == "auth" and "No API key configured for Anthropic" in str(ei.value)
    with pytest.raises(ProviderError) as ei2:
        await OpenAICompatibleProvider("groq", base_url=reg.PROVIDER_BASE_URLS["groq"], api_key=None).complete(msgs, model="llama-3.1-8b-instant")
    assert ei2.value.kind == "auth" and "Groq" in str(ei2.value)


def test_keyless_provider_sends_no_bearer_token():
    from app.integrations.ai.openai_compatible import OpenAICompatibleProvider
    p = OpenAICompatibleProvider("pollinations", base_url=reg.PROVIDER_BASE_URLS["pollinations"], api_key=None)
    client = p._get_client()
    assert client.base_url.host == "text.pollinations.ai"
    assert client._client.event_hooks["request"], "authorization-stripping hook must be installed"


def test_ai_provider_switch_routes_every_tier(monkeypatch):
    monkeypatch.setattr(settings, "ai_provider", "groq")
    r = reg.default_routing()
    assert r["cheap"]["primary"] == "groq/" + reg.DEFAULT_MODELS["groq"]["cheap"]
    assert r["powerful"]["primary"] == "groq/" + reg.DEFAULT_MODELS["groq"]["powerful"]
    assert r["embeddings"]["primary"] == settings.default_embedding_model      # embeddings untouched
    monkeypatch.setattr(settings, "ai_provider", "nope")
    assert reg.default_routing()["cheap"]["primary"] == settings.default_cheap_model   # unknown name → unchanged


async def test_groq_key_alone_runs_everything_on_groq(monkeypatch):
    _no_keys(monkeypatch, groq_api_key="gsk-test")
    monkeypatch.setattr(settings, "ai_provider", "groq")
    for tier in ("cheap", "balanced", "powerful"):
        cands = await reg.providers_for_tier(None, None, tier, "research")
        assert cands[0][0].name == "groq" and cands[0][1] == reg.DEFAULT_MODELS["groq"][tier]

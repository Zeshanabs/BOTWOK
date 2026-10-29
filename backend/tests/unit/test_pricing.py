from app.core import pricing
from app.core.ports.ai_provider import Usage


def test_known_model_cost():
    # 1M input tokens of Sonnet 5.5 = $2
    assert pricing.estimate_cost("anthropic", "claude-sonnet-5-5", Usage(tokens_in=1_000_000)) == 2.0
    # output priced separately
    assert pricing.estimate_cost("anthropic", "claude-opus-5-5", {"tokens_in": 0, "tokens_out": 1_000_000}) == 20.0


def test_cached_tokens_discounted():
    full = pricing.estimate_cost("anthropic", "claude-sonnet-5-5", {"tokens_in": 100_000, "tokens_out": 0, "cached_tokens": 0})
    cached = pricing.estimate_cost("anthropic", "claude-sonnet-5-5", {"tokens_in": 100_000, "tokens_out": 0, "cached_tokens": 100_000})
    assert cached < full
    assert abs(cached - 100_000 * 0.20 / 1e6) < 1e-9


def test_date_suffix_and_prefix_matching():
    assert pricing.get_price("anthropic", "claude-haiku-4-5-20251001") == pricing.get_price("anthropic", "claude-haiku-4-5")
    assert pricing.get_price("openai", "gpt-5-mini-2025-08-07") == pricing.get_price("openai", "gpt-5-mini")
    assert pricing.get_price("openai", "gpt-4.1-nano").input_per_m == 0.1


def test_unknown_model_is_zero_with_warning():
    pricing._warned.clear()
    assert pricing.estimate_cost("openai", "totally-unknown-model", {"tokens_in": 1000, "tokens_out": 1000}) == 0.0
    assert "openai/totally-unknown-model" in pricing._warned
    assert pricing.estimate_cost("nonexistent-provider", "x", {"tokens_in": 10}) == 0.0


def test_local_models_are_free():
    assert pricing.estimate_cost("ollama", "llama3.1:8b", {"tokens_in": 1_000_000, "tokens_out": 1_000_000}) == 0.0
    assert pricing.estimate_cost("local", "anything", {"tokens_in": 5}) == 0.0


def test_embeddings_priced():
    assert pricing.estimate_cost("openai", "text-embedding-3-small", {"tokens_in": 1_000_000}) == 0.02


def test_snapshot_has_version():
    snap = pricing.price_table_snapshot()
    assert snap["version"] == pricing.PRICE_TABLE_VERSION
    assert "claude-sonnet-5-5" in snap["models"]["anthropic"]

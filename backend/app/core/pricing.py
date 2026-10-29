"""Versioned price table (doc 20 §20.7). `ai_calls.cost_usd` is computed at call time with the then-current table.

Prices are USD per million tokens. Unknown provider/model pairs cost 0 and log a warning (once per model).
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any

from app.core.logging import get_logger

log = get_logger("pricing")

PRICE_TABLE_VERSION = "2026-10-01"


@dataclass(frozen=True)
class ModelPrice:
    input_per_m: float
    output_per_m: float
    cached_per_m: float = 0.0

    def as_dict(self) -> dict[str, float]:
        return {"input_per_m": self.input_per_m, "output_per_m": self.output_per_m, "cached_per_m": self.cached_per_m}


def _p(i: float, o: float, c: float | None = None) -> ModelPrice:
    return ModelPrice(i, o, c if c is not None else round(i * 0.1, 4))


PRICES: dict[str, dict[str, ModelPrice]] = {
    "anthropic": {
        # current generation
        "claude-fable-5-1": _p(10.0, 50.0, 0.25),
        "claude-fable-5": _p(10.0, 50.0, 1.0),
        "claude-opus-5-5": _p(4.0, 20.0, 0.20),
        "claude-opus-5": _p(5.0, 25.0, 0.50),
        "claude-opus-4-8": _p(5.0, 25.0, 0.50),
        "claude-opus-4-7": _p(5.0, 25.0, 0.50),
        "claude-opus-4-6": _p(5.0, 25.0, 0.50),
        "claude-sonnet-5-5": _p(2.0, 10.0, 0.20),
        "claude-sonnet-5": _p(2.0, 10.0, 0.20),
        "claude-sonnet-4-6": _p(3.0, 15.0, 0.30),
        "claude-haiku-4-5": _p(1.0, 5.0, 0.10),
        # 4.x family (older names still routable)
        "claude-opus-4-5": _p(5.0, 25.0, 0.50),
        "claude-opus-4-1": _p(15.0, 75.0, 1.50),
        "claude-opus-4": _p(15.0, 75.0, 1.50),
        "claude-sonnet-4-5": _p(3.0, 15.0, 0.30),
        "claude-sonnet-4": _p(3.0, 15.0, 0.30),
        "claude-3-7-sonnet": _p(3.0, 15.0, 0.30),
        "claude-3-5-haiku": _p(0.8, 4.0, 0.08),
    },
    "openai": {
        "gpt-5": _p(1.25, 10.0, 0.125),
        "gpt-5-mini": _p(0.25, 2.0, 0.025),
        "gpt-5-nano": _p(0.05, 0.4, 0.005),
        "gpt-5-pro": _p(15.0, 120.0, 15.0),
        "gpt-5-chat": _p(1.25, 10.0, 0.125),
        "gpt-4.1": _p(2.0, 8.0, 0.5),
        "gpt-4.1-mini": _p(0.4, 1.6, 0.1),
        "gpt-4.1-nano": _p(0.1, 0.4, 0.025),
        "gpt-4o": _p(2.5, 10.0, 1.25),
        "gpt-4o-mini": _p(0.15, 0.6, 0.075),
        "o3": _p(2.0, 8.0, 0.5),
        "o4-mini": _p(1.1, 4.4, 0.275),
        "text-embedding-3-small": _p(0.02, 0.0, 0.0),
        "text-embedding-3-large": _p(0.13, 0.0, 0.0),
        "text-embedding-ada-002": _p(0.1, 0.0, 0.0),
    },
    "xai": {
        "grok-4": _p(3.0, 15.0, 0.75),
        "grok-4-fast": _p(0.2, 0.5, 0.05),
        "grok-3": _p(3.0, 15.0, 0.75),
        "grok-3-mini": _p(0.3, 0.5, 0.075),
    },
    "google": {
        "gemini-2.5-pro": _p(1.25, 10.0, 0.31),
        "gemini-2.5-flash": _p(0.3, 2.5, 0.075),
        "gemini-2.5-flash-lite": _p(0.1, 0.4, 0.025),
        "gemini-2.0-flash": _p(0.1, 0.4, 0.025),
        "text-embedding-004": _p(0.0, 0.0, 0.0),
    },
    "openrouter": {},
    "ollama": {"*": _p(0.0, 0.0, 0.0)},
    "local": {"*": _p(0.0, 0.0, 0.0)},
    "fake": {"*": _p(0.0, 0.0, 0.0)},
}

# Non-LLM metered prices (USD per unit). Overridable in AI Settings (media/search sections).
MEDIA_PRICES: dict[str, float] = {
    "openai/gpt-image-1": 0.04,         # per standard image
    "openai/dall-e-3": 0.04,
    "stability/sd3": 0.035,
    "replicate/flux-schnell": 0.003,
    "local/*": 0.0,
}
SEARCH_PRICES: dict[str, float] = {
    "tavily": 0.008,                    # per call (approx; 1000 free/mo)
    "brave": 0.005,
    "exa": 0.01,
    "searxng": 0.0,
}

_DATE_SUFFIX = re.compile(r"-\d{8}$")
_LATEST_SUFFIX = re.compile(r"-(latest|preview)$")
_warned: set[str] = set()
_ZERO = ModelPrice(0.0, 0.0, 0.0)


def _normalize_model(model: str) -> str:
    m = model.strip().lower()
    m = _DATE_SUFFIX.sub("", m)
    m = _LATEST_SUFFIX.sub("", m)
    # vendor prefixes used by openrouter / bedrock style ids
    if "/" in m:
        m = m.rsplit("/", 1)[-1]
    return m


def get_price(provider: str, model: str) -> ModelPrice | None:
    """Exact → date-stripped → longest-prefix match. None when unknown."""
    table = PRICES.get((provider or "").lower())
    if table is None:
        return None
    if "*" in table and len(table) == 1:
        return table["*"]
    if model in table:
        return table[model]
    norm = _normalize_model(model)
    if norm in table:
        return table[norm]
    best: str | None = None
    for key in table:
        if key != "*" and norm.startswith(key) and (best is None or len(key) > len(best)):
            best = key
    if best is not None:
        return table[best]
    return table.get("*")


def _usage_fields(usage: Any) -> tuple[int, int, int]:
    if usage is None:
        return 0, 0, 0
    if isinstance(usage, dict):
        return int(usage.get("tokens_in", 0) or 0), int(usage.get("tokens_out", 0) or 0), int(usage.get("cached_tokens", 0) or 0)
    return int(getattr(usage, "tokens_in", 0) or 0), int(getattr(usage, "tokens_out", 0) or 0), int(getattr(usage, "cached_tokens", 0) or 0)


def estimate_cost(provider: str, model: str, usage: Any) -> float:
    """USD cost of a call. `usage` is a Usage dataclass or dict with tokens_in/tokens_out/cached_tokens.

    `tokens_in` is the total prompt size including cached tokens (adapters normalize it that way).
    """
    tokens_in, tokens_out, cached = _usage_fields(usage)
    price = get_price(provider, model)
    if price is None:
        key = f"{provider}/{model}"
        if key not in _warned:
            _warned.add(key)
            log.warning("pricing.unknown_model", provider=provider, model=model)
        price = _ZERO
    cached = min(cached, tokens_in)
    uncached_in = tokens_in - cached
    cost = (uncached_in * price.input_per_m + cached * price.cached_per_m + tokens_out * price.output_per_m) / 1_000_000
    return round(cost, 8)


def estimate_tokens_cost(provider: str, model: str, tokens_in: int, tokens_out: int) -> float:
    return estimate_cost(provider, model, {"tokens_in": tokens_in, "tokens_out": tokens_out, "cached_tokens": 0})


def price_table_snapshot() -> dict[str, Any]:
    return {"version": PRICE_TABLE_VERSION,
            "models": {p: {m: v.as_dict() for m, v in t.items()} for p, t in PRICES.items()},
            "media": dict(MEDIA_PRICES), "search": dict(SEARCH_PRICES)}

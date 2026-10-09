"""Lazy, failure-tolerant access to the AI core (cheap LLM tier + embeddings).

Everything here returns ``None`` when the AI core isn't installed, no provider is configured, or a call fails — callers
then use the deterministic path. Costs are reported back so the pipeline can account them on research_runs.cost_usd.
"""
from __future__ import annotations

import inspect
import json
import re
from dataclasses import dataclass, field
from typing import Any
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.core.logging import get_logger

log = get_logger("research.ai")

# Rough $/1M-token fallbacks when the AI core exposes no pricing helper.
_FALLBACK_PRICES = {"cheap": (1.0, 5.0), "embedding": (0.02, 0.0)}


async def _maybe_await(v: Any) -> Any:
    return await v if inspect.isawaitable(v) else v


def _has_credentials(provider: Any) -> bool:
    """Skip keyed providers that were constructed without a key (they would only produce failing network calls)."""
    name = str(getattr(provider, "name", "") or getattr(provider, "provider_name", "")).lower()
    if name in ("ollama", "local", "fake"):
        return True
    if hasattr(provider, "_api_key"):
        return bool(provider._api_key)
    return True


@dataclass
class CheapLLM:
    provider: Any
    model: str
    spent_usd: float = 0.0
    calls: int = 0
    errors: list[str] = field(default_factory=list)
    max_consecutive_errors: int = 2
    _consecutive_errors: int = 0

    @property
    def disabled(self) -> bool:
        return self._consecutive_errors >= self.max_consecutive_errors

    def _cost(self, usage: Any) -> float:
        try:
            from app.integrations.ai import pricing  # type: ignore[attr-defined]
            for fn_name in ("cost_usd", "estimate_cost", "compute_cost"):
                fn = getattr(pricing, fn_name, None)
                if fn:
                    return float(fn(self.model, usage))
        except Exception:
            pass
        pin, pout = _FALLBACK_PRICES["cheap"]
        tin = getattr(usage, "tokens_in", 0) or 0
        tout = getattr(usage, "tokens_out", 0) or 0
        return (tin * pin + tout * pout) / 1_000_000

    async def complete_json(self, system: str, user: str, *, max_tokens: int = 800,
                            schema: dict[str, Any] | None = None) -> dict[str, Any] | None:
        """One JSON-returning call; returns None on any failure (callers fall back to heuristics). After repeated
        failures (e.g. no API key configured) the helper disables itself for the rest of the run."""
        if self.disabled:
            return None
        try:
            from app.core.ports.ai_provider import Message
            msgs = [Message(role="system", content=system), Message(role="user", content=user)]
            kwargs: dict[str, Any] = {"model": self.model, "temperature": 0.1, "max_tokens": max_tokens}
            if schema is not None:
                kwargs["response_schema"] = schema
            comp = await self.provider.complete(msgs, **kwargs)
            self.calls += 1
            self.spent_usd += self._cost(getattr(comp, "usage", None))
            self._consecutive_errors = 0
            return parse_json_object(getattr(comp, "content", "") or "")
        except Exception as e:  # provider errors, budget refusals, schema problems
            self._consecutive_errors += 1
            self.errors.append(f"{type(e).__name__}: {e}"[:300])
            log.info("research.llm_failed", error=str(e)[:200])
            return None


def parse_json_object(text: str) -> dict[str, Any] | None:
    text = text.strip()
    if text.startswith("```"):
        text = re.sub(r"^```(?:json)?\s*|\s*```$", "", text, flags=re.S)
    try:
        v = json.loads(text)
        return v if isinstance(v, dict) else None
    except ValueError:
        m = re.search(r"\{.*\}", text, re.S)
        if m:
            try:
                v = json.loads(m.group(0))
                return v if isinstance(v, dict) else None
            except ValueError:
                return None
    return None


async def get_cheap_llm(db: AsyncSession | None, workspace_id: UUID | None) -> CheapLLM | None:
    try:
        from app.integrations.ai.registry import provider_for_tier  # type: ignore[import-not-found]
    except ImportError:
        return None
    try:
        res = await _maybe_await(provider_for_tier(db, workspace_id, "cheap"))
    except Exception as e:
        log.info("research.llm_unavailable", error=str(e)[:200])
        return None
    if res is None:
        return None
    provider, model = res, None
    if isinstance(res, tuple | list):
        provider = res[0]
        model = res[1] if len(res) > 1 else None
    elif isinstance(res, dict):
        provider, model = res.get("provider"), res.get("model")
    if provider is None or not hasattr(provider, "complete") or not _has_credentials(provider):
        return None
    model = model or getattr(provider, "model", None) or getattr(provider, "default_model", None) or settings.default_cheap_model
    if isinstance(model, str) and "/" in model and getattr(provider, "name", "") and model.split("/", 1)[0] == provider.name:
        model = model.split("/", 1)[1]
    return CheapLLM(provider=provider, model=str(model))


@dataclass
class Embedder:
    provider: Any
    model: str
    dims: int
    spent_usd: float = 0.0
    failures: int = 0

    async def embed(self, texts: list[str]) -> list[list[float]] | None:
        if not texts:
            return []
        if self.failures >= 2:  # provider unreachable/misconfigured: stop trying for this run
            return None
        try:
            vecs = await self.provider.embed(texts)
        except Exception as e:
            self.failures += 1
            log.info("research.embed_failed", error=str(e)[:200])
            return None
        if not vecs or len(vecs) != len(texts) or any(len(v) != self.dims for v in vecs):
            return None
        approx_tokens = sum(len(t.split()) / 0.75 for t in texts)
        self.spent_usd += approx_tokens * _FALLBACK_PRICES["embedding"][0] / 1_000_000
        return [list(map(float, v)) for v in vecs]


async def get_embedder(db: AsyncSession | None, workspace_id: UUID | None) -> Embedder | None:
    try:
        from app.integrations.embeddings.registry import (
            get_embedding_provider,  # type: ignore[import-not-found]
        )
    except ImportError:
        return None
    try:
        provider = await _maybe_await(get_embedding_provider(db, workspace_id))
    except Exception as e:
        log.info("research.embeddings_unavailable", error=str(e)[:200])
        return None
    if provider is None or not hasattr(provider, "embed") or not _has_credentials(provider):
        return None
    dims = int(getattr(provider, "dims", 0) or settings.embedding_dims)
    if dims != settings.embedding_dims:  # vector column dimension is fixed by the migration
        log.warning("research.embedding_dims_mismatch", provider_dims=dims, column_dims=settings.embedding_dims)
        return None
    return Embedder(provider=provider, model=str(getattr(provider, "model", "unknown")), dims=dims)

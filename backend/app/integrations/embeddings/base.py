"""Shared embedding helpers: batching, truncation, dimension enforcement (settings.embedding_dims)."""
from __future__ import annotations

import math
from typing import Any

from app.config import settings
from app.core.logging import get_logger

log = get_logger("embeddings")

MAX_BATCH = 100
MAX_CHARS = 8000


class EmbeddingError(Exception):
    pass


def chunk(items: list[Any], size: int = MAX_BATCH) -> list[list[Any]]:
    return [items[i:i + size] for i in range(0, len(items), size)]


def prepare_texts(texts: list[str]) -> list[str]:
    return [(t or " ")[:MAX_CHARS] for t in texts]


def fit_dims(vec: list[float], dims: int, *, model: str = "") -> list[float]:
    """Vectors must match the pgvector column dimension; pad with zeros / truncate (warn once per model)."""
    n = len(vec)
    if n == dims:
        return vec
    if model not in _dims_warned:
        _dims_warned.add(model)
        log.warning("embeddings.dims_mismatch", model=model, got=n, expected=dims)
    if n > dims:
        out = vec[:dims]
    else:
        out = list(vec) + [0.0] * (dims - n)
    return normalize(out)


_dims_warned: set[str] = set()


def normalize(vec: list[float]) -> list[float]:
    norm = math.sqrt(sum(x * x for x in vec))
    if norm == 0:
        return vec
    return [x / norm for x in vec]


def cosine(a: list[float], b: list[float]) -> float:
    if not a or not b or len(a) != len(b):
        return 0.0
    dot = sum(x * y for x, y in zip(a, b, strict=False))
    na = math.sqrt(sum(x * x for x in a))
    nb = math.sqrt(sum(y * y for y in b))
    return dot / (na * nb) if na and nb else 0.0


class BaseEmbeddingProvider:
    name: str = "base"
    model: str = ""
    dims: int = settings.embedding_dims

    async def _embed_batch(self, texts: list[str]) -> list[list[float]]:  # pragma: no cover - abstract
        raise NotImplementedError

    async def embed(self, texts: list[str]) -> list[list[float]]:
        if not texts:
            return []
        out: list[list[float]] = []
        for batch in chunk(prepare_texts(texts)):
            vectors = await self._embed_batch(batch)
            out.extend(fit_dims(list(v), self.dims, model=self.model) for v in vectors)
        return out

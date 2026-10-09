"""Deterministic fake embeddings for tests: sha256-seeded unit vectors of settings.embedding_dims."""
from __future__ import annotations

import hashlib
import random

from app.config import settings
from app.integrations.embeddings.base import BaseEmbeddingProvider, normalize


class FakeEmbeddingProvider(BaseEmbeddingProvider):
    name = "fake"
    model = "fake-embed"

    def __init__(self, dims: int | None = None):
        self.dims = dims or settings.embedding_dims
        self.calls: list[list[str]] = []

    def _vector(self, text: str) -> list[float]:
        seed = int.from_bytes(hashlib.sha256(text.strip().lower().encode()).digest()[:8], "big")
        rng = random.Random(seed)
        return normalize([rng.uniform(-1.0, 1.0) for _ in range(self.dims)])

    async def _embed_batch(self, texts: list[str]) -> list[list[float]]:
        self.calls.append(list(texts))
        return [self._vector(t) for t in texts]

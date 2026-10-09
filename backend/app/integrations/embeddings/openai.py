"""OpenAI embeddings (text-embedding-3-small/large) via the official SDK; dims reduced to settings.embedding_dims."""
from __future__ import annotations

from typing import Any

from app.config import settings
from app.integrations.embeddings.base import BaseEmbeddingProvider, EmbeddingError


class OpenAIEmbeddingProvider(BaseEmbeddingProvider):
    name = "openai"

    def __init__(self, model: str = "text-embedding-3-small", api_key: str | None = None, base_url: str | None = None,
                 dims: int | None = None, *, provider_name: str = "openai"):
        self.name = provider_name
        self.model = model
        self.dims = dims or settings.embedding_dims
        self._api_key = api_key or settings.openai_api_key or None
        self._base_url = base_url
        self._client: Any = None

    def _get_client(self):
        if self._client is None:
            from openai import AsyncOpenAI
            kwargs: dict[str, Any] = {"api_key": self._api_key or "missing", "max_retries": 2, "timeout": 60.0}
            if self._base_url:
                kwargs["base_url"] = self._base_url
            self._client = AsyncOpenAI(**kwargs)
        return self._client

    async def _embed_batch(self, texts: list[str]) -> list[list[float]]:
        kwargs: dict[str, Any] = {"model": self.model, "input": texts}
        if self.model.startswith("text-embedding-3"):
            kwargs["dimensions"] = self.dims
        try:
            resp = await self._get_client().embeddings.create(**kwargs)
        except Exception as e:  # noqa: BLE001
            raise EmbeddingError(f"{self.name} embeddings failed: {e}") from e
        data = sorted(resp.data, key=lambda d: d.index)
        return [list(d.embedding) for d in data]

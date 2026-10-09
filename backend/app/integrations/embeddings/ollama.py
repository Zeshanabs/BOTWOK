"""Ollama embeddings (nomic-embed-text, mxbai-embed-large, ...) through its OpenAI-compatible /v1/embeddings endpoint."""
from __future__ import annotations

from app.config import settings
from app.integrations.embeddings.openai import OpenAIEmbeddingProvider


class OllamaEmbeddingProvider(OpenAIEmbeddingProvider):
    def __init__(self, model: str = "nomic-embed-text", base_url: str | None = None, dims: int | None = None):
        super().__init__(model=model, api_key="ollama", base_url=base_url or settings.ollama_base_url, dims=dims,
                         provider_name="ollama")

    async def _embed_batch(self, texts: list[str]) -> list[list[float]]:
        # Ollama ignores `dimensions`; base.fit_dims pads/truncates to the configured column width.
        resp = await self._get_client().embeddings.create(model=self.model, input=texts)
        data = sorted(resp.data, key=lambda d: d.index)
        return [list(d.embedding) for d in data]

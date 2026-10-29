"""get_embedding_provider(db, workspace_id) -> EmbeddingProvider honoring ai_settings.routing.embeddings."""
from __future__ import annotations

import hashlib
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.core.ports.embedding_provider import EmbeddingProvider
from app.integrations.ai.registry import env_api_key, get_routing, resolve_model

_cache: dict[str, EmbeddingProvider] = {}
_override: EmbeddingProvider | None = None


def register_embedding_provider(provider: EmbeddingProvider | None) -> None:
    """Test hook: force every lookup to return `provider` (None clears)."""
    global _override
    _override = provider


class EmbeddingsUnavailable(RuntimeError):
    """Raised before any network call when no key/provider is configured; callers degrade gracefully."""


def embedding_provider_for_spec(spec: str, api_key: str | None = None) -> EmbeddingProvider:
    if _override is not None:
        return _override
    provider, model = resolve_model(spec)
    key = api_key or env_api_key(provider)
    if not key and provider not in ("ollama", "fake", "local"):
        raise EmbeddingsUnavailable(f"no API key configured for embedding provider '{provider}'")
    cache_key = f"{provider}/{model}:{hashlib.sha256((key or '').encode()).hexdigest()[:12]}"
    if cache_key in _cache:
        return _cache[cache_key]
    if provider == "fake":
        from app.integrations.embeddings.fake import FakeEmbeddingProvider
        p: EmbeddingProvider = FakeEmbeddingProvider(settings.embedding_dims)
    elif provider == "ollama":
        from app.integrations.embeddings.ollama import OllamaEmbeddingProvider
        p = OllamaEmbeddingProvider(model=model)
    elif provider == "openai":
        from app.integrations.embeddings.openai import OpenAIEmbeddingProvider
        p = OpenAIEmbeddingProvider(model=model, api_key=key)
    elif provider == "google":
        from app.integrations.ai.registry import PROVIDER_BASE_URLS
        from app.integrations.embeddings.openai import OpenAIEmbeddingProvider
        p = OpenAIEmbeddingProvider(model=model, api_key=key, base_url=PROVIDER_BASE_URLS["google"], provider_name="google")
    else:
        raise ValueError(f"no embedding provider for {spec!r}")
    _cache[cache_key] = p
    return p


async def get_embedding_provider(db: AsyncSession | None, workspace_id: UUID | str | None) -> EmbeddingProvider:
    if _override is not None:
        return _override
    routing = await get_routing(db, workspace_id)
    tier = routing.get("embeddings") or {}
    spec = tier.get("primary") if isinstance(tier, dict) else tier
    spec = spec or settings.default_embedding_model
    provider, _ = resolve_model(spec)
    key = None
    if db is not None and workspace_id is not None:
        try:
            from app.services.ai_settings_service import AISettingsService
            key = await AISettingsService().get_provider_key(db, UUID(str(workspace_id)), provider)
        except Exception:  # noqa: BLE001
            key = None
    return embedding_provider_for_spec(spec, key)

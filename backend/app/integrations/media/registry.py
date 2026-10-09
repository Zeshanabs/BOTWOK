"""Image provider registry: name → provider, env/workspace key detection, fallback order openai → xai → fake.

- Keys: env (`OPENAI_API_KEY`, `XAI_API_KEY`) overridden by workspace `provider_secrets` when
  `app.services.ai_settings_service.get_provider_key(db, workspace_id, provider)` exists.
- Default provider: explicit name > `ai_settings.media.image_provider` ("openai/gpt-image-1") or `media.image.primary`
  > env `BOTWOK_IMAGE_PROVIDER` > first configured.
- `fake` is only auto-selected outside production (or with BOTWOK_ALLOW_FAKE_IMAGES=1) and only when no real
  provider is configured.
"""
from __future__ import annotations

import inspect
import os
from collections.abc import Callable
from typing import Any
from uuid import UUID

from app.config import settings
from app.core.errors import ProblemError
from app.core.logging import get_logger
from app.integrations.media.base import ImageProvider
from app.integrations.media.fake_images import FakeImageProvider

log = get_logger("media.providers")

FALLBACK_ORDER: tuple[str, ...] = ("openai", "xai", "fake")
KEYED_PROVIDERS: tuple[str, ...] = ("openai", "xai")


def _openai(key: str, model: str | None) -> ImageProvider:
    from app.integrations.media.openai_images import DEFAULT_MODEL, OpenAIImageProvider
    return OpenAIImageProvider(key, model=model or DEFAULT_MODEL)


def _xai(key: str, model: str | None) -> ImageProvider:
    from app.integrations.media.xai_images import DEFAULT_MODEL, XAIImageProvider
    return XAIImageProvider(key, model=model or DEFAULT_MODEL)


_FACTORIES: dict[str, Callable[[str, str | None], ImageProvider]] = {"openai": _openai, "xai": _xai}


def fake_allowed() -> bool:
    return settings.app_env != "production" or os.environ.get("BOTWOK_ALLOW_FAKE_IMAGES") == "1"


def env_keys() -> dict[str, str]:
    return {k: v for k, v in {"openai": settings.openai_api_key, "xai": settings.xai_api_key}.items() if v}


def available_image_providers(keys: dict[str, str] | None = None) -> list[str]:
    keys = env_keys() if keys is None else keys
    names = [n for n in KEYED_PROVIDERS if keys.get(n)]
    if fake_allowed():
        names.append("fake")
    return names


def build_image_provider(name: str, *, keys: dict[str, str] | None = None, model: str | None = None) -> ImageProvider:
    name = name.strip().lower()
    if name == "fake":
        if not fake_allowed():
            raise ProblemError(422, "image_provider_not_configured", "Fake image provider is disabled in production")
        return FakeImageProvider()
    if name not in _FACTORIES:
        raise ProblemError(422, "unknown_image_provider", "Unknown image provider",
                           f"'{name}' is not one of {', '.join(FALLBACK_ORDER)}")
    keys = env_keys() if keys is None else keys
    key = keys.get(name)
    if not key:
        raise ProblemError(422, "image_provider_not_configured", "Image provider not configured",
                           f"No API key for '{name}' (set it in Settings → AI or the environment)")
    return _FACTORIES[name](key, model)


def image_provider_chain(name: str | None = None, *, keys: dict[str, str] | None = None,
                         preferred: list[str] | None = None, model: str | None = None) -> list[ImageProvider]:
    """Providers to try in order. An explicit `name` disables fallback."""
    keys = env_keys() if keys is None else keys
    if name:
        return [build_image_provider(name, keys=keys, model=model)]
    order: list[str] = []
    env_default = os.environ.get("BOTWOK_IMAGE_PROVIDER")
    for n in [*(preferred or []), *([env_default] if env_default else []), *FALLBACK_ORDER]:
        n = (n or "").strip().lower()
        if n and n not in order:
            order.append(n)
    real = [n for n in order if n in KEYED_PROVIDERS and keys.get(n)]
    chain: list[ImageProvider] = []
    primary = (preferred[0].strip().lower() if preferred else None)
    for i, n in enumerate(real):
        use_model = model if i == 0 and (primary is None or n == primary) else None
        chain.append(build_image_provider(n, keys=keys, model=use_model))
    if not chain and fake_allowed():
        chain.append(FakeImageProvider())
    if not chain:
        raise ProblemError(501, "image_provider_not_configured", "No image provider configured",
                           "Add an OpenAI or xAI API key in Settings → AI.")
    return chain


def get_image_provider(name: str | None = None, *, keys: dict[str, str] | None = None,
                       model: str | None = None) -> ImageProvider:
    """First provider of the chain (explicit name, else openai → xai → fake by availability)."""
    return image_provider_chain(name, keys=keys, model=model)[0]


def _key_getter() -> Any:
    """ai-core's `get_provider_key(db, workspace_id, provider)` (module function or AISettingsService method)."""
    try:
        from app.services import ai_settings_service as svc  # owned by ai-core
    except ImportError:
        return None
    fn = getattr(svc, "get_provider_key", None)
    if fn is None and hasattr(svc, "AISettingsService"):
        fn = getattr(svc.AISettingsService(), "get_provider_key", None)
    return fn


async def resolve_provider_keys(db: Any, workspace_id: UUID | None) -> dict[str, str]:
    """Env keys overridden by workspace provider_secrets."""
    keys = env_keys()
    if db is None or workspace_id is None:
        return keys
    getter = _key_getter()
    if getter is None:
        return keys
    for provider in KEYED_PROVIDERS:
        try:
            value = getter(db, workspace_id, provider)
            if inspect.isawaitable(value):
                value = await value
        except Exception as e:  # a broken/absent secret must not hide the env key
            log.warning("media.provider_key_lookup_failed", provider=provider, error=str(e))
            continue
        if value:
            keys[provider] = str(value)
    return keys


async def workspace_media_settings(db: Any, workspace_id: UUID | None) -> dict[str, Any]:
    """Effective `ai_settings.media` (ai-core defaults merged) or the raw stored row as a fallback."""
    if db is None or workspace_id is None:
        return {}
    try:
        from app.services.ai_settings_service import AISettingsService
        eff = await AISettingsService().get(db, workspace_id)
        media = eff.get("media") if isinstance(eff, dict) else None
        if isinstance(media, dict):
            return media
    except ImportError:
        pass
    except Exception as e:
        log.warning("media.ai_settings_unavailable", error=str(e))
    try:
        from sqlalchemy import select

        from app.models.ai import AISettings
        row = (await db.execute(select(AISettings).where(AISettings.workspace_id == workspace_id))).scalar_one_or_none()
    except Exception as e:
        log.warning("media.ai_settings_unavailable", error=str(e))
        return {}
    return dict((row.media if row else None) or {})


def image_preferences(media: dict[str, Any]) -> tuple[list[str], str | None]:
    """Preferred provider order + model from either `image_provider: "openai/gpt-image-1"` (+ `image_fallback`)
    or doc 10's `image: {primary, fallback, model}` shape."""
    preferred: list[str] = []
    model: str | None = None
    image = media.get("image")
    if isinstance(image, dict):
        for k in ("primary", "fallback"):
            v = image.get(k)
            preferred.extend([v] if isinstance(v, str) else [str(x) for x in v] if isinstance(v, list) else [])
        model = image.get("model")
    for k in ("image_provider", "image_fallback"):
        v = media.get(k)
        for item in ([v] if isinstance(v, str) else v if isinstance(v, list) else []):
            prov, _, mdl = str(item).partition("/")
            preferred.append(prov)
            if k == "image_provider" and mdl and model is None:
                model = mdl
    out: list[str] = []
    for p in preferred:
        p = p.strip().lower()
        if p and p not in out:
            out.append(p)
    return out, model


async def get_workspace_image_providers(db: Any, workspace_id: UUID | None, name: str | None = None) -> list[ImageProvider]:
    keys = await resolve_provider_keys(db, workspace_id)
    preferred, model = image_preferences(await workspace_media_settings(db, workspace_id))
    if name:
        return image_provider_chain(name, keys=keys, model=model if preferred and preferred[0] == name else None)
    return image_provider_chain(None, keys=keys, preferred=preferred, model=model)

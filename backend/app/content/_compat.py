"""Lazy, failure-tolerant bridges to modules owned by concurrent builders (identity, brand, ai-core, memory).

Every helper degrades gracefully when the owner's module is not importable yet. Side-effect helpers that write to
the DB (audit, notify) run inside a SAVEPOINT so a failure there never poisons the caller's transaction.
"""
from __future__ import annotations

import importlib
import inspect
from typing import Any
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.logging import get_logger

log = get_logger("content.compat")


def optional_attr(module: str, name: str) -> Any | None:
    try:
        mod = importlib.import_module(module)
    except ImportError:
        return None
    return getattr(mod, name, None)


async def _maybe_await(v: Any) -> Any:
    if inspect.isawaitable(v):
        return await v
    return v


async def call_service(cls: Any, method: str, *args: Any, **kwargs: Any) -> Any:
    """Call ``cls.method`` whether it is a static/class method or an instance method (instantiating ``cls()``)."""
    raw = inspect.getattr_static(cls, method, None)
    if raw is None:
        raise AttributeError(method)
    if isinstance(raw, (staticmethod, classmethod)) or not inspect.isclass(cls):
        fn = getattr(cls, method)
    else:
        fn = getattr(cls(), method)
    return await _maybe_await(fn(*args, **kwargs))


async def audit(db: AsyncSession, member: Any, action: str, target_type: str, target_id: Any,
                before: dict[str, Any] | None = None, after: dict[str, Any] | None = None) -> None:
    fn = optional_attr("app.services.audit_service", "audit")
    if fn is None:
        return
    try:
        async with db.begin_nested():
            await _maybe_await(fn(db, member, action, target_type, str(target_id) if target_id is not None else None,
                                  before=before, after=after))
    except Exception as e:  # audit must never break the domain write
        log.warning("audit.failed", action=action, error=str(e))


async def notify(db: AsyncSession, workspace_id: UUID, kind: str, title: str, body: str | None, link: str | None,
                 user_id: UUID | None = None, severity: str = "info") -> None:
    cls = optional_attr("app.services.notification_service", "NotificationService")
    if cls is None:
        return
    try:
        async with db.begin_nested():
            await call_service(cls, "notify", db, workspace_id, kind, title, body, link, user_id=user_id, severity=severity)
    except Exception as e:
        log.warning("notify.failed", kind=kind, error=str(e))


async def brand_context(db: AsyncSession, workspace_id: UUID, brand_id: UUID, mode: str = "compact") -> str | None:
    cls = optional_attr("app.services.brand_service", "BrandService")
    if cls is None:
        return None
    try:
        return await call_service(cls, "build_context", db, brand_id, mode=mode)
    except Exception as e:
        log.warning("brand_context.failed", error=str(e))
        return None


def ai_service_class() -> Any | None:
    return optional_attr("app.agents.orchestrator.service", "AIService")


async def create_ai_run(db: AsyncSession, member: Any, *, message: str, brand_id: UUID | None, agent: str, action: str,
                        inputs: dict[str, Any]) -> Any:
    """``AIService.create_run(mode="tool")``. Raises ``ImportError`` when the AI core is not available."""
    cls = ai_service_class()
    if cls is None:
        raise ImportError("app.agents.orchestrator.service.AIService")
    return await call_service(cls, "create_run", db, member, message=message, brand_id=brand_id, mode="tool",
                              agent=agent, action=action, inputs=inputs)


async def get_embedding_provider(db: AsyncSession | None = None, workspace_id: Any = None) -> Any | None:
    """``app.integrations.embeddings.registry.get_embedding_provider(db, workspace_id)``; None when unavailable or when a
    remote provider has no API key (avoids slow failing network calls in offline/local setups)."""
    fn = optional_attr("app.integrations.embeddings.registry", "get_embedding_provider")
    if fn is None:
        return None
    try:
        try:
            prov = await _maybe_await(fn(db, workspace_id))
        except TypeError:
            prov = await _maybe_await(fn())
    except Exception as e:
        log.info("embeddings.unavailable", error=str(e))
        return None
    if getattr(prov, "name", "") in ("openai", "google") and not getattr(prov, "_api_key", "set"):
        return None
    return prov


async def embed_texts(texts: list[str], db: AsyncSession | None = None,
                      workspace_id: Any = None) -> tuple[list[list[float]], str | None] | None:
    import asyncio
    prov = await get_embedding_provider(db, workspace_id)
    if prov is None:
        return None
    try:
        vecs = await asyncio.wait_for(prov.embed(texts), timeout=8)
        return vecs, getattr(prov, "model", None)
    except Exception as e:
        log.info("embeddings.failed", error=str(e))
        return None

"""Content event consumers (doc 18 §18.3).

- ``VARIANT_CREATED`` → critic auto-pass (``AIService.create_run(mode="tool", agent="critic", action="critique")``),
  skipped silently when the AI core is not installed.
- ``CONTENT_APPROVED`` → content memory note via ``MemoryService.remember(...)`` when the memory module exists.

Imported for its side effect by ``app.services.content_service`` (loaded by both API and workers).
Consumers are idempotent by ``event_id`` (best effort, Redis SET NX) since the relay is at-least-once.
"""
from __future__ import annotations

from typing import Any
from uuid import UUID

from sqlalchemy import select

from app.content import _compat
from app.core.db import session_scope
from app.core.events import on_event
from app.core.logging import get_logger

log = get_logger("consumers.content")


async def _first_time(event_id: str | None, consumer: str) -> bool:
    if not event_id:
        return True
    try:
        from app.core.redis import get_redis
        return bool(await get_redis().set(f"consumed:{consumer}:{event_id}", "1", nx=True, ex=7 * 86400))
    except Exception:
        return True


async def _member_for(db: Any, workspace_id: UUID, user_id: UUID | None) -> Any | None:
    from app.api.deps import Member
    from app.models import User, WorkspaceMember
    if user_id is None:
        return None
    row = (await db.execute(select(WorkspaceMember).where(WorkspaceMember.workspace_id == workspace_id,
                                                          WorkspaceMember.user_id == user_id))).scalar_one_or_none()
    user = await db.get(User, user_id)
    if row is None or user is None:
        return None
    return Member(user=user, workspace_id=workspace_id, role=row.role)


def _uuid(v: Any) -> UUID | None:
    try:
        return UUID(str(v))
    except (TypeError, ValueError):
        return None


@on_event("VARIANT_CREATED")
async def critic_auto_pass(envelope: dict[str, Any]) -> None:
    if _compat.ai_service_class() is None:
        return
    payload = envelope.get("payload") or {}
    ws = _uuid(envelope.get("workspace_id"))
    variant_id = _uuid(payload.get("variant_id"))
    item_id = _uuid(payload.get("content_item_id"))
    if not ws or not variant_id or not item_id or payload.get("auto_critic") is False:
        return
    if not await _first_time(envelope.get("event_id"), "critic_auto_pass"):
        return
    from app.models import ContentItem, ContentVariant
    async with session_scope(ws) as db:
        v = (await db.execute(select(ContentVariant).where(ContentVariant.id == variant_id,
                                                           ContentVariant.workspace_id == ws))).scalar_one_or_none()
        item = (await db.execute(select(ContentItem).where(ContentItem.id == item_id, ContentItem.workspace_id == ws,
                                                           ContentItem.deleted_at.is_(None)))).scalar_one_or_none()
        if v is None or item is None or v.critique is not None:
            return
        actor = envelope.get("actor") or {}
        user_id = _uuid(actor.get("id")) if actor.get("type") == "user" else _uuid(actor.get("on_behalf_of"))
        member = await _member_for(db, ws, user_id or item.created_by)
        if member is None:
            return
        try:
            await _compat.create_ai_run(db, member, message=f"Critique {v.platform.value} variant of '{item.title}'",
                                        brand_id=item.brand_id, agent="critic", action="critique",
                                        inputs={"content_id": str(item.id), "variant_id": str(v.id),
                                                "brand_id": str(item.brand_id), "target_type": "variant",
                                                "target_id": str(v.id), "auto": True})
        except ImportError:
            return
        except Exception as e:  # budget exceeded, provider missing… never break the relay
            log.info("critic_auto_pass.skipped", variant_id=str(v.id), error=str(e))


@on_event("CONTENT_APPROVED")
async def remember_approved_content(envelope: dict[str, Any]) -> None:
    cls = _compat.optional_attr("app.agents.orchestrator.memory", "MemoryService")
    if cls is None:
        return
    payload = envelope.get("payload") or {}
    ws = _uuid(envelope.get("workspace_id"))
    item_id = _uuid(payload.get("content_item_id"))
    if not ws or not item_id:
        return
    if not await _first_time(envelope.get("event_id"), "remember_approved_content"):
        return
    from app.models import ContentItem
    async with session_scope(ws) as db:
        item = (await db.execute(select(ContentItem).where(ContentItem.id == item_id, ContentItem.workspace_id == ws))
                ).scalar_one_or_none()
        if item is None:
            return
        body = item.body or {}
        platforms = sorted({v.platform.value for v in item.variants or []})
        note = (f"Approved content: {item.title}\nType: {getattr(item.content_type, 'value', item.content_type) or 'n/a'}; "
                f"format: {item.master_format.value}; platforms: {', '.join(platforms) or 'n/a'}\n"
                f"Hook: {body.get('hook') or ''}\n{(body.get('body_md') or '')[:1200]}")
        meta = {"content_item_id": str(item.id), "pillar_id": str(item.pillar_id) if item.pillar_id else None,
                "platforms": platforms, "ai_generated": item.ai_generated, "approver": payload.get("approver")}
        attempts = (
            {"workspace_id": ws, "brand_id": item.brand_id, "kind": "content", "content": note, "meta": meta,
             "ref_type": "content_item", "ref_id": item.id},
            {"workspace_id": ws, "brand_id": item.brand_id, "kind": "content", "content": note},
        )
        for kwargs in attempts:
            try:
                async with db.begin_nested():
                    await _compat.call_service(cls, "remember", db, **kwargs)
                return
            except TypeError:
                continue
            except Exception as e:
                log.info("content_memory.failed", content_item_id=str(item.id), error=str(e))
                return

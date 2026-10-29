"""Jobs: media (queue `media`, CPU-bound — renditions, generation)."""
from __future__ import annotations

from uuid import UUID

from app.core.db import session_scope
from app.core.logging import get_logger
from app.workers.app import procrastinate_app

log = get_logger("jobs.media")


def _actor(workspace_id: str, user_id: str | None):
    from app.services.media_service import Actor
    return Actor(workspace_id=UUID(workspace_id), user_id=UUID(user_id) if user_id else None)


@procrastinate_app.task(name="jobs.media.transform", queue="media", retry=2)
async def transform(media_id: str, workspace_id: str, platform: str, format: str, aspect: str | None = None,
                    pad_color: str | None = None, user_id: str | None = None) -> str:
    """Produce a platform rendition (MediaService.transform_for_platform); emits MEDIA_PROCESSED. Returns rendition id."""
    from app.services.media_service import MediaService
    async with session_scope(UUID(workspace_id)) as db:
        rendition = await MediaService.transform_for_platform(db, _actor(workspace_id, user_id), UUID(media_id),
                                                              platform, format, aspect=aspect, pad_color=pad_color)
        rid = str(rendition.id)
    log.info("media.transform.done", media_id=media_id, rendition_id=rid, platform=platform, format=format)
    return rid


@procrastinate_app.task(name="jobs.media.generate", queue="media", retry=1)
async def generate(workspace_id: str, prompt: str, brand_id: str | None = None, provider: str | None = None,
                   size: str = "1024x1024", n: int = 1, negative_prompt: str | None = None, style: str | None = None,
                   quality: str | None = None, reference_asset_ids: list[str] | None = None,
                   user_id: str | None = None, ai_run_id: str | None = None, alt_text: str | None = None) -> list[str]:
    """Generate images (MediaService.generate_image); emits MEDIA_GENERATED per asset. Returns media ids."""
    from app.services.media_service import MediaService
    async with session_scope(UUID(workspace_id)) as db:
        assets = await MediaService.generate_image(
            db, _actor(workspace_id, user_id), UUID(brand_id) if brand_id else None, prompt, provider, size, n,
            negative_prompt=negative_prompt, style=style, quality=quality,
            reference_asset_ids=[UUID(r) for r in reference_asset_ids or []],
            ai_run_id=UUID(ai_run_id) if ai_run_id else None, alt_text=alt_text)
        ids = [str(a.id) for a in assets]
    log.info("media.generate.done", count=len(ids), provider=provider)
    return ids

"""MediaService: uploads (presigned PUT → validate → re-encode → catalog), generation via ImageProvider registry,
platform renditions, background removal, carousels, URLs (doc 10).

Object layout: uploads land in bucket `tmp` at `{workspace}/{uuid}.{ext}`; catalogued files live in the media bucket at
`{workspace}/{kind}/{yyyy}/{mm}/{uuid}.{ext}`. Renditions are separate `media_assets` rows with `derived_from_id`.
"""
from __future__ import annotations

import asyncio
import hashlib
import io
import re
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any, cast
from uuid import UUID

from botocore.exceptions import ClientError
from PIL import Image
from sqlalchemy import func, select, tuple_
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.core.errors import ProblemError, not_found, validation
from app.core.events import emit
from app.core.ids import new_id
from app.core.logging import get_logger
from app.core.pagination import decode_cursor, encode_cursor
from app.integrations.media.base import GeneratedImage, ImageProviderError, parse_size
from app.integrations.media.registry import get_workspace_image_providers, workspace_media_settings
from app.integrations.storage.s3 import storage
from app.media import platform_specs as specs
from app.media.pipelines import image as imgp
from app.media.pipelines import video as vidp
from app.media.pipelines.carousel import compose_slides, slides_to_pdf
from app.models.brand import Brand, BrandSettings
from app.models.content import ContentAsset, ContentItem, ContentVariant, MediaAsset
from app.models.platform import UsageLedger
from app.schemas.media import MediaUpdate
from app.services.brand_service import actor_dict, actor_user_id, safe_audit

log = get_logger("media")

TMP_BUCKET = "tmp"
UPLOAD_MIMES: dict[str, str] = {
    "image/jpeg": "jpg", "image/png": "png", "image/webp": "webp", "image/gif": "gif",
    "video/mp4": "mp4", "video/quicktime": "mov", "video/webm": "webm",
    "audio/mpeg": "mp3", "audio/mp4": "m4a", "audio/wav": "wav", "audio/x-wav": "wav", "audio/ogg": "ogg",
    "application/pdf": "pdf",
}
EXT_FOR_MIME = {**UPLOAD_MIMES, "audio/x-wav": "wav"}
MAX_BYTES: dict[str, int] = {"image": 50 * 1024 * 1024, "video": 1024 * 1024 * 1024, "audio": 200 * 1024 * 1024,
                             "document": 100 * 1024 * 1024}
PRESIGN_PUT_TTL_S = 900
PRESIGN_GET_TTL_S = 3600
CONTENT_ASSET_ROLES = {"primary", "carousel_slide", "thumbnail", "cover", "subtitle"}
COLUMN_FIELDS = {"alt_text", "caption", "labels", "ai_generated", "provider", "model", "prompt", "seed",
                 "generation_params", "derived_from_id", "transform", "platform_target", "carousel_group_id", "position",
                 "width", "height", "duration_ms", "fps", "codec", "status", "error"}


@dataclass
class Actor:
    """Minimal actor for jobs/tools (audited as {"type": "agent"|"user"|"system"} by `safe_audit`)."""
    workspace_id: UUID
    user_id: UUID | None = None
    role: str | None = None
    agent_id: str | None = None


@dataclass
class Ingested:
    kind: str
    mime: str
    data: bytes
    width: int | None = None
    height: int | None = None
    duration_ms: int | None = None
    fps: float | None = None
    codec: str | None = None
    labels: list[str] = field(default_factory=list)

    @property
    def ext(self) -> str:
        return EXT_FOR_MIME.get(self.mime, "bin")


def kind_for_mime(mime: str) -> str:
    if mime.startswith("image/"):
        return "image"
    if mime.startswith("video/"):
        return "video"
    if mime.startswith("audio/"):
        return "audio"
    return "document"


def _ws(member: Any) -> UUID:
    ws = getattr(member, "workspace_id", None)
    if ws is None:
        raise ProblemError(400, "workspace_required", "Workspace context required")
    return ws if isinstance(ws, UUID) else UUID(str(ws))


def media_key(workspace_id: UUID, kind: str, asset_id: UUID, ext: str, now: datetime | None = None) -> str:
    now = now or datetime.now(UTC)
    return f"{workspace_id}/{kind}/{now:%Y}/{now:%m}/{asset_id}.{ext}"


async def ingest_bytes(data: bytes, *, reencode_images: bool = True) -> Ingested:
    """Validate by magic bytes (Pillow for images, ffprobe for audio/video, `%PDF-` for documents) and normalize."""
    if not data:
        raise ProblemError(422, "empty_file", "The uploaded file is empty")
    if data[:5] == b"%PDF-":
        if len(data) > MAX_BYTES["document"]:
            raise ProblemError(413, "file_too_large", "File too large", "Documents are limited to 100 MB")
        return Ingested(kind="document", mime="application/pdf", data=data)
    av_mime = vidp.sniff_av_mime(data)
    if av_mime:
        kind = kind_for_mime(av_mime)
        if len(data) > MAX_BYTES[kind]:
            raise ProblemError(413, "file_too_large", "File too large", f"{kind} files are limited to "
                               f"{MAX_BYTES[kind] // (1024 * 1024)} MB")
        try:
            info = await vidp.probe(data)
        except ProblemError as e:
            if e.type != "ffmpeg_missing":
                raise
            log.warning("media.unprobed_upload", mime=av_mime, reason="ffmpeg_missing")
            return Ingested(kind=kind, mime=av_mime, data=data, labels=["unprobed"])
        if kind == "video" and not info.has_video:
            if not info.has_audio:
                raise ProblemError(422, "invalid_video", "Invalid video", "No video or audio stream found")
            kind, av_mime = "audio", "audio/mp4" if av_mime in ("video/mp4", "video/quicktime") else av_mime
        if kind == "audio" and not info.has_audio:
            raise ProblemError(422, "invalid_audio", "Invalid audio", "No audio stream found")
        return Ingested(kind=kind, mime=av_mime, data=data, width=info.width, height=info.height,
                        duration_ms=info.duration_ms, fps=info.fps, codec=info.codec if kind == "video" else info.audio_codec)
    meta = imgp.validate_image(data, max_bytes=MAX_BYTES["image"])
    if not reencode_images:
        return Ingested(kind="image", mime=meta["mime"], data=data, width=meta["width"], height=meta["height"])
    enc = await asyncio.to_thread(imgp.reencode, data)
    return Ingested(kind="image", mime=enc.mime, data=enc.data, width=enc.width, height=enc.height,
                    labels=["animated"] if meta["animated"] and enc.mime == "image/gif" else [])


class MediaService:
    """All methods are classmethods (call on the class or an instance)."""

    # ------------------------------------------------------------ uploads
    @classmethod
    async def create_upload_url(cls, member: Any, filename: str, content_type: str,
                                size_bytes: int | None = None) -> dict[str, Any]:
        ctype = content_type.split(";")[0].strip().lower()
        if ctype == "image/svg+xml":
            raise ProblemError(415, "unsupported_media_type", "SVG uploads are not allowed",
                               "Upload a PNG or JPEG instead (SVG can carry scripts).")
        if ctype not in UPLOAD_MIMES:
            raise ProblemError(415, "unsupported_media_type", "Unsupported media type",
                               f"Allowed: {', '.join(sorted(UPLOAD_MIMES))}")
        kind = kind_for_mime(ctype)
        if size_bytes and size_bytes > MAX_BYTES[kind]:
            raise ProblemError(413, "file_too_large", "File too large",
                               f"{kind} files are limited to {MAX_BYTES[kind] // (1024 * 1024)} MB")
        key = f"{_ws(member)}/{new_id()}.{UPLOAD_MIMES[ctype]}"
        url = await storage.presign_put(TMP_BUCKET, key, ctype, PRESIGN_PUT_TTL_S)
        return {"upload_url": url, "key": key, "bucket": TMP_BUCKET, "method": "PUT",
                "headers": {"Content-Type": ctype}, "expires_in": PRESIGN_PUT_TTL_S, "filename": filename}

    @classmethod
    async def register_upload(cls, db: AsyncSession, member: Any, key: str, filename: str, *,
                              brand_id: UUID | None = None, alt_text: str | None = None,
                              caption: str | None = None) -> MediaAsset:
        ws = _ws(member)
        if not re.fullmatch(rf"{ws}/[0-9a-fA-F-]{{36}}\.[a-z0-9]{{2,5}}", key or ""):
            raise ProblemError(403, "forbidden", "Forbidden", "Upload key does not belong to this workspace")
        if brand_id:
            await cls._check_brand(db, ws, brand_id)
        try:
            raw = await storage.get(TMP_BUCKET, key)
        except ClientError as e:
            code = (e.response.get("Error") or {}).get("Code", "")
            if code in ("NoSuchKey", "404", "NotFound"):
                raise ProblemError(404, "upload_not_found", "Upload not found",
                                   "PUT the file to the upload URL first (URLs expire after 15 minutes)") from e
            raise
        ing = await ingest_bytes(raw)
        asset = await cls._store(db, ws, ing, source="upload", brand_id=brand_id, created_by=actor_user_id(member),
                                 alt_text=alt_text, caption=caption,
                                 generation_params={"original_filename": filename[:255]})
        try:
            await storage.delete(TMP_BUCKET, key)
        except Exception as e:  # tmp bucket is swept by maintenance anyway
            log.warning("media.tmp_delete_failed", key=key, error=str(e))
        await emit(db, "MEDIA_PROCESSED", cls._event_payload(asset, step="ingest"), workspace_id=ws,
                   actor=actor_dict(member))
        await safe_audit(db, member, "media.upload", "media_asset", asset.id,
                         after={"kind": asset.kind, "mime": asset.mime, "bytes": asset.bytes, "sha256": asset.sha256})
        return asset

    @classmethod
    async def _store(cls, db: AsyncSession, workspace_id: UUID, ing: Ingested, *, source: str,
                     brand_id: UUID | None = None, created_by: UUID | None = None, **fields: Any) -> MediaAsset:
        asset_id = new_id()
        key = media_key(workspace_id, ing.kind, asset_id, ing.ext)
        bucket = settings.s3_bucket_media
        await storage.put(bucket, key, ing.data, ing.mime)
        labels = list(dict.fromkeys([*(fields.pop("labels", None) or []), *ing.labels]))
        cols = {k: v for k, v in fields.items() if k in COLUMN_FIELDS and v is not None}
        for k in ("width", "height", "duration_ms", "fps", "codec"):
            if cols.get(k) is None and getattr(ing, k) is not None:
                cols[k] = getattr(ing, k)
        asset = MediaAsset(id=asset_id, workspace_id=workspace_id, brand_id=brand_id, kind=ing.kind, source=source,
                           bucket=bucket, object_key=key, mime=ing.mime, bytes=len(ing.data),
                           sha256=hashlib.sha256(ing.data).hexdigest(), labels=labels, created_by=created_by,
                           status=cols.pop("status", "ready"), **cols)
        db.add(asset)
        await db.flush()
        await db.refresh(asset)
        return asset

    @classmethod
    async def upload_bytes(cls, db: AsyncSession, *, workspace_id: UUID, data: bytes, kind: str | None = None,
                           source: str = "generated", mime: str | None = None, brand_id: UUID | None = None,
                           created_by: UUID | None = None, process: bool = True, **fields: Any) -> MediaAsset:
        """Catalog bytes produced inside Botwok (generation, renditions, carousels). No event is emitted here.

        process=True validates + re-encodes images (strip metadata); process=False trusts `mime`/dimensions given
        (used for renditions we just encoded ourselves). Extra kwargs map to media_assets columns.
        """
        if process or not mime:
            ing = await ingest_bytes(data, reencode_images=process)
        else:
            k = kind or kind_for_mime(mime)
            ing = Ingested(kind=k, mime=mime, data=data)
            if k == "image" and (fields.get("width") is None or fields.get("height") is None):
                with Image.open(io.BytesIO(data)) as im:
                    ing.width, ing.height = im.size
        if kind and ing.kind != kind:
            raise validation(f"Expected {kind} bytes, got {ing.kind}")
        return await cls._store(db, workspace_id, ing, source=source, brand_id=brand_id, created_by=created_by,
                                **fields)

    # ------------------------------------------------------------ catalog
    @classmethod
    async def list_media(cls, db: AsyncSession, workspace_id: UUID, *, kind: str | None = None,
                         brand_id: UUID | None = None, source: str | None = None, derived_from_id: UUID | None = None,
                         platform_target: str | None = None, carousel_group_id: UUID | None = None, limit: int = 50,
                         cursor: str | None = None) -> tuple[list[MediaAsset], str | None]:
        limit = max(1, min(limit, 200))
        stmt = select(MediaAsset).where(MediaAsset.workspace_id == workspace_id, MediaAsset.deleted_at.is_(None))
        if kind:
            stmt = stmt.where(MediaAsset.kind == kind)
        if brand_id:
            stmt = stmt.where(MediaAsset.brand_id == brand_id)
        if source:
            stmt = stmt.where(MediaAsset.source == source)
        if derived_from_id:
            stmt = stmt.where(MediaAsset.derived_from_id == derived_from_id)
        if platform_target:
            stmt = stmt.where(MediaAsset.platform_target == platform_target)
        if carousel_group_id:
            stmt = stmt.where(MediaAsset.carousel_group_id == carousel_group_id)
        cur = decode_cursor(cursor) if cursor else None
        if cur:
            try:
                c_at, c_id = datetime.fromisoformat(cur["c"]), UUID(cur["i"])
            except (KeyError, ValueError, TypeError) as e:
                raise validation("Invalid cursor") from e
            stmt = stmt.where(tuple_(MediaAsset.created_at, MediaAsset.id) < tuple_(c_at, c_id))
        rows = list((await db.execute(stmt.order_by(MediaAsset.created_at.desc(), MediaAsset.id.desc())
                                      .limit(limit + 1))).scalars().all())
        next_cursor = None
        if len(rows) > limit:
            rows = rows[:limit]
            last = rows[-1]
            next_cursor = encode_cursor({"c": last.created_at.isoformat(), "i": str(last.id)})
        return rows, next_cursor

    @classmethod
    async def get(cls, db: AsyncSession, workspace_id: UUID, media_id: UUID) -> MediaAsset:
        asset = (await db.execute(select(MediaAsset).where(MediaAsset.id == media_id,
                                                           MediaAsset.workspace_id == workspace_id,
                                                           MediaAsset.deleted_at.is_(None)))).scalar_one_or_none()
        if asset is None:
            raise not_found("Media asset")
        return asset

    @classmethod
    async def update(cls, db: AsyncSession, member: Any, media_id: UUID, data: MediaUpdate) -> MediaAsset:
        ws = _ws(member)
        asset = await cls.get(db, ws, media_id)
        patch = data.model_dump(exclude_unset=True)
        if patch.get("brand_id"):
            await cls._check_brand(db, ws, patch["brand_id"])
        before = {k: getattr(asset, k) for k in patch}
        for k, v in patch.items():
            setattr(asset, k, list(v or []) if k == "labels" else v)
        await db.flush()
        await db.refresh(asset)
        action = "media.alt_text_update" if set(patch) == {"alt_text"} else "media.update"
        await safe_audit(db, member, action, "media_asset", asset.id, before=_jsonable(before),
                         after=_jsonable({k: getattr(asset, k) for k in patch}))
        return asset

    @classmethod
    async def delete(cls, db: AsyncSession, member: Any, media_id: UUID) -> None:
        """Soft delete (objects stay until maintenance purges unreferenced files)."""
        asset = await cls.get(db, _ws(member), media_id)
        asset.deleted_at = datetime.now(UTC)
        await db.flush()
        await safe_audit(db, member, "media.delete", "media_asset", asset.id,
                         before={"object_key": asset.object_key, "kind": asset.kind})

    # ------------------------------------------------------------ URLs
    @classmethod
    async def presigned_get_url(cls, asset: MediaAsset, expires_s: int = PRESIGN_GET_TTL_S) -> str:
        return await storage.presign_get(asset.bucket, asset.object_key, expires_s)

    @classmethod
    async def public_url(cls, asset: MediaAsset, expires_s: int = PRESIGN_GET_TTL_S) -> tuple[str, bool]:
        """(url, is_public): PUBLIC_MEDIA_BASE_URL when configured (platforms fetch by URL), else a presigned GET."""
        pub = storage.public_url(asset.bucket, asset.object_key)
        if pub:
            return pub, True
        return await cls.presigned_get_url(asset, expires_s), False

    @classmethod
    async def urls_for(cls, assets: list[MediaAsset], expires_s: int = PRESIGN_GET_TTL_S) -> dict[UUID, str]:
        """Batch URLs with a single S3 client (list views)."""
        out: dict[UUID, str] = {}
        pending = []
        for a in assets:
            pub = storage.public_url(a.bucket, a.object_key)
            if pub:
                out[a.id] = pub
            else:
                pending.append(a)
        if not pending:
            return out
        try:
            from app.integrations.storage.s3 import _client
            async with _client() as c:  # pyright: ignore[reportGeneralTypeIssues]
                for a in pending:
                    out[a.id] = await c.generate_presigned_url("get_object", Params={"Bucket": a.bucket,
                                                                                     "Key": a.object_key},
                                                               ExpiresIn=expires_s)
        except Exception as e:
            log.warning("media.batch_presign_failed", error=str(e))
            for a in pending:
                try:
                    out[a.id] = await cls.presigned_get_url(a, expires_s)
                except Exception:
                    continue
        return out

    # ------------------------------------------------------------ helpers
    @classmethod
    async def _check_brand(cls, db: AsyncSession, workspace_id: UUID, brand_id: UUID) -> Brand:
        brand = (await db.execute(select(Brand).where(Brand.id == brand_id, Brand.workspace_id == workspace_id,
                                                      Brand.deleted_at.is_(None)))).scalar_one_or_none()
        if brand is None:
            raise not_found("Brand")
        return brand

    @classmethod
    async def _brand_visual(cls, db: AsyncSession, workspace_id: UUID, brand_id: UUID | None) -> dict[str, Any]:
        if not brand_id:
            return {}
        visual = (await db.execute(select(BrandSettings.visual).where(BrandSettings.brand_id == brand_id,
                                                                       BrandSettings.workspace_id == workspace_id))
                  ).scalar_one_or_none()
        return visual or {}

    @staticmethod
    def _event_payload(asset: MediaAsset, **extra: Any) -> dict[str, Any]:
        return {"media_id": str(asset.id), "brand_id": str(asset.brand_id) if asset.brand_id else None,
                "kind": asset.kind, "source": asset.source, "mime": asset.mime,
                "derived_from_id": str(asset.derived_from_id) if asset.derived_from_id else None,
                "platform": asset.platform_target, **extra}

    @classmethod
    async def _existing_rendition(cls, db: AsyncSession, asset: MediaAsset, transform_key: str) -> MediaAsset | None:
        stmt = (select(MediaAsset)
                .where(MediaAsset.workspace_id == asset.workspace_id, MediaAsset.derived_from_id == asset.id,
                       MediaAsset.deleted_at.is_(None), MediaAsset.transform["key"].astext == transform_key)
                .order_by(MediaAsset.created_at.desc()).limit(1))
        return (await db.execute(stmt)).scalar_one_or_none()

    # ------------------------------------------------------------ platform transforms
    @classmethod
    async def transform_for_platform(cls, db: AsyncSession, member: Any, media_id: UUID, platform: str, fmt: str, *,
                                     aspect: str | None = None, pad_color: str | None = None,
                                     focus: str = "saliency") -> MediaAsset:
        """Produce (or reuse) a platform rendition that satisfies `platform_specs` for (platform, format)."""
        ws = _ws(member)
        platform = str(getattr(platform, "value", platform))
        fmt = str(getattr(fmt, "value", fmt))
        asset = await cls.get(db, ws, media_id)
        if asset.kind not in ("image", "video"):
            raise ProblemError(422, "unsupported_media_kind", "Only images and videos have platform renditions")
        try:
            spec = specs.get_spec(platform, fmt, asset.kind)
        except KeyError as e:
            raise ProblemError(422, "unsupported_platform_format", "Unsupported platform/format", str(e).strip("'")) from e
        if pad_color:
            try:
                imgp.parse_color(pad_color)
            except ValueError as e:
                raise validation("pad_color must be a hex color like #0B2545") from e
            pad = pad_color
        else:
            colors = (await cls._brand_visual(db, ws, asset.brand_id)).get("colors") or {}
            pad = str(colors.get("primary") or ("#000000" if asset.kind == "video" else "#FFFFFF"))
        target_override: float | None = None
        if aspect:
            try:
                target_override = specs.parse_aspect(aspect)
            except ValueError as e:
                raise validation(f"Invalid aspect '{aspect}'") from e
            if not specs.aspect_allowed(target_override, spec):
                raise ProblemError(422, "aspect_not_allowed", "Aspect ratio not allowed",
                                   f"{aspect} is outside {platform}/{fmt} limits "
                                   f"({spec.min_aspect or '-'}–{spec.max_aspect or '-'})")
        tkey = f"{platform}:{fmt}:{aspect or ''}:{pad.upper()}"
        existing = await cls._existing_rendition(db, asset, tkey)
        if existing is not None:
            return existing
        if asset.kind == "image":
            rendition = await cls._transform_image(db, asset, spec, platform, fmt, tkey, target_override, pad, focus,
                                                   created_by=actor_user_id(member))
        else:
            rendition = await cls._transform_video(db, asset, spec, platform, fmt, tkey, target_override, pad,
                                                   created_by=actor_user_id(member))
        await emit(db, "MEDIA_PROCESSED", cls._event_payload(rendition, step="transform", format=fmt),
                   workspace_id=ws, actor=actor_dict(member))
        await safe_audit(db, member, "media.transform", "media_asset", rendition.id,
                         after={"derived_from_id": str(asset.id), "platform": platform, "format": fmt,
                                "transform": rendition.transform})
        return rendition

    @classmethod
    async def _transform_image(cls, db: AsyncSession, asset: MediaAsset, spec: specs.MediaSpec, platform: str, fmt: str,
                               tkey: str, target_override: float | None, pad_color: str, focus: str, *,
                               created_by: UUID | None) -> MediaAsset:
        data = await storage.get(asset.bucket, asset.object_key)

        def work() -> tuple[bytes, str, int, int, dict[str, Any]]:
            img = imgp.open_image(data)
            w, h = img.size
            src_aspect = w / h
            target = target_override or specs.clamp_aspect(src_aspect, spec)
            ops: dict[str, Any] = {"source_size": [w, h], "target_aspect": round(target, 4)}
            if abs(target - src_aspect) / target > 0.005:
                img = imgp.smart_crop_to_aspect(img, target, pad_color=pad_color, max_crop=0.2,
                                                focus="saliency" if focus == "saliency" else "center")
                ops["crop_pad"] = True
            long_cap = max(spec.recommended_size) if spec.recommended_size else 2048
            cw, ch = img.size
            if max(cw, ch) > long_cap:
                img = imgp.resize_fit(img, long_cap, long_cap)
            img = imgp.fit_bounds(img, min_width=spec.min_width, min_height=spec.min_height, max_width=spec.max_width,
                                  max_height=spec.max_height, max_pixels=spec.max_pixels)
            out_mime = asset.mime if asset.mime in spec.mimes and asset.mime != "image/gif" else spec.preferred_mime
            fmt_name = imgp.MIME_FORMAT.get(out_mime, "JPEG")
            if fmt_name == "GIF":
                fmt_name, out_mime = "PNG", "image/png"
            out = imgp.encode(img, cast(imgp.OutFormat, fmt_name), quality=90, max_bytes=spec.max_bytes,
                              background=pad_color)
            with Image.open(io.BytesIO(out)) as chk:
                ow, oh = chk.size
            ops["output_size"] = [ow, oh]
            return out, out_mime, ow, oh, ops

        out, out_mime, ow, oh, ops = await asyncio.to_thread(work)
        transform = {"op": "platform_transform", "key": tkey, "platform": platform, "format": fmt,
                     "pad_color": pad_color, "spec": {"min_aspect": spec.min_aspect, "max_aspect": spec.max_aspect,
                                                      "max_bytes": spec.max_bytes, "mimes": list(spec.mimes)},
                     "verified_at": specs.VERIFIED_AT, **ops}
        return await cls.upload_bytes(db, workspace_id=asset.workspace_id, data=out, kind="image", source="derived",
                                      mime=out_mime, process=False, brand_id=asset.brand_id, created_by=created_by,
                                      width=ow, height=oh, derived_from_id=asset.id, transform=transform,
                                      platform_target=platform, alt_text=asset.alt_text, ai_generated=asset.ai_generated,
                                      labels=list(asset.labels or []), provider=asset.provider, model=asset.model)

    @classmethod
    async def _transform_video(cls, db: AsyncSession, asset: MediaAsset, spec: specs.MediaSpec, platform: str, fmt: str,
                               tkey: str, target_override: float | None, pad_color: str, *,
                               created_by: UUID | None) -> MediaAsset:
        vidp.require_ffmpeg()
        data = await storage.get(asset.bucket, asset.object_key)
        info = await vidp.probe(data)
        if not info.width or not info.height:
            raise ProblemError(422, "invalid_video", "Invalid video", "No video stream found")
        dur_s = (info.duration_ms or 0) / 1000
        if spec.min_duration_s and dur_s and dur_s < spec.min_duration_s:
            raise ProblemError(422, "video_too_short", "Video too short",
                               f"{platform}/{fmt} requires at least {spec.min_duration_s:g}s (got {dur_s:.1f}s)")
        src_aspect = info.width / info.height
        target = target_override or specs.clamp_aspect(src_aspect, spec)
        rec = spec.recommended_size
        if rec and abs(target - rec[0] / rec[1]) / target < 0.01:
            tw, th = rec
        else:
            tw = min(info.width, spec.max_width or info.width, 1920)
            th = round(tw / target)
            if spec.max_height and th > spec.max_height:
                th = spec.max_height
                tw = round(th * target)
        tw, th = max(2, tw // 2 * 2), max(2, th // 2 * 2)
        crop_frac = abs(1 - min(src_aspect, target) / max(src_aspect, target))
        fit = "crop" if crop_frac <= 0.2 else "pad"
        fps = None
        if info.fps and spec.max_fps and info.fps > spec.max_fps + 0.5:
            fps = spec.max_fps
        elif info.fps and spec.min_fps and info.fps < spec.min_fps - 0.5:
            fps = spec.min_fps
        max_dur = spec.max_duration_s if spec.max_duration_s and dur_s > spec.max_duration_s else None
        out = b""
        for crf in (23, 28, 33):
            out = await vidp.transcode(data, width=tw, height=th, pad_color=pad_color, fit=fit, fps=fps,
                                       max_duration_s=max_dur, crf=crf)
            if not spec.max_bytes or len(out) <= spec.max_bytes:
                break
        else:
            raise ProblemError(422, "video_too_large", "Rendition exceeds the platform size limit",
                               f"{len(out)} bytes > {spec.max_bytes}")
        oinfo = await vidp.probe(out)
        transform = {"op": "platform_transform", "key": tkey, "platform": platform, "format": fmt, "fit": fit,
                     "pad_color": pad_color, "target_size": [tw, th], "fps": fps, "trimmed_to_s": max_dur,
                     "source": info.as_dict(), "verified_at": specs.VERIFIED_AT}
        return await cls.upload_bytes(db, workspace_id=asset.workspace_id, data=out, kind="video", source="derived",
                                      mime="video/mp4", process=False, brand_id=asset.brand_id, created_by=created_by,
                                      width=oinfo.width, height=oinfo.height, duration_ms=oinfo.duration_ms,
                                      fps=oinfo.fps, codec=oinfo.codec, derived_from_id=asset.id, transform=transform,
                                      platform_target=platform, alt_text=asset.alt_text,
                                      ai_generated=asset.ai_generated, labels=list(asset.labels or []))

    @classmethod
    def needs_async(cls, asset: MediaAsset) -> bool:
        """The API never transcodes video inline (doc 10 §10.1)."""
        return asset.kind == "video"

    @classmethod
    async def enqueue_transform(cls, member: Any, media_id: UUID, platform: str, fmt: str, *, aspect: str | None = None,
                                pad_color: str | None = None) -> int | None:
        platform = str(getattr(platform, "value", platform))
        fmt = str(getattr(fmt, "value", fmt))
        uid = actor_user_id(member)
        return await defer_media_job("jobs.media.transform", f"media-transform:{media_id}:{platform}:{fmt}",
                                     media_id=str(media_id), workspace_id=str(_ws(member)), platform=platform,
                                     format=fmt, aspect=aspect, pad_color=pad_color,
                                     user_id=str(uid) if uid else None)

    # ------------------------------------------------------------ background removal
    @classmethod
    async def remove_background(cls, db: AsyncSession, member: Any, media_id: UUID) -> MediaAsset:
        try:
            from rembg import remove as rembg_remove  # type: ignore[import-not-found]
        except ImportError as e:
            raise ProblemError(501, "rembg_not_installed", "Background removal is not available",
                               "Install the optional `rembg` package on the media worker.") from e
        ws = _ws(member)
        asset = await cls.get(db, ws, media_id)
        if asset.kind != "image":
            raise ProblemError(422, "unsupported_media_kind", "Background removal works on images only")
        existing = await cls._existing_rendition(db, asset, "remove_background")
        if existing is not None:
            return existing
        data = await storage.get(asset.bucket, asset.object_key)
        out = await asyncio.to_thread(rembg_remove, data)
        if not isinstance(out, (bytes, bytearray)):
            buf = io.BytesIO()
            out.save(buf, "PNG")
            out = buf.getvalue()
        enc = await asyncio.to_thread(imgp.reencode, bytes(out), "PNG")
        rendition = await cls.upload_bytes(db, workspace_id=ws, data=enc.data, kind="image", source="derived",
                                           mime=enc.mime, process=False, width=enc.width, height=enc.height,
                                           brand_id=asset.brand_id, created_by=actor_user_id(member),
                                           derived_from_id=asset.id, alt_text=asset.alt_text,
                                           ai_generated=asset.ai_generated,
                                           labels=list(dict.fromkeys([*(asset.labels or []), "background_removed"])),
                                           transform={"op": "remove_background", "key": "remove_background"})
        await emit(db, "MEDIA_PROCESSED", cls._event_payload(rendition, step="remove_background"), workspace_id=ws,
                   actor=actor_dict(member))
        await safe_audit(db, member, "media.remove_background", "media_asset", rendition.id,
                         after={"derived_from_id": str(asset.id)})
        return rendition

    # ------------------------------------------------------------ generation
    @classmethod
    async def generate_image(cls, db: AsyncSession, member: Any, brand_id: UUID | None, prompt: str,
                             provider: str | None = None, size: str = "1024x1024", n: int = 1, *,
                             negative_prompt: str | None = None, style: str | None = None, quality: str | None = None,
                             reference_asset_ids: list[UUID] | None = None, ai_run_id: UUID | None = None,
                             alt_text: str | None = None) -> list[MediaAsset]:
        """Generate n images with the workspace's ImageProvider chain (explicit provider disables fallback).
        SPEND-class: records usage_ledger(kind=media) per image and emits MEDIA_GENERATED per asset."""
        ws = _ws(member)
        prompt = (prompt or "").strip()
        if not prompt:
            raise validation("prompt is required")
        if len(prompt) > 4000:
            raise validation("prompt is limited to 4000 characters")
        if not 1 <= n <= 4:
            raise validation("n must be between 1 and 4")
        try:
            parse_size(size)
        except ValueError as e:
            raise validation(str(e)) from e
        if brand_id:
            await cls._check_brand(db, ws, brand_id)
        await cls._check_daily_limit(db, ws, n)
        refs: list[bytes] = []
        for rid in reference_asset_ids or []:
            ref = await cls.get(db, ws, rid)
            if ref.kind == "image":
                refs.append(await storage.get(ref.bucket, ref.object_key))
        chain = await get_workspace_image_providers(db, ws, provider)
        images: list[GeneratedImage] = []
        used = chain[0]
        errors: list[str] = []
        for prov in chain:
            try:
                images = await prov.generate(prompt, negative_prompt=negative_prompt, size=size, n=n, style=style,
                                             quality=quality, reference_images=refs or None)
                used = prov
                break
            except ImageProviderError as e:
                if e.refused:
                    raise ProblemError(422, "provider_refused", "The image provider declined this prompt", str(e)) from e
                errors.append(f"{prov.name}: {e}")
                log.warning("media.provider_failed", provider=prov.name, error=str(e))
            except Exception as e:
                errors.append(f"{prov.name}: {e}")
                log.warning("media.provider_failed", provider=prov.name, error=str(e))
        if not images:
            raise ProblemError(502, "image_generation_failed", "Image generation failed", "; ".join(errors)[:1000])
        assets: list[MediaAsset] = []
        uid = actor_user_id(member)
        total_cost = 0.0
        for img in images:
            params = {"size": size, "n": n, "negative_prompt": negative_prompt, "style": style, "quality": quality,
                      "revised_prompt": img.revised_prompt, "cost_usd": img.cost_usd,
                      "reference_asset_ids": [str(r) for r in reference_asset_ids or []],
                      "ai_run_id": str(ai_run_id) if ai_run_id else None}
            asset = await cls.upload_bytes(db, workspace_id=ws, data=img.data, kind="image", source="generated",
                                           brand_id=brand_id, created_by=uid, ai_generated=True, provider=used.name,
                                           model=img.model or used.model, prompt=prompt, seed=img.seed,
                                           generation_params={k: v for k, v in params.items() if v is not None},
                                           labels=["ai_generated"], alt_text=alt_text)
            total_cost += img.cost_usd
            db.add(UsageLedger(workspace_id=ws, kind="media", provider=used.name, model=img.model or used.model,
                               quantity=1, cost_usd=img.cost_usd, ref_type="media_asset", ref_id=asset.id))
            await emit(db, "MEDIA_GENERATED", {**cls._event_payload(asset), "provider": used.name,
                                               "model": asset.model, "ai_run_id": str(ai_run_id) if ai_run_id else None},
                       workspace_id=ws, actor=actor_dict(member))
            assets.append(asset)
        await db.flush()
        await safe_audit(db, member, "media.generate", "media_asset", assets[0].id,
                         after={"provider": used.name, "model": assets[0].model, "n": len(assets),
                                "prompt_sha256": hashlib.sha256(prompt.encode()).hexdigest(),
                                "cost_usd": round(total_cost, 6), "media_ids": [str(a.id) for a in assets]})
        return assets

    @classmethod
    async def _check_daily_limit(cls, db: AsyncSession, workspace_id: UUID, n: int) -> None:
        """`ai_settings.media.max_generations_per_day` (counted from usage_ledger kind=media, UTC day)."""
        limit = (await workspace_media_settings(db, workspace_id)).get("max_generations_per_day")
        if not limit:
            return
        start = datetime.now(UTC).replace(hour=0, minute=0, second=0, microsecond=0)
        used = (await db.execute(select(func.coalesce(func.sum(UsageLedger.quantity), 0))
                                 .where(UsageLedger.workspace_id == workspace_id, UsageLedger.kind == "media",
                                        UsageLedger.occurred_at >= start))).scalar() or 0
        if float(used) + n > float(limit):
            raise ProblemError(429, "media_generation_limit", "Daily image generation limit reached",
                               f"{int(float(used))}/{int(float(limit))} generations used today (Settings → AI → media)")

    @classmethod
    async def edit_image(cls, db: AsyncSession, member: Any, media_id: UUID, prompt: str, *,
                         provider: str | None = None, mask_asset_id: UUID | None = None, n: int = 1,
                         size: str | None = None, ai_run_id: UUID | None = None) -> list[MediaAsset]:
        """Prompted edit of an existing image (provider `edit`) → new generated assets derived from it. SPEND-class."""
        ws = _ws(member)
        prompt = (prompt or "").strip()
        if not prompt or len(prompt) > 4000:
            raise validation("prompt is required (≤ 4000 characters)")
        if not 1 <= n <= 4:
            raise validation("n must be between 1 and 4")
        src = await cls.get(db, ws, media_id)
        if src.kind != "image":
            raise ProblemError(422, "unsupported_media_kind", "Only images can be edited")
        await cls._check_daily_limit(db, ws, n)
        image = await storage.get(src.bucket, src.object_key)
        if src.mime != "image/png":  # edit endpoints expect PNG
            image = (await asyncio.to_thread(imgp.reencode, image, "PNG")).data
        mask = None
        if mask_asset_id:
            m = await cls.get(db, ws, mask_asset_id)
            mask = (await asyncio.to_thread(imgp.reencode, await storage.get(m.bucket, m.object_key), "PNG")).data
        size = size or (f"{src.width}x{src.height}" if src.width and src.height else "1024x1024")
        chain = await get_workspace_image_providers(db, ws, provider)
        images: list[GeneratedImage] = []
        used = chain[0]
        errors: list[str] = []
        for prov in chain:
            try:
                images = await prov.edit(image, prompt, mask=mask, size=size, n=n)
                used = prov
                break
            except ImageProviderError as e:
                if e.refused:
                    raise ProblemError(422, "provider_refused", "The image provider declined this prompt", str(e)) from e
                errors.append(f"{prov.name}: {e}")
            except Exception as e:
                errors.append(f"{prov.name}: {e}")
        if not images:
            raise ProblemError(502, "image_edit_failed", "Image edit failed", "; ".join(errors)[:1000])
        uid = actor_user_id(member)
        assets: list[MediaAsset] = []
        for img in images:
            asset = await cls.upload_bytes(
                db, workspace_id=ws, data=img.data, kind="image", source="generated", brand_id=src.brand_id,
                created_by=uid, ai_generated=True, provider=used.name, model=img.model or used.model, prompt=prompt,
                seed=img.seed, derived_from_id=src.id, labels=["ai_generated", "ai_edited"],
                transform={"op": "ai_edit", "mask_asset_id": str(mask_asset_id) if mask_asset_id else None},
                generation_params={"size": size, "n": n, "cost_usd": img.cost_usd,
                                   "ai_run_id": str(ai_run_id) if ai_run_id else None})
            db.add(UsageLedger(workspace_id=ws, kind="media", provider=used.name, model=asset.model, quantity=1,
                               cost_usd=img.cost_usd, ref_type="media_asset", ref_id=asset.id))
            await emit(db, "MEDIA_GENERATED", {**cls._event_payload(asset), "provider": used.name, "model": asset.model,
                                               "edit_of": str(src.id)}, workspace_id=ws, actor=actor_dict(member))
            assets.append(asset)
        await db.flush()
        await safe_audit(db, member, "media.edit", "media_asset", assets[0].id,
                         after={"source_id": str(src.id), "provider": used.name, "n": len(assets),
                                "prompt_sha256": hashlib.sha256(prompt.encode()).hexdigest(),
                                "cost_usd": round(sum(i.cost_usd for i in images), 6)})
        return assets

    # ------------------------------------------------------------ carousel
    @classmethod
    async def compose_carousel(cls, db: AsyncSession, member: Any, brand_id: UUID | None, slides: list[dict[str, Any]],
                               template: dict[str, Any] | None = None, *, with_pdf: bool = False) -> list[MediaAsset]:
        """Render slides (1080×1350) with brand colors → one image asset per slide sharing a carousel_group_id
        (+ an optional PDF `document` asset for LinkedIn document posts, position = len(slides))."""
        ws = _ws(member)
        if not slides or len(slides) > 20:
            raise validation("A carousel needs 1–20 slides")
        if brand_id:
            await cls._check_brand(db, ws, brand_id)
        visual = await cls._brand_visual(db, ws, brand_id)
        tpl = {"colors": visual.get("colors") or {}, "fonts": visual.get("fonts") or {}, **(template or {})}
        pngs = await asyncio.to_thread(compose_slides, slides, tpl)
        group = new_id()
        uid = actor_user_id(member)
        assets: list[MediaAsset] = []
        for i, png in enumerate(pngs):
            assets.append(await cls.upload_bytes(
                db, workspace_id=ws, data=png, kind="image", source="generated", mime="image/png", process=False,
                brand_id=brand_id, created_by=uid, carousel_group_id=group, position=i, labels=["carousel"],
                caption=str(slides[i].get("headline") or "")[:2200] or None,
                transform={"op": "compose_carousel", "template": {"colors": tpl.get("colors"), "fonts": tpl.get("fonts")}}))
        if with_pdf:
            pdf = await asyncio.to_thread(slides_to_pdf, pngs)
            assets.append(await cls.upload_bytes(db, workspace_id=ws, data=pdf, kind="document", source="generated",
                                                 mime="application/pdf", process=False, brand_id=brand_id,
                                                 created_by=uid, carousel_group_id=group, position=len(pngs),
                                                 labels=["carousel", "document"], transform={"op": "carousel_pdf"}))
        for a in assets:
            await emit(db, "MEDIA_GENERATED", {**cls._event_payload(a), "carousel_group_id": str(group),
                                               "position": a.position}, workspace_id=ws, actor=actor_dict(member))
        await safe_audit(db, member, "media.compose_carousel", "media_asset", assets[0].id,
                         after={"carousel_group_id": str(group), "slides": len(pngs), "pdf": with_pdf})
        return assets

    # ------------------------------------------------------------ attach to content
    @classmethod
    async def attach_to_content(cls, db: AsyncSession, member: Any, media_id: UUID, *, variant_id: UUID | None = None,
                                content_item_id: UUID | None = None, role: str = "primary", position: int | None = None,
                                alt_text: str | None = None) -> ContentAsset:
        ws = _ws(member)
        if role not in CONTENT_ASSET_ROLES:
            raise validation(f"role must be one of {', '.join(sorted(CONTENT_ASSET_ROLES))}")
        if not variant_id and not content_item_id:
            raise validation("variant_id or content_item_id is required")
        media = await cls.get(db, ws, media_id)
        if variant_id:
            variant = (await db.execute(select(ContentVariant).where(ContentVariant.id == variant_id,
                                                                     ContentVariant.workspace_id == ws))
                       ).scalar_one_or_none()
            if variant is None:
                raise not_found("Content variant")
            if content_item_id and content_item_id != variant.content_item_id:
                raise validation("variant does not belong to content_item_id")
            content_item_id = variant.content_item_id
        else:
            item = (await db.execute(select(ContentItem.id).where(ContentItem.id == content_item_id,
                                                                  ContentItem.workspace_id == ws,
                                                                  ContentItem.deleted_at.is_(None)))).first()
            if item is None:
                raise not_found("Content item")
        scope = ContentAsset.variant_id == variant_id if variant_id else (
            (ContentAsset.content_item_id == content_item_id) & ContentAsset.variant_id.is_(None))
        dup = (await db.execute(select(ContentAsset).where(ContentAsset.workspace_id == ws, scope,
                                                           ContentAsset.media_asset_id == media.id,
                                                           ContentAsset.role == role))).scalar_one_or_none()
        if dup is not None:
            if alt_text and dup.alt_text != alt_text:
                dup.alt_text = alt_text
                await db.flush()
            return dup
        content_service: Any = None
        try:  # the content module owns content_assets rules (editability lock, variant re-validation, audit)
            from app.services.content_service import ContentService as content_service
        except ImportError:
            pass
        if content_service is not None and hasattr(content_service, "attach_asset"):
            ca = await content_service.attach_asset(db, member, content_item_id, media.id, variant_id=variant_id,
                                                    role=role, position=position, alt_text=alt_text)
        else:
            if position is None:
                max_pos = (await db.execute(select(func.max(ContentAsset.position))
                                            .where(ContentAsset.workspace_id == ws, scope))).scalar()
                position = 0 if max_pos is None else int(max_pos) + 1
            ca = ContentAsset(workspace_id=ws, content_item_id=content_item_id, variant_id=variant_id,
                              media_asset_id=media.id, role=role, position=position, alt_text=alt_text or media.alt_text)
            db.add(ca)
            await db.flush()
            await db.refresh(ca)
            await safe_audit(db, member, "content_asset.attach", "content_asset", ca.id,
                             after={"media_id": str(media.id), "content_item_id": str(content_item_id),
                                    "variant_id": str(variant_id) if variant_id else None, "role": role,
                                    "position": position})
        await emit(db, "CONTENT_UPDATED", {"content_id": str(content_item_id),
                                           "variant_id": str(variant_id) if variant_id else None,
                                           "change": "asset_attached", "media_id": str(media.id), "role": role,
                                           "position": ca.position}, workspace_id=ws, actor=actor_dict(member))
        return ca

    list = list_media  # public alias per spec (`MediaService.list`)


def _jsonable(d: dict[str, Any]) -> dict[str, Any]:
    return {k: (str(v) if isinstance(v, UUID) else list(v) if isinstance(v, tuple) else v) for k, v in d.items()}


async def defer_media_job(task_name: str, queueing_lock: str | None = None, **kwargs: Any) -> int | None:
    """Enqueue a job on the `media` queue; opens the Procrastinate app on demand (API process)."""
    from procrastinate import exceptions as pexc

    from app.workers.app import procrastinate_app
    deferrer = procrastinate_app.configure_task(name=task_name, queue="media", queueing_lock=queueing_lock)
    try:
        try:
            return await deferrer.defer_async(**kwargs)
        except pexc.AppNotOpen:
            async with procrastinate_app.open_async():
                return await deferrer.defer_async(**kwargs)
    except pexc.AlreadyEnqueued:
        log.info("media.job_already_enqueued", task=task_name, lock=queueing_lock)
        return None


media_service = MediaService()

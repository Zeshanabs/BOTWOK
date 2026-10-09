"""Image pipeline (Pillow): validate, re-encode (strip EXIF/metadata, sRGB), resize, crop/pad to aspect, thumbnail.

Every uploaded or generated image is re-encoded (defeats polyglot files, strips EXIF/GPS) — doc 10 §10.7.
"""
from __future__ import annotations

import hashlib
import io
from dataclasses import dataclass
from typing import Any, Literal

import numpy as np
from PIL import Image, ImageFilter, ImageOps, ImageSequence, UnidentifiedImageError

from app.core.errors import ProblemError

FORMAT_MIME = {"JPEG": "image/jpeg", "PNG": "image/png", "WEBP": "image/webp", "GIF": "image/gif"}
MIME_FORMAT = {v: k for k, v in FORMAT_MIME.items()}
MIME_EXT = {"image/jpeg": "jpg", "image/png": "png", "image/webp": "webp", "image/gif": "gif"}
ALLOWED_IMAGE_MIMES = frozenset(FORMAT_MIME.values())
MAX_IMAGE_BYTES = 50 * 1024 * 1024
MAX_PIXELS = 80_000_000
OutFormat = Literal["JPEG", "PNG", "WEBP", "GIF"]


@dataclass(frozen=True)
class EncodedImage:
    data: bytes
    mime: str
    width: int
    height: int

    @property
    def ext(self) -> str:
        return MIME_EXT.get(self.mime, "bin")

    @property
    def sha256(self) -> str:
        return sha256_hex(self.data)


def sha256_hex(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _invalid(detail: str) -> ProblemError:
    return ProblemError(422, "invalid_image", "Invalid image", detail)


def parse_color(value: str | tuple[int, ...] | None, default: tuple[int, int, int] = (255, 255, 255)) -> tuple[int, int, int]:
    if value is None:
        return default
    if isinstance(value, tuple):
        return (int(value[0]), int(value[1]), int(value[2]))
    s = value.strip().lstrip("#")
    if len(s) in (3, 4):
        s = "".join(c * 2 for c in s[:3])
    if len(s) not in (6, 8):
        raise ValueError(f"invalid color {value!r}")
    return (int(s[0:2], 16), int(s[2:4], 16), int(s[4:6], 16))


def has_alpha(img: Image.Image) -> bool:
    return img.mode in ("RGBA", "LA", "PA") or (img.mode == "P" and "transparency" in img.info)


def validate_image(data: bytes, *, max_bytes: int | None = MAX_IMAGE_BYTES, max_pixels: int = MAX_PIXELS) -> dict[str, Any]:
    """Magic-byte + decode validation. Returns {mime, width, height, sha256, format, mode, has_alpha, animated, frames, bytes}."""
    if not data:
        raise _invalid("Empty file")
    if max_bytes is not None and len(data) > max_bytes:
        raise ProblemError(413, "file_too_large", "File too large", f"Image exceeds {max_bytes // (1024 * 1024)} MB")
    try:
        with Image.open(io.BytesIO(data)) as im:
            fmt = im.format
            if fmt not in FORMAT_MIME:
                raise _invalid(f"Unsupported image format {fmt!r} (allowed: JPEG, PNG, WEBP, GIF)")
            width, height = im.size
            if width < 1 or height < 1 or width * height > max_pixels:
                raise _invalid(f"Image dimensions {width}x{height} not allowed")
            mode = im.mode
            frames = int(getattr(im, "n_frames", 1) or 1)
            alpha = has_alpha(im)
            im.verify()
        with Image.open(io.BytesIO(data)) as im:  # verify() leaves the image unusable; fully decode to catch truncation
            im.load()
    except ProblemError:
        raise
    except (UnidentifiedImageError, OSError, SyntaxError, ValueError, Image.DecompressionBombError) as e:
        raise _invalid(f"Not a valid image: {e}") from e
    return {"mime": FORMAT_MIME[fmt], "width": width, "height": height, "sha256": sha256_hex(data), "format": fmt,
            "mode": mode, "has_alpha": alpha, "animated": frames > 1, "frames": frames, "bytes": len(data)}


def open_image(data: bytes | Image.Image) -> Image.Image:
    """Decode, apply EXIF orientation, convert to sRGB; returns a detached, fully-loaded image."""
    if isinstance(data, Image.Image):
        return data
    try:
        im = Image.open(io.BytesIO(data))
        im.load()
    except (UnidentifiedImageError, OSError, SyntaxError, ValueError, Image.DecompressionBombError) as e:
        raise _invalid(f"Not a valid image: {e}") from e
    im = ImageOps.exif_transpose(im) or im
    return to_srgb(im)


def to_srgb(img: Image.Image) -> Image.Image:
    icc = img.info.get("icc_profile")
    if icc and img.mode in ("RGB", "RGBA", "CMYK"):
        try:
            from PIL import ImageCms
            src = ImageCms.ImageCmsProfile(io.BytesIO(icc))
            dst = ImageCms.createProfile("sRGB")
            out_mode = "RGBA" if img.mode == "RGBA" else "RGB"
            converted = ImageCms.profileToProfile(img, src, dst, outputMode=out_mode)
            if converted is not None:
                img = converted
        except Exception:  # broken/unsupported profile: keep pixels, drop profile
            pass
    elif img.mode == "CMYK":
        img = img.convert("RGB")
    img.info = {k: v for k, v in img.info.items() if k == "transparency"}
    return img


def _normalize_mode(img: Image.Image) -> Image.Image:
    if img.mode in ("RGB", "RGBA"):
        return img
    return img.convert("RGBA" if has_alpha(img) else "RGB")


def flatten(img: Image.Image, background: str | tuple[int, int, int] = "#FFFFFF") -> Image.Image:
    img = _normalize_mode(img)
    if img.mode != "RGBA":
        return img
    bg = Image.new("RGB", img.size, parse_color(background))
    bg.paste(img, mask=img.getchannel("A"))
    return bg


def encode(img: Image.Image, fmt: OutFormat = "JPEG", *, quality: int = 90, max_bytes: int | None = None,
           background: str = "#FFFFFF") -> bytes:
    """Encode without any metadata (no EXIF/XMP/ICC). JPEG flattens alpha onto `background`.
    With `max_bytes`, JPEG/WEBP lower quality first, then all formats downscale until the file fits."""
    work = flatten(img, background) if fmt == "JPEG" else _normalize_mode(img)
    work.info = {}
    q = quality
    for _ in range(24):
        buf = io.BytesIO()
        if fmt == "JPEG":
            work.save(buf, "JPEG", quality=q, optimize=True, progressive=True, subsampling=0 if q >= 90 else 2)
        elif fmt == "PNG":
            work.save(buf, "PNG", optimize=True)
        elif fmt == "WEBP":
            work.save(buf, "WEBP", quality=q, method=4)
        elif fmt == "GIF":
            work.save(buf, "GIF", optimize=True)
        else:
            raise ValueError(f"unsupported output format {fmt}")
        out = buf.getvalue()
        if max_bytes is None or len(out) <= max_bytes:
            return out
        if fmt in ("JPEG", "WEBP") and q > 60:
            q -= 8
            continue
        w, h = work.size
        if w <= 64 or h <= 64:
            break
        work = work.resize((max(1, int(w * 0.85)), max(1, int(h * 0.85))), Image.Resampling.LANCZOS)
    raise ProblemError(422, "image_too_large", "Image cannot be compressed under the size limit",
                       f"Could not encode under {max_bytes} bytes")


def reencode(data: bytes, fmt: OutFormat | None = None, *, quality: int = 90,
             max_bytes: int | None = None) -> EncodedImage:
    """Strip all metadata and re-encode. Default: PNG when the image has transparency, else JPEG.
    Animated GIFs stay animated GIFs unless another format is requested (then the first frame is used)."""
    try:
        src = Image.open(io.BytesIO(data))
    except (UnidentifiedImageError, OSError, SyntaxError, ValueError, Image.DecompressionBombError) as e:
        raise _invalid(f"Not a valid image: {e}") from e
    if src.format == "GIF" and getattr(src, "is_animated", False) and fmt in (None, "GIF"):
        frames, durations = [], []
        for frame in ImageSequence.Iterator(src):
            frames.append(frame.convert("RGBA"))
            durations.append(frame.info.get("duration", 100))
        buf = io.BytesIO()
        frames[0].save(buf, "GIF", save_all=True, append_images=frames[1:], duration=durations,
                       loop=src.info.get("loop", 0), disposal=2, optimize=False)
        out = buf.getvalue()
        return EncodedImage(out, "image/gif", frames[0].width, frames[0].height)
    img = open_image(data)
    if fmt is None:
        fmt = "PNG" if has_alpha(img) else "JPEG"
    out = encode(img, fmt, quality=quality, max_bytes=max_bytes)
    with Image.open(io.BytesIO(out)) as check:
        w, h = check.size
    return EncodedImage(out, FORMAT_MIME[fmt], w, h)


def resize_fit(img: bytes | Image.Image, max_w: int, max_h: int, *, upscale: bool = False) -> Image.Image:
    """Scale to fit inside max_w × max_h, preserving aspect ratio."""
    im = open_image(img)
    w, h = im.size
    scale = min(max_w / w, max_h / h)
    if scale >= 1 and not upscale:
        return im.copy()
    nw, nh = max(1, round(w * scale)), max(1, round(h * scale))
    return im.resize((nw, nh), Image.Resampling.LANCZOS)


def resize_exact(img: Image.Image, width: int, height: int) -> Image.Image:
    return img.resize((width, height), Image.Resampling.LANCZOS) if img.size != (width, height) else img.copy()


def _best_window(profile: np.ndarray, win: int) -> int:
    """Start index of the window with the highest summed energy; center when the profile is flat."""
    center = max(0, (profile.size - win) // 2)
    sums = np.convolve(profile, np.ones(win), mode="valid")
    if sums.size == 0 or float(sums.max() - sums.min()) <= 1e-9 * max(1.0, float(abs(sums.max()))):
        return center
    return int(np.argmax(sums))


def _saliency_offset(img: Image.Image, crop_w: int, crop_h: int) -> tuple[int, int]:
    """Crop window with the most edge energy along the cropped axis (cheap subject heuristic, no ML)."""
    w, h = img.size
    k = min(1.0, 256 / max(w, h))
    sw, sh = max(1, int(w * k)), max(1, int(h * k))
    energy = np.asarray(img.convert("L").resize((sw, sh)).filter(ImageFilter.FIND_EDGES), dtype=np.float64)
    if crop_w < w:
        start = _best_window(energy.sum(axis=0), max(1, int(crop_w * k)))
        return min(w - crop_w, max(0, int(start / k))), (h - crop_h) // 2
    start = _best_window(energy.sum(axis=1), max(1, int(crop_h * k)))
    return (w - crop_w) // 2, min(h - crop_h, max(0, int(start / k)))


def smart_crop_to_aspect(img: bytes | Image.Image, aspect: float, *, pad_color: str | None = "#FFFFFF",
                         max_crop: float = 0.2, focus: Literal["center", "saliency"] = "center") -> Image.Image:
    """Reach `aspect` (w/h) by cropping up to `max_crop` of the long side (centered, or on the most detailed region
    with focus="saliency"); anything still missing is padded with `pad_color` (centered letter/pillar-box).
    max_crop=1.0 → pure crop; max_crop=0 → pure pad."""
    im = _normalize_mode(open_image(img))
    w, h = im.size
    cur = w / h
    if abs(cur - aspect) / aspect < 0.005:
        return im.copy()
    if cur > aspect:   # too wide → crop width, then pad height
        full_crop_w = max(1, round(h * aspect))
        crop_w = full_crop_w if (1 - full_crop_w / w) <= max_crop else max(1, round(w * (1 - max_crop)))
        crop_h = h
    else:              # too tall → crop height, then pad width
        full_crop_h = max(1, round(w / aspect))
        crop_h = full_crop_h if (1 - full_crop_h / h) <= max_crop else max(1, round(h * (1 - max_crop)))
        crop_w = w
    if focus == "saliency":
        x, y = _saliency_offset(im, crop_w, crop_h)
    else:
        x, y = (w - crop_w) // 2, (h - crop_h) // 2
    cropped = im.crop((x, y, x + crop_w, y + crop_h))
    cw, ch = cropped.size
    if abs(cw / ch - aspect) / aspect < 0.005:
        return cropped
    if cw / ch > aspect:
        tw, th = cw, max(ch, round(cw / aspect))
    else:
        tw, th = max(cw, round(ch * aspect)), ch
    rgb = parse_color(pad_color)
    canvas = Image.new(cropped.mode, (tw, th), (*rgb, 255) if cropped.mode == "RGBA" else rgb)
    canvas.paste(cropped, ((tw - cw) // 2, (th - ch) // 2))
    return canvas


def pad_to_aspect(img: bytes | Image.Image, aspect: float, pad_color: str = "#FFFFFF") -> Image.Image:
    return smart_crop_to_aspect(img, aspect, pad_color=pad_color, max_crop=0.0)


def thumbnail(img: bytes | Image.Image, size: int = 512) -> Image.Image:
    im = open_image(img).copy()
    im.thumbnail((size, size), Image.Resampling.LANCZOS)
    return im


def fit_bounds(img: Image.Image, *, min_width: int | None = None, min_height: int | None = None,
               max_width: int | None = None, max_height: int | None = None, max_pixels: int | None = None) -> Image.Image:
    """Scale (down first, then up if required) so the image satisfies the given dimension limits."""
    w, h = img.size
    scale = 1.0
    if max_width and w * scale > max_width:
        scale = max_width / w
    if max_height and h * scale > max_height:
        scale = min(scale, max_height / h)
    if max_pixels and (w * scale) * (h * scale) > max_pixels:
        scale = min(scale, (max_pixels / (w * h)) ** 0.5)
    if min_width and w * scale < min_width:
        scale = max(scale, min_width / w)
    if min_height and h * scale < min_height:
        scale = max(scale, min_height / h)
    if abs(scale - 1.0) < 1e-6:
        return img
    return img.resize((max(1, round(w * scale)), max(1, round(h * scale))), Image.Resampling.LANCZOS)


def solid_png(width: int, height: int, color: str = "#FFFFFF") -> bytes:
    buf = io.BytesIO()
    Image.new("RGB", (width, height), parse_color(color)).save(buf, "PNG")
    return buf.getvalue()

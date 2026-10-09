"""Carousel slide composer (Pillow, no external font files): doc 10 §10.5.

`compose_slides(slides, template)` renders N slides (default 1080×1350, 4:5) with the brand colors, safe margins,
an accent bar, auto-fitted headline/body text and a page counter. Fonts use Pillow's bundled default
(`ImageFont.load_default(size=...)`, Pillow ≥ 10.1); template font *names* are recorded but not loaded.
"""
from __future__ import annotations

import io
from functools import lru_cache
from typing import Any

from PIL import Image, ImageDraw, ImageFont

from app.media.pipelines.image import parse_color

SLIDE_SIZE = (1080, 1350)
FontT = ImageFont.FreeTypeFont | ImageFont.ImageFont


@lru_cache(maxsize=64)
def _font(size: int) -> FontT:
    try:
        return ImageFont.load_default(size=size)
    except TypeError:  # very old Pillow: bitmap font, fixed size
        return ImageFont.load_default()


def _luminance(rgb: tuple[int, int, int]) -> float:
    def ch(c: int) -> float:
        v = c / 255
        return v / 12.92 if v <= 0.03928 else ((v + 0.055) / 1.055) ** 2.4
    r, g, b = (ch(c) for c in rgb)
    return 0.2126 * r + 0.7152 * g + 0.0722 * b


def contrast_text_color(bg: tuple[int, int, int]) -> tuple[int, int, int]:
    return (17, 17, 17) if _luminance(bg) > 0.4 else (255, 255, 255)


def _text_width(draw: ImageDraw.ImageDraw, text: str, font: FontT) -> float:
    return draw.textlength(text, font=font)


def wrap_text(draw: ImageDraw.ImageDraw, text: str, font: FontT, max_width: int) -> list[str]:
    lines: list[str] = []
    for paragraph in (text or "").split("\n"):
        words = paragraph.split()
        if not words:
            lines.append("")
            continue
        cur = ""
        for word in words:
            candidate = f"{cur} {word}".strip()
            if _text_width(draw, candidate, font) <= max_width:
                cur = candidate
                continue
            if cur:
                lines.append(cur)
            # hard-break words longer than the line
            while _text_width(draw, word, font) > max_width and len(word) > 1:
                cut = len(word)
                while cut > 1 and _text_width(draw, word[:cut], font) > max_width:
                    cut -= 1
                lines.append(word[:cut])
                word = word[cut:]
            cur = word
        lines.append(cur)
    return lines


def _line_height(font: FontT, spacing: float = 1.25) -> int:
    size = getattr(font, "size", 16)
    return int(size * spacing)


def _fit(draw: ImageDraw.ImageDraw, text: str, start: int, minimum: int, max_width: int,
         max_height: int) -> tuple[FontT, list[str]]:
    size = start
    while True:
        font = _font(size)
        lines = wrap_text(draw, text, font, max_width)
        if len(lines) * _line_height(font) <= max_height or size <= minimum:
            return font, lines
        size = max(minimum, size - 4)


def _palette(template: dict[str, Any]) -> tuple[tuple[int, int, int], tuple[int, int, int], tuple[int, int, int]]:
    colors = template.get("colors") or {}
    neutral = colors.get("neutral") or []
    bg = parse_color(colors.get("background") or colors.get("primary") or (neutral[0] if neutral else None))
    text = parse_color(colors.get("text")) if colors.get("text") else contrast_text_color(bg)
    accent_raw = colors.get("accent") or colors.get("secondary")
    accent = parse_color(accent_raw) if accent_raw else text
    if accent == bg:
        accent = text
    return bg, text, accent


def render_slide(slide: dict[str, Any], index: int, total: int, template: dict[str, Any] | None = None,
                 size: tuple[int, int] = SLIDE_SIZE) -> Image.Image:
    template = template or {}
    bg, text_color, accent = _palette(template)
    if slide.get("background"):
        bg = parse_color(slide["background"])
        text_color = contrast_text_color(bg)
    w, h = size
    margin = int(template.get("margin", round(w * 0.09)))
    sizes = template.get("sizes") or {}
    img = Image.new("RGB", size, bg)
    draw = ImageDraw.Draw(img)

    # accent bar
    bar_h = max(6, h // 110)
    draw.rectangle((margin, margin, margin + w // 9, margin + bar_h), fill=accent)

    content_w = w - 2 * margin
    footer_h = int(h * 0.08)
    top = margin + bar_h + int(h * 0.04)
    bottom = h - margin - footer_h
    avail = bottom - top

    headline = str(slide.get("headline") or "").strip()
    body = str(slide.get("body") or "").strip()
    h_font, h_lines = _fit(draw, headline, int(sizes.get("headline", 84)), int(sizes.get("headline_min", 44)), content_w,
                           int(avail * (0.55 if body else 1.0)))
    y = top
    for line in h_lines if headline else []:
        draw.text((margin, y), line, font=h_font, fill=text_color)
        y += _line_height(h_font, 1.15)
    if body:
        y += int(h * 0.03) if headline else 0
        b_font, b_lines = _fit(draw, body, int(sizes.get("body", 44)), int(sizes.get("body_min", 26)), content_w,
                               max(0, bottom - y))
        for line in b_lines:
            if y + _line_height(b_font) > bottom + _line_height(b_font) // 2:
                break
            draw.text((margin, y), line, font=b_font, fill=text_color)
            y += _line_height(b_font)

    small = _font(int(sizes.get("counter", 30)))
    if template.get("show_counter", True) and total > 1:
        counter = f"{index + 1}/{total}"
        cw = _text_width(draw, counter, small)
        draw.text((w - margin - cw, h - margin - _line_height(small)), counter, font=small, fill=accent)
    footer = slide.get("footer") or template.get("footer")
    if footer:
        draw.text((margin, h - margin - _line_height(small)), str(footer), font=small, fill=text_color)
    return img


def compose_slides(slides: list[dict[str, Any]], template: dict[str, Any] | None = None, *,
                   size: tuple[int, int] = SLIDE_SIZE, fmt: str = "PNG") -> list[bytes]:
    """Render slides [{headline, body, background?, footer?}] with template {colors, fonts, sizes?, margin?, footer?,
    show_counter?} → encoded images (PNG by default, metadata-free)."""
    if not slides:
        raise ValueError("at least one slide is required")
    out: list[bytes] = []
    total = len(slides)
    for i, slide in enumerate(slides):
        img = render_slide(slide, i, total, template, size)
        buf = io.BytesIO()
        if fmt.upper() == "JPEG":
            img.save(buf, "JPEG", quality=92, optimize=True)
        else:
            img.save(buf, "PNG", optimize=True)
        out.append(buf.getvalue())
    return out


def slides_to_pdf(slides: list[bytes]) -> bytes:
    """Bundle rendered slides into one PDF (LinkedIn document carousel)."""
    if not slides:
        raise ValueError("no slides")
    pages = [Image.open(io.BytesIO(b)).convert("RGB") for b in slides]
    buf = io.BytesIO()
    pages[0].save(buf, "PDF", save_all=True, append_images=pages[1:], resolution=150.0)
    return buf.getvalue()

"""Deterministic offline image provider for local dev and tests: a solid-color PNG with the prompt drawn on it."""
from __future__ import annotations

import hashlib
import io
import textwrap
from typing import Any

from PIL import Image, ImageDraw, ImageFont

from app.integrations.media.base import GeneratedImage, parse_size

MAX_SIDE = 2048


class FakeImageProvider:
    name = "fake"
    model = "fake-image-1"

    def capabilities(self) -> dict[str, Any]:
        return {"provider": self.name, "model": self.model, "sizes": ["any"], "max_n": 4, "edit": True,
                "negative_prompt": True, "offline": True}

    @staticmethod
    def _render(prompt: str, size: tuple[int, int], seed: int) -> bytes:
        w, h = min(size[0], MAX_SIDE), min(size[1], MAX_SIDE)
        digest = hashlib.sha256(f"{seed}:{prompt}".encode()).digest()
        bg = (64 + digest[0] % 160, 64 + digest[1] % 160, 64 + digest[2] % 160)
        lum = 0.299 * bg[0] + 0.587 * bg[1] + 0.114 * bg[2]
        fg = (20, 20, 20) if lum > 140 else (245, 245, 245)
        img = Image.new("RGB", (w, h), bg)
        draw = ImageDraw.Draw(img)
        font_size = max(12, min(w, h) // 22)
        try:
            font: Any = ImageFont.load_default(size=font_size)
        except TypeError:
            font = ImageFont.load_default()
        chars_per_line = max(10, int(w / (font_size * 0.55)))
        lines = textwrap.wrap(prompt.strip() or "(empty prompt)", width=chars_per_line)[:12]
        y = h // 10
        for line in lines:
            draw.text((w // 12, y), line, fill=fg, font=font)
            y += int(font_size * 1.3)
        draw.text((w // 12, h - h // 10), f"botwok fake image · seed {seed}", fill=fg, font=font)
        buf = io.BytesIO()
        img.save(buf, "PNG")
        return buf.getvalue()

    async def generate(self, prompt: str, *, negative_prompt: str | None = None, size: str = "1024x1024", n: int = 1,
                       style: str | None = None, quality: str | None = None,
                       reference_images: list[bytes] | None = None) -> list[GeneratedImage]:
        w, h = parse_size(size)
        base_seed = int.from_bytes(hashlib.sha256(prompt.encode()).digest()[:4], "big")
        out = []
        for i in range(max(1, min(n, 4))):
            seed = base_seed + i
            out.append(GeneratedImage(data=self._render(prompt, (w, h), seed), mime="image/png", model=self.model,
                                      seed=seed, cost_usd=0.0, width=min(w, MAX_SIDE), height=min(h, MAX_SIDE)))
        return out

    async def edit(self, image: bytes, prompt: str, *, mask: bytes | None = None, size: str = "1024x1024",
                   n: int = 1) -> list[GeneratedImage]:
        return await self.generate(f"[edit] {prompt}", size=size, n=n)

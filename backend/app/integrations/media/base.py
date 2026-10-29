"""ImageProvider port (doc 10 §10.3)."""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any, Protocol, runtime_checkable


@dataclass
class GeneratedImage:
    data: bytes                       # encoded image bytes (PNG/JPEG/WEBP)
    mime: str = "image/png"
    model: str | None = None
    seed: int | None = None
    cost_usd: float = 0.0
    revised_prompt: str | None = None
    width: int | None = None
    height: int | None = None
    meta: dict[str, Any] = field(default_factory=dict)


class ImageProviderError(Exception):
    """Provider failure. `refused=True` means the provider declined the prompt on safety grounds (do not retry blindly)."""

    def __init__(self, message: str, *, provider: str, refused: bool = False, retryable: bool = False):
        super().__init__(message)
        self.provider = provider
        self.refused = refused
        self.retryable = retryable


@runtime_checkable
class ImageProvider(Protocol):
    name: str
    model: str

    async def generate(self, prompt: str, *, negative_prompt: str | None = None, size: str = "1024x1024", n: int = 1,
                       style: str | None = None, quality: str | None = None,
                       reference_images: list[bytes] | None = None) -> list[GeneratedImage]: ...

    async def edit(self, image: bytes, prompt: str, *, mask: bytes | None = None, size: str = "1024x1024",
                   n: int = 1) -> list[GeneratedImage]: ...

    def capabilities(self) -> dict[str, Any]: ...


_SIZE_RE = re.compile(r"^\s*(\d{2,5})\s*[xX×]\s*(\d{2,5})\s*$")


def parse_size(size: str | None, default: tuple[int, int] = (1024, 1024)) -> tuple[int, int]:
    if not size or size == "auto":
        return default
    m = _SIZE_RE.match(size)
    if not m:
        raise ValueError(f"invalid size {size!r}; expected WIDTHxHEIGHT")
    return int(m.group(1)), int(m.group(2))


def nearest_size(size: str | None, allowed: list[str], default: str) -> str:
    """Map an arbitrary WxH to the allowed size with the closest aspect ratio."""
    if not size or size == "auto":
        return default
    if size in allowed:
        return size
    w, h = parse_size(size)
    target = w / h
    best = min(allowed, key=lambda s: abs((parse_size(s)[0] / parse_size(s)[1]) - target))
    return best


def merge_negative(prompt: str, negative_prompt: str | None, style: str | None = None) -> str:
    """Providers without a negative-prompt parameter get it folded into the prompt."""
    text = prompt.strip()
    if style:
        text += f"\nStyle: {style.strip()}"
    if negative_prompt:
        text += f"\nAvoid: {negative_prompt.strip()}"
    return text

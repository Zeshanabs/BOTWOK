"""xAI image generation through the OpenAI-compatible endpoint (https://api.x.ai/v1).

NEEDS VERIFICATION before enabling for users (not covered by docs/platforms/*):
- model id `grok-2-image` (xAI may have newer image models; make it configurable via ai_settings.media.image.model),
- `size`/`quality`/`style` are not supported by xAI (we omit them), `n` max 10,
- response_format `b64_json` support, and the per-image price (assumed $0.07).
"""
from __future__ import annotations

import base64
from typing import Any

import httpx

from app.integrations.media.base import GeneratedImage, ImageProviderError, merge_negative

BASE_URL = "https://api.x.ai/v1"
DEFAULT_MODEL = "grok-2-image"          # NEEDS VERIFICATION
EST_COST_PER_IMAGE = 0.07               # NEEDS VERIFICATION
TIMEOUT_S = 120.0


class XAIImageProvider:
    name = "xai"

    def __init__(self, api_key: str, *, model: str = DEFAULT_MODEL, base_url: str = BASE_URL,
                 timeout_s: float = TIMEOUT_S):
        if not api_key:
            raise ValueError("xAI API key required")
        self.api_key = api_key
        self.model = model
        self.base_url = base_url
        self.timeout_s = timeout_s

    def _client(self) -> Any:
        from openai import AsyncOpenAI
        return AsyncOpenAI(api_key=self.api_key, base_url=self.base_url, timeout=self.timeout_s, max_retries=2)

    def capabilities(self) -> dict[str, Any]:
        return {"provider": self.name, "model": self.model, "sizes": ["auto"], "max_n": 10, "edit": False,
                "negative_prompt": False, "verified": False}

    async def generate(self, prompt: str, *, negative_prompt: str | None = None, size: str = "1024x1024", n: int = 1,
                       style: str | None = None, quality: str | None = None,
                       reference_images: list[bytes] | None = None) -> list[GeneratedImage]:
        import openai
        try:
            resp = await self._client().images.generate(model=self.model, prompt=merge_negative(prompt, negative_prompt, style),
                                                        n=max(1, min(n, 10)), response_format="b64_json")
        except openai.OpenAIError as e:
            retryable = isinstance(e, (openai.RateLimitError, openai.APITimeoutError, openai.APIConnectionError,
                                       openai.InternalServerError))
            raise ImageProviderError(f"xAI image error: {e}", provider=self.name, retryable=retryable) from e
        out: list[GeneratedImage] = []
        for it in list(getattr(resp, "data", None) or []):
            data: bytes | None = None
            if getattr(it, "b64_json", None):
                data = base64.b64decode(it.b64_json)
            elif getattr(it, "url", None):
                async with httpx.AsyncClient(timeout=60) as http:
                    r = await http.get(it.url)
                    r.raise_for_status()
                    data = r.content
            if not data:
                continue
            mime = "image/png" if data[:8] == b"\x89PNG\r\n\x1a\n" else "image/jpeg"
            out.append(GeneratedImage(data=data, mime=mime, model=self.model, cost_usd=EST_COST_PER_IMAGE,
                                      revised_prompt=getattr(it, "revised_prompt", None)))
        if not out:
            raise ImageProviderError("xAI returned no images", provider=self.name, retryable=True)
        return out

    async def edit(self, image: bytes, prompt: str, *, mask: bytes | None = None, size: str = "1024x1024",
                   n: int = 1) -> list[GeneratedImage]:
        raise ImageProviderError("xAI image editing is not supported", provider=self.name)

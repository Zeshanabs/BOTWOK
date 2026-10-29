"""OpenAI Images API provider (`gpt-image-1`) via the official `openai` SDK.

Cost: computed from `response.usage` token counts when returned, else a per-image estimate.
Pricing constants are UNVERIFIED snapshots (gpt-image-1: text in $5/M, image in $10/M, image out $40/M tokens);
update them from https://openai.com/api/pricing when they change.
"""
from __future__ import annotations

import base64
import io
from typing import Any

from app.integrations.media.base import GeneratedImage, ImageProviderError, merge_negative, nearest_size

DEFAULT_MODEL = "gpt-image-1"
ALLOWED_SIZES = ["1024x1024", "1536x1024", "1024x1536"]
PRICE_TEXT_IN_PER_TOKEN = 5.0 / 1_000_000      # UNVERIFIED
PRICE_IMAGE_IN_PER_TOKEN = 10.0 / 1_000_000    # UNVERIFIED
PRICE_IMAGE_OUT_PER_TOKEN = 40.0 / 1_000_000   # UNVERIFIED
EST_COST_PER_IMAGE = {"low": 0.011, "medium": 0.042, "high": 0.167, "auto": 0.042}  # 1024x1024, UNVERIFIED
TIMEOUT_S = 120.0


class OpenAIImageProvider:
    name = "openai"

    def __init__(self, api_key: str, *, model: str = DEFAULT_MODEL, base_url: str | None = None,
                 timeout_s: float = TIMEOUT_S):
        if not api_key:
            raise ValueError("OpenAI API key required")
        self.api_key = api_key
        self.model = model
        self.base_url = base_url
        self.timeout_s = timeout_s

    def _client(self) -> Any:
        from openai import AsyncOpenAI
        return AsyncOpenAI(api_key=self.api_key, base_url=self.base_url, timeout=self.timeout_s, max_retries=2)

    def capabilities(self) -> dict[str, Any]:
        return {"provider": self.name, "model": self.model, "sizes": ALLOWED_SIZES, "max_n": 4, "edit": True,
                "negative_prompt": False, "transparent_background": True}

    def _cost(self, usage: Any, n: int, quality: str) -> float:
        if usage is not None:
            try:
                details = getattr(usage, "input_tokens_details", None)
                text_in = getattr(details, "text_tokens", None) if details else None
                image_in = getattr(details, "image_tokens", None) if details else None
                total_in = getattr(usage, "input_tokens", 0) or 0
                text_in = text_in if text_in is not None else total_in
                image_in = image_in or 0
                out = getattr(usage, "output_tokens", 0) or 0
                return round(text_in * PRICE_TEXT_IN_PER_TOKEN + image_in * PRICE_IMAGE_IN_PER_TOKEN
                             + out * PRICE_IMAGE_OUT_PER_TOKEN, 6)
            except (TypeError, ValueError):
                pass
        return round(EST_COST_PER_IMAGE.get(quality, EST_COST_PER_IMAGE["auto"]) * n, 6)

    def _to_images(self, resp: Any, n: int, quality: str, size: str) -> list[GeneratedImage]:
        items = list(getattr(resp, "data", None) or [])
        if not items:
            raise ImageProviderError("OpenAI returned no images", provider=self.name, retryable=True)
        total = self._cost(getattr(resp, "usage", None), len(items), quality)
        w, h = (int(x) for x in size.split("x"))
        out: list[GeneratedImage] = []
        for it in items:
            b64 = getattr(it, "b64_json", None)
            if not b64:
                raise ImageProviderError("OpenAI image without b64_json payload", provider=self.name)
            out.append(GeneratedImage(data=base64.b64decode(b64), mime="image/png", model=self.model,
                                      cost_usd=round(total / len(items), 6),
                                      revised_prompt=getattr(it, "revised_prompt", None), width=w, height=h))
        return out

    @staticmethod
    def _map_error(e: Exception) -> ImageProviderError:
        import openai
        msg = str(e)
        if isinstance(e, openai.BadRequestError) and ("moderation" in msg.lower() or "safety" in msg.lower()):
            return ImageProviderError(f"OpenAI declined the prompt: {msg}", provider="openai", refused=True)
        retryable = isinstance(e, (openai.RateLimitError, openai.APITimeoutError, openai.APIConnectionError,
                                   openai.InternalServerError))
        return ImageProviderError(f"OpenAI image error: {msg}", provider="openai", retryable=retryable)

    async def generate(self, prompt: str, *, negative_prompt: str | None = None, size: str = "1024x1024", n: int = 1,
                       style: str | None = None, quality: str | None = None,
                       reference_images: list[bytes] | None = None) -> list[GeneratedImage]:
        if reference_images:
            return await self.edit(reference_images[0], merge_negative(prompt, negative_prompt, style), size=size, n=n)
        import openai
        api_size = nearest_size(size, ALLOWED_SIZES, "1024x1024")
        q = quality or "auto"
        try:
            resp = await self._client().images.generate(model=self.model, prompt=merge_negative(prompt, negative_prompt, style),
                                                        n=max(1, min(n, 4)), size=api_size, quality=q)
        except openai.OpenAIError as e:
            raise self._map_error(e) from e
        return self._to_images(resp, n, q, api_size)

    async def edit(self, image: bytes, prompt: str, *, mask: bytes | None = None, size: str = "1024x1024",
                   n: int = 1) -> list[GeneratedImage]:
        import openai
        api_size = nearest_size(size, ALLOWED_SIZES, "1024x1024")
        kwargs: dict[str, Any] = {"model": self.model, "prompt": prompt, "n": max(1, min(n, 4)), "size": api_size,
                                  "image": ("image.png", io.BytesIO(image), "image/png")}
        if mask:
            kwargs["mask"] = ("mask.png", io.BytesIO(mask), "image/png")
        try:
            resp = await self._client().images.edit(**kwargs)
        except openai.OpenAIError as e:
            raise self._map_error(e) from e
        return self._to_images(resp, n, "auto", api_size)

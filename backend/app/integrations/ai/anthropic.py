"""AnthropicProvider: AIProvider implementation on the official `anthropic` SDK (Messages API)."""
from __future__ import annotations

import json
import os
from collections.abc import AsyncIterator
from typing import Any

from app.config import settings
from app.core.logging import get_logger
from app.core.ports.ai_provider import Completion, Message, ToolCall, ToolSpec, Usage
from app.integrations.ai import base
from app.integrations.ai.base import (
    ProviderError,
    Timer,
    content_text,
    missing_key_error,
    normalize_messages,
    split_system,
)

log = get_logger("ai.anthropic")

# Models on which sampling params (temperature/top_p) are rejected (thinking-native generations).
_NO_SAMPLING_MARKERS = ("opus-5", "sonnet-5", "fable", "mythos", "opus-4-7", "opus-4-8")


def _supports_sampling(model: str) -> bool:
    m = model.lower()
    return not any(marker in m for marker in _NO_SAMPLING_MARKERS)


class AnthropicProvider:
    name = "anthropic"

    def __init__(self, api_key: str | None = None, base_url: str | None = None, *, timeout_s: float = 120.0):
        self._api_key = api_key or settings.anthropic_api_key or None
        self._base_url = base_url
        self._timeout_s = timeout_s
        self._client: Any = None

    # -- client ---------------------------------------------------------------------------------------------------
    def _get_client(self):
        if self._client is None:
            from anthropic import AsyncAnthropic
            kwargs: dict[str, Any] = {"max_retries": 0, "timeout": self._timeout_s}
            if self._api_key:
                kwargs["api_key"] = self._api_key
            if self._base_url:
                kwargs["base_url"] = self._base_url
            self._client = AsyncAnthropic(**kwargs)
        return self._client

    # -- conversion -----------------------------------------------------------------------------------------------
    @staticmethod
    def _system_blocks(system_msgs: list[Message]) -> list[dict[str, Any]] | None:
        blocks: list[dict[str, Any]] = []
        for m in system_msgs:
            text = content_text(m)
            if not text.strip():
                continue
            block: dict[str, Any] = {"type": "text", "text": text}
            if m.cache:
                block["cache_control"] = {"type": "ephemeral"}
            blocks.append(block)
        return blocks or None

    @staticmethod
    def _convert_messages(msgs: list[Message]) -> list[dict[str, Any]]:
        out: list[dict[str, Any]] = []
        for m in msgs:
            if m.role == "tool":
                block = {"type": "tool_result", "tool_use_id": m.tool_call_id or "", "content": content_text(m)}
                if out and out[-1]["role"] == "user" and isinstance(out[-1]["content"], list) \
                        and out[-1]["content"] and out[-1]["content"][-1].get("type") == "tool_result":
                    out[-1]["content"].append(block)
                else:
                    out.append({"role": "user", "content": [block]})
                continue
            if m.role == "assistant":
                content: list[dict[str, Any]] = []
                text = content_text(m)
                if text.strip():
                    content.append({"type": "text", "text": text})
                for tc in m.tool_calls:
                    content.append({"type": "tool_use", "id": tc.id, "name": tc.name, "input": tc.arguments})
                if not content:
                    continue
                out.append({"role": "assistant", "content": content})
                continue
            # user
            if isinstance(m.content, list):
                content_blocks: list[dict[str, Any]] = [dict(b) for b in m.content if isinstance(b, dict)]
            else:
                content_blocks = [{"type": "text", "text": m.content}]
            if m.cache and content_blocks:
                content_blocks[-1]["cache_control"] = {"type": "ephemeral"}
            out.append({"role": "user", "content": content_blocks})
        if out and out[0]["role"] != "user":
            out.insert(0, {"role": "user", "content": [{"type": "text", "text": "(start)"}]})
        return out

    @staticmethod
    def _translate_error(e: Exception) -> ProviderError:
        import anthropic
        if isinstance(e, anthropic.RateLimitError):
            return ProviderError(str(e), provider="anthropic", status=429, retryable=True, kind="rate_limited")
        if isinstance(e, anthropic.APITimeoutError):
            return ProviderError(str(e), provider="anthropic", status=None, retryable=True, kind="timeout")
        if isinstance(e, anthropic.APIConnectionError):
            return ProviderError(str(e), provider="anthropic", status=None, retryable=True, kind="connection")
        if isinstance(e, anthropic.APIStatusError):
            status = getattr(e, "status_code", None) or 0
            retry = status >= 500 or status in (408, 409, 529)
            return ProviderError(str(e), provider="anthropic", status=status, retryable=retry,
                                 kind="server_error" if retry else "bad_request")
        return ProviderError(str(e), provider="anthropic", retryable=False, kind="unknown")

    # -- API ------------------------------------------------------------------------------------------------------
    async def complete(self, messages: list[Message], *, model: str, tools: list[ToolSpec] | None = None,
                       response_schema: dict[str, Any] | None = None, temperature: float = 0.3,
                       max_tokens: int = 2048) -> Completion:
        if not self._api_key and not os.environ.get("ANTHROPIC_API_KEY"):
            raise missing_key_error("anthropic")
        msgs = normalize_messages(messages)
        if response_schema:
            msgs = base.append_json_instruction(msgs, response_schema)
        system_msgs, rest = split_system(msgs)
        payload: dict[str, Any] = {"model": model, "max_tokens": max_tokens, "messages": self._convert_messages(rest)}
        system = self._system_blocks(system_msgs)
        if system:
            payload["system"] = system
        if tools:
            payload["tools"] = base.tool_specs_as(tools, "anthropic")
        # anthropic SDK >= 1.12 no longer accepts sampling params on Messages.create; temperature is ignored.
        _ = (temperature, _supports_sampling)
        if response_schema:
            payload["output_config"] = {"format": {"type": "json_schema", "schema": response_schema}}

        async def _call(p: dict[str, Any]):
            client = self._get_client()
            try:
                with Timer() as t:
                    resp = await client.messages.create(**p)
                return resp, t.ms
            except Exception as e:  # noqa: BLE001 - translated below
                raise self._translate_error(e) from e

        try:
            resp, ms = await base.with_retries(lambda: _call(payload), provider=self.name)
        except ProviderError as e:
            # Structured-output format may be rejected (unsupported schema feature / model). Fall back to prompt-only JSON.
            if "output_config" in payload and e.status == 400:
                log.warning("anthropic.output_config_rejected", error=str(e)[:200])
                payload.pop("output_config", None)
                resp, ms = await base.with_retries(lambda: _call(payload), provider=self.name)
            else:
                raise
        return self._to_completion(resp, model, ms)

    def _to_completion(self, resp: Any, model: str, latency_ms: int) -> Completion:
        texts: list[str] = []
        calls: list[ToolCall] = []
        for block in getattr(resp, "content", []) or []:
            btype = getattr(block, "type", None)
            if btype == "text":
                texts.append(block.text)
            elif btype == "tool_use":
                args = block.input if isinstance(block.input, dict) else {}
                calls.append(ToolCall(id=block.id, name=block.name, arguments=args))
        u = getattr(resp, "usage", None)
        cache_read = int(getattr(u, "cache_read_input_tokens", 0) or 0)
        cache_write = int(getattr(u, "cache_creation_input_tokens", 0) or 0)
        tokens_in = int(getattr(u, "input_tokens", 0) or 0) + cache_read + cache_write
        usage = Usage(tokens_in=tokens_in, tokens_out=int(getattr(u, "output_tokens", 0) or 0), cached_tokens=cache_read)
        finish = getattr(resp, "stop_reason", None) or ("tool_use" if calls else "end_turn")
        return base.make_completion(content="\n".join(texts), tool_calls=calls, usage=usage,
                                    model=getattr(resp, "model", model) or model, provider=self.name,
                                    finish_reason=str(finish), latency_ms=latency_ms, raw=resp)

    async def stream(self, messages: list[Message], *, model: str, temperature: float = 0.3,
                     max_tokens: int = 2048) -> AsyncIterator[str]:
        msgs = normalize_messages(messages)
        system_msgs, rest = split_system(msgs)
        payload: dict[str, Any] = {"model": model, "max_tokens": max_tokens, "messages": self._convert_messages(rest)}
        system = self._system_blocks(system_msgs)
        if system:
            payload["system"] = system
        # anthropic SDK >= 1.12 no longer accepts sampling params on Messages.create; temperature is ignored.
        _ = (temperature, _supports_sampling)
        client = self._get_client()
        try:
            async with client.messages.stream(**payload) as s:
                async for text in s.text_stream:
                    yield text
        except Exception as e:  # noqa: BLE001
            raise self._translate_error(e) from e

    def count_tokens(self, messages: list[Message], model: str) -> int:
        """Synchronous estimate (tiktoken ×1.15: tiktoken undercounts Claude by ~15%). Use count_tokens_remote for exact."""
        return base.estimate_tokens(normalize_messages(messages), ratio=1.15)

    async def count_tokens_remote(self, messages: list[Message], model: str, tools: list[ToolSpec] | None = None) -> int:
        msgs = normalize_messages(messages)
        system_msgs, rest = split_system(msgs)
        payload: dict[str, Any] = {"model": model, "messages": self._convert_messages(rest)}
        system = self._system_blocks(system_msgs)
        if system:
            payload["system"] = system
        if tools:
            payload["tools"] = base.tool_specs_as(tools, "anthropic")
        try:
            resp = await self._get_client().messages.count_tokens(**payload)
            return int(resp.input_tokens)
        except Exception as e:  # noqa: BLE001
            log.warning("anthropic.count_tokens_failed", error=str(e)[:200])
            return self.count_tokens(messages, model)

    def __repr__(self) -> str:
        return f"AnthropicProvider(key={'set' if self._api_key else 'unset'})"


def _debug_payload(p: dict[str, Any]) -> str:  # pragma: no cover - debugging aid
    return json.dumps(p, default=str)[:2000]

"""OpenAICompatibleProvider: chat.completions adapter used for openai, xai, ollama, openrouter, google (OpenAI-compatible)."""
from __future__ import annotations

import json
from collections.abc import AsyncIterator
from typing import Any

from app.core.logging import get_logger
from app.core.ports.ai_provider import Completion, Message, ToolCall, ToolSpec, Usage
from app.integrations.ai import base
from app.integrations.ai.base import (
    KEYLESS_PROVIDERS,
    ProviderError,
    Timer,
    content_text,
    missing_key_error,
    normalize_messages,
)

log = get_logger("ai.openai_compatible")

_REASONING_PREFIXES = ("gpt-5", "o1", "o3", "o4")


def _is_reasoning_model(model: str) -> bool:
    m = model.lower()
    return any(m.startswith(p) for p in _REASONING_PREFIXES) and not m.startswith("gpt-5-chat")


class OpenAICompatibleProvider:
    def __init__(self, name: str, base_url: str | None = None, api_key: str | None = None, *, timeout_s: float = 120.0,
                 supports_json_schema: bool | None = None, extra_headers: dict[str, str] | None = None):
        self.name = name
        self._base_url = base_url
        self._api_key = api_key or ("ollama" if name == "ollama" else None)
        self._keyless = name in KEYLESS_PROVIDERS
        self._timeout_s = timeout_s
        self._client: Any = None
        self._json_schema_supported: bool | None = supports_json_schema
        self._extra_headers = extra_headers or {}

    def _get_client(self):
        if self._client is None:
            from openai import AsyncOpenAI
            kwargs: dict[str, Any] = {"api_key": self._api_key or "missing", "max_retries": 0, "timeout": self._timeout_s}
            if self._keyless and not self._api_key:
                import httpx

                async def _strip_auth(request: httpx.Request) -> None:   # public endpoint: no bearer token at all
                    request.headers.pop("authorization", None)
                kwargs["http_client"] = httpx.AsyncClient(event_hooks={"request": [_strip_auth]}, timeout=self._timeout_s)
            if self._base_url:
                kwargs["base_url"] = self._base_url
            if self._extra_headers:
                kwargs["default_headers"] = self._extra_headers
            self._client = AsyncOpenAI(**kwargs)
        return self._client

    # -- conversion -----------------------------------------------------------------------------------------------
    @staticmethod
    def _convert_messages(msgs: list[Message]) -> list[dict[str, Any]]:
        out: list[dict[str, Any]] = []
        for m in msgs:
            if m.role == "tool":
                out.append({"role": "tool", "tool_call_id": m.tool_call_id or "", "content": content_text(m)})
            elif m.role == "assistant":
                d: dict[str, Any] = {"role": "assistant", "content": content_text(m) or None}
                if m.tool_calls:
                    d["tool_calls"] = [{"id": tc.id, "type": "function",
                                        "function": {"name": tc.name, "arguments": json.dumps(tc.arguments, default=str)}}
                                       for tc in m.tool_calls]
                out.append(d)
            else:
                out.append({"role": m.role, "content": content_text(m)})
        return out

    def _translate_error(self, e: Exception) -> ProviderError:
        import openai
        if isinstance(e, openai.RateLimitError):
            return ProviderError(str(e), provider=self.name, status=429, retryable=True, kind="rate_limited")
        if isinstance(e, openai.APITimeoutError):
            return ProviderError(str(e), provider=self.name, status=None, retryable=True, kind="timeout")
        if isinstance(e, openai.APIConnectionError):
            return ProviderError(str(e), provider=self.name, status=None, retryable=True, kind="connection")
        if isinstance(e, openai.APIStatusError):
            status = getattr(e, "status_code", None) or 0
            retry = status >= 500 or status in (408, 409)
            return ProviderError(str(e), provider=self.name, status=status, retryable=retry,
                                 kind="server_error" if retry else "bad_request")
        return ProviderError(str(e), provider=self.name, retryable=False, kind="unknown")

    # -- API ------------------------------------------------------------------------------------------------------
    async def complete(self, messages: list[Message], *, model: str, tools: list[ToolSpec] | None = None,
                       response_schema: dict[str, Any] | None = None, temperature: float = 0.3,
                       max_tokens: int = 2048) -> Completion:
        if not self._keyless and not self._api_key:
            raise missing_key_error(self.name)
        msgs = normalize_messages(messages)
        if response_schema:
            msgs = base.append_json_instruction(msgs, response_schema)
        payload: dict[str, Any] = {"model": model, "messages": self._convert_messages(msgs)}
        if self.name == "openai":
            payload["max_completion_tokens"] = max_tokens
        else:
            payload["max_tokens"] = max_tokens
        if temperature is not None and not _is_reasoning_model(model):
            payload["temperature"] = temperature
        if tools:
            payload["tools"] = base.tool_specs_as(tools, "openai")
            payload["tool_choice"] = "auto"
        if response_schema:
            if self._json_schema_supported is not False:
                payload["response_format"] = {"type": "json_schema",
                                              "json_schema": {"name": "output", "schema": response_schema, "strict": False}}
            else:
                payload["response_format"] = {"type": "json_object"}

        async def _call(p: dict[str, Any]):
            client = self._get_client()
            try:
                with Timer() as t:
                    resp = await client.chat.completions.create(**p)
                return resp, t.ms
            except Exception as e:  # noqa: BLE001
                raise self._translate_error(e) from e

        try:
            resp, ms = await base.with_retries(lambda: _call(payload), provider=self.name)
        except ProviderError as e:
            if e.status == 400 and payload.get("response_format", {}).get("type") == "json_schema":
                log.warning("openai_compatible.json_schema_unsupported", provider=self.name, error=str(e)[:200])
                self._json_schema_supported = False
                payload["response_format"] = {"type": "json_object"}
                try:
                    resp, ms = await base.with_retries(lambda: _call(payload), provider=self.name)
                except ProviderError as e2:
                    if e2.status == 400:
                        payload.pop("response_format", None)
                        resp, ms = await base.with_retries(lambda: _call(payload), provider=self.name)
                    else:
                        raise
            else:
                raise
        return self._to_completion(resp, model, ms)

    def _to_completion(self, resp: Any, model: str, latency_ms: int) -> Completion:
        choice = (getattr(resp, "choices", None) or [None])[0]
        content = ""
        calls: list[ToolCall] = []
        finish = "stop"
        if choice is not None:
            msg = getattr(choice, "message", None)
            content = (getattr(msg, "content", None) or "") if msg is not None else ""
            for tc in (getattr(msg, "tool_calls", None) or []):
                fn = getattr(tc, "function", None)
                if fn is None:
                    continue
                try:
                    args = json.loads(fn.arguments or "{}")
                except json.JSONDecodeError:
                    try:
                        args = base.extract_json(fn.arguments or "{}")
                    except Exception:
                        args = {"_raw": fn.arguments}
                if not isinstance(args, dict):
                    args = {"value": args}
                calls.append(ToolCall(id=getattr(tc, "id", "") or "", name=fn.name, arguments=args))
            finish = getattr(choice, "finish_reason", None) or ("tool_calls" if calls else "stop")
        u = getattr(resp, "usage", None)
        details = getattr(u, "prompt_tokens_details", None)
        cached = int(getattr(details, "cached_tokens", 0) or 0) if details is not None else 0
        usage = Usage(tokens_in=int(getattr(u, "prompt_tokens", 0) or 0), tokens_out=int(getattr(u, "completion_tokens", 0) or 0),
                      cached_tokens=cached)
        return base.make_completion(content=content, tool_calls=calls, usage=usage, model=getattr(resp, "model", model) or model,
                                    provider=self.name, finish_reason=str(finish), latency_ms=latency_ms, raw=resp)

    async def stream(self, messages: list[Message], *, model: str, temperature: float = 0.3,
                     max_tokens: int = 2048) -> AsyncIterator[str]:
        msgs = normalize_messages(messages)
        payload: dict[str, Any] = {"model": model, "messages": self._convert_messages(msgs), "stream": True}
        payload["max_completion_tokens" if self.name == "openai" else "max_tokens"] = max_tokens
        if temperature is not None and not _is_reasoning_model(model):
            payload["temperature"] = temperature
        try:
            stream = await self._get_client().chat.completions.create(**payload)
            async for chunk in stream:
                choices = getattr(chunk, "choices", None) or []
                if choices:
                    delta = getattr(choices[0], "delta", None)
                    text = getattr(delta, "content", None) if delta is not None else None
                    if text:
                        yield text
        except Exception as e:  # noqa: BLE001
            raise self._translate_error(e) from e

    def count_tokens(self, messages: list[Message], model: str) -> int:
        return base.estimate_tokens(normalize_messages(messages))

    def __repr__(self) -> str:
        return f"OpenAICompatibleProvider(name={self.name!r}, base_url={self._base_url!r})"

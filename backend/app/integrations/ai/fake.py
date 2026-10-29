"""FakeProvider for tests: scripted responses (list of Completion-like dicts / Completions, or a callable); records calls."""
from __future__ import annotations

import itertools
from collections.abc import AsyncIterator, Callable
from typing import Any

from app.core.ports.ai_provider import Completion, Message, ToolCall, ToolSpec, Usage
from app.integrations.ai import base

Scripted = Completion | dict[str, Any]
_ids = itertools.count(1)


def completion_from(obj: Scripted, *, model: str = "fake-model", provider: str = "fake") -> Completion:
    if isinstance(obj, Completion):
        return obj
    calls = []
    for tc in obj.get("tool_calls") or []:
        if isinstance(tc, ToolCall):
            calls.append(tc)
        else:
            calls.append(ToolCall(id=tc.get("id") or f"call_{next(_ids)}", name=tc["name"], arguments=tc.get("arguments", {})))
    u = obj.get("usage") or {}
    usage = u if isinstance(u, Usage) else Usage(tokens_in=int(u.get("tokens_in", 100)), tokens_out=int(u.get("tokens_out", 50)),
                                                 cached_tokens=int(u.get("cached_tokens", 0)))
    content = obj.get("content", "")
    if not isinstance(content, str):
        import json
        content = json.dumps(content, default=str)
    return Completion(content=content, tool_calls=calls, usage=usage, model=obj.get("model", model),
                      provider=obj.get("provider", provider), finish_reason=obj.get("finish_reason") or ("tool_use" if calls else "end_turn"),
                      latency_ms=int(obj.get("latency_ms", 1)), raw=obj.get("raw"))


class FakeProvider:
    """responses: list of scripted completions consumed in order (last one repeats), or callable(messages, kwargs)->Scripted."""

    def __init__(self, responses: list[Scripted] | Callable[[list[Message], dict[str, Any]], Scripted] | None = None,
                 *, name: str = "fake", raise_errors: list[Exception] | None = None):
        self.name = name
        self._responses = list(responses) if isinstance(responses, list) else None
        self._fn = responses if callable(responses) else None
        self._i = 0
        self.calls: list[dict[str, Any]] = []
        self.errors = list(raise_errors or [])

    def _next(self, messages: list[Message], kwargs: dict[str, Any]) -> Completion:
        if self.errors:
            raise self.errors.pop(0)
        if self._fn is not None:
            return completion_from(self._fn(messages, kwargs), model=kwargs.get("model", "fake-model"))
        if not self._responses:
            return completion_from({"content": "{}"}, model=kwargs.get("model", "fake-model"))
        obj = self._responses[min(self._i, len(self._responses) - 1)]
        self._i += 1
        return completion_from(obj, model=kwargs.get("model", "fake-model"))

    async def complete(self, messages: list[Message], *, model: str, tools: list[ToolSpec] | None = None,
                       response_schema: dict[str, Any] | None = None, temperature: float = 0.3,
                       max_tokens: int = 2048) -> Completion:
        msgs = base.normalize_messages(messages)
        kwargs = {"model": model, "tools": [t.name for t in tools or []], "response_schema": response_schema,
                  "temperature": temperature, "max_tokens": max_tokens}
        self.calls.append({"messages": msgs, **kwargs})
        comp = self._next(msgs, kwargs)
        comp.model = comp.model or model
        comp.provider = self.name
        return comp

    async def stream(self, messages: list[Message], *, model: str, temperature: float = 0.3,
                     max_tokens: int = 2048) -> AsyncIterator[str]:
        comp = await self.complete(messages, model=model, temperature=temperature, max_tokens=max_tokens)
        for chunk in comp.content.split(" "):
            yield chunk + " "

    def count_tokens(self, messages: list[Message], model: str) -> int:
        return sum(len(base.content_text(m)) // 4 + 4 for m in base.normalize_messages(messages))

    @property
    def last_call(self) -> dict[str, Any] | None:
        return self.calls[-1] if self.calls else None

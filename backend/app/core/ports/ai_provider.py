from __future__ import annotations

from collections.abc import AsyncIterator
from dataclasses import dataclass, field
from typing import Any, Protocol


@dataclass
class ToolSpec:
    name: str
    description: str
    parameters: dict[str, Any]          # JSON schema


@dataclass
class ToolCall:
    id: str
    name: str
    arguments: dict[str, Any]


@dataclass
class Message:
    role: str                           # system | user | assistant | tool
    content: str | list[dict[str, Any]] = ""
    tool_calls: list[ToolCall] = field(default_factory=list)
    tool_call_id: str | None = None     # for role=tool
    name: str | None = None
    cache: bool = False                 # mark stable prefix for provider prompt caching


@dataclass
class Usage:
    tokens_in: int = 0
    tokens_out: int = 0
    cached_tokens: int = 0


@dataclass
class Completion:
    content: str
    tool_calls: list[ToolCall]
    usage: Usage
    model: str
    provider: str
    finish_reason: str
    latency_ms: int
    raw: Any = None


class AIProvider(Protocol):
    name: str

    async def complete(self, messages: list[Message], *, model: str, tools: list[ToolSpec] | None = None,
                       response_schema: dict[str, Any] | None = None, temperature: float = 0.3,
                       max_tokens: int = 2048) -> Completion: ...

    async def stream(self, messages: list[Message], *, model: str, temperature: float = 0.3,
                     max_tokens: int = 2048) -> AsyncIterator[str]: ...

    def count_tokens(self, messages: list[Message], model: str) -> int: ...

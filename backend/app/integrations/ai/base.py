"""Shared helpers for AI provider adapters: message normalization, tool schema conversion, structured-output
enforcement (ask → parse → repair once), retry with backoff, latency timing, token estimation."""
from __future__ import annotations

import asyncio
import json
import random
import re
import time
from collections.abc import Awaitable, Callable
from typing import Any

from app.core.logging import get_logger
from app.core.ports.ai_provider import Completion, Message, ToolCall, ToolSpec, Usage

log = get_logger("ai.base")

# doc 05 §5.4: 1s, 4s, 12s (+ jitter); tests may monkeypatch
RETRY_DELAYS: list[float] = [1.0, 4.0, 12.0]
RETRY_ATTEMPTS = 3
JSON_INSTRUCTION = ("Respond with a single JSON object only (no prose, no markdown fences) that matches this JSON schema:\n")


class ProviderError(Exception):
    """Normalized provider failure. `retryable` → 429/5xx/timeouts/connection errors."""

    def __init__(self, message: str, *, provider: str = "", status: int | None = None, retryable: bool = False,
                 kind: str = "api_error"):
        super().__init__(message)
        self.provider = provider
        self.status = status
        self.retryable = retryable
        self.kind = kind


class StructuredOutputError(ValueError):
    """The provider returned content that could not be parsed as the requested JSON."""


# ----------------------------------------------------------------------------- messages

def as_message(m: Message | dict[str, Any]) -> Message:
    if isinstance(m, Message):
        return m
    tcs = [tc if isinstance(tc, ToolCall) else ToolCall(id=tc.get("id", ""), name=tc["name"], arguments=tc.get("arguments", {}))
           for tc in (m.get("tool_calls") or [])]
    return Message(role=m["role"], content=m.get("content", ""), tool_calls=tcs, tool_call_id=m.get("tool_call_id"),
                   name=m.get("name"), cache=bool(m.get("cache", False)))


def normalize_messages(messages: list[Message | dict[str, Any]]) -> list[Message]:
    """Coerce dicts, drop empty non-tool messages, keep ordering. Adapters split out system messages themselves."""
    out: list[Message] = []
    for raw in messages:
        m = as_message(raw)
        if m.role not in ("system", "user", "assistant", "tool"):
            raise ValueError(f"unsupported role {m.role!r}")
        if m.role in ("user", "system") and not content_text(m).strip() and not isinstance(m.content, list):
            continue
        out.append(m)
    return out


def content_text(m: Message) -> str:
    if isinstance(m.content, str):
        return m.content
    parts: list[str] = []
    for block in m.content:
        if isinstance(block, dict):
            if block.get("type") == "text" and "text" in block:
                parts.append(str(block["text"]))
            elif "text" in block:
                parts.append(str(block["text"]))
        else:
            parts.append(str(block))
    return "\n".join(parts)


def split_system(messages: list[Message]) -> tuple[list[Message], list[Message]]:
    system = [m for m in messages if m.role == "system"]
    rest = [m for m in messages if m.role != "system"]
    return system, rest


def append_json_instruction(messages: list[Message], schema: dict[str, Any]) -> list[Message]:
    """Attach the structured-output instruction to the last user/tool message (never modifies callers' objects)."""
    instruction = JSON_INSTRUCTION + json.dumps(schema, separators=(",", ":"))
    msgs = list(messages)
    for i in range(len(msgs) - 1, -1, -1):
        if msgs[i].role in ("user", "tool"):
            m = msgs[i]
            if m.role == "tool":
                msgs.append(Message(role="user", content=instruction))
            else:
                msgs[i] = Message(role="user", content=f"{content_text(m)}\n\n{instruction}", cache=m.cache, name=m.name)
            return msgs
    msgs.append(Message(role="user", content=instruction))
    return msgs


# ----------------------------------------------------------------------------- tools

def tool_json_schema(spec: ToolSpec) -> dict[str, Any]:
    """Ensure a well-formed object schema (type/properties/additionalProperties)."""
    schema = dict(spec.parameters or {})
    schema.setdefault("type", "object")
    schema.setdefault("properties", {})
    schema.pop("title", None)
    return schema


def tool_specs_as(specs: list[ToolSpec] | None, fmt: str) -> list[dict[str, Any]]:
    if not specs:
        return []
    if fmt == "anthropic":
        return [{"name": s.name, "description": s.description or s.name, "input_schema": tool_json_schema(s)} for s in specs]
    if fmt == "openai":
        return [{"type": "function", "function": {"name": s.name, "description": s.description or s.name,
                                                   "parameters": tool_json_schema(s)}} for s in specs]
    raise ValueError(fmt)


# ----------------------------------------------------------------------------- structured outputs

_FENCE_RE = re.compile(r"```(?:json)?\s*(.*?)```", re.S)
_TRAILING_COMMA_RE = re.compile(r",\s*([}\]])")


def extract_json(text: str) -> Any:
    """Parse the first JSON object/array in `text`; strips fences; repairs trailing commas once."""
    if text is None:
        raise StructuredOutputError("empty response")
    s = text.strip()
    if not s:
        raise StructuredOutputError("empty response")
    candidates: list[str] = [s]
    m = _FENCE_RE.search(s)
    if m:
        candidates.insert(0, m.group(1).strip())
    # first { ... last } or first [ ... last ]
    for open_c, close_c in (("{", "}"), ("[", "]")):
        a, b = s.find(open_c), s.rfind(close_c)
        if a != -1 and b > a:
            candidates.append(s[a:b + 1])
    last_err: Exception | None = None
    for cand in candidates:
        for attempt in (cand, _TRAILING_COMMA_RE.sub(r"\1", cand)):
            try:
                return json.loads(attempt)
            except json.JSONDecodeError as e:
                last_err = e
    raise StructuredOutputError(f"could not parse JSON: {last_err}")


def parse_structured(text: str) -> dict[str, Any]:
    data = extract_json(text)
    if isinstance(data, dict):
        return data
    if isinstance(data, list):
        return {"items": data}
    raise StructuredOutputError(f"expected JSON object, got {type(data).__name__}")


async def complete_structured(provider: Any, messages: list[Message], *, model: str, schema: dict[str, Any],
                              tools: list[ToolSpec] | None = None, temperature: float = 0.2, max_tokens: int = 2048,
                              on_completion: Callable[[Completion], Awaitable[None]] | None = None
                              ) -> tuple[dict[str, Any], Completion]:
    """Ask for JSON, parse, and repair once by re-prompting with the parse error. Returns (data, last_completion)."""
    comp: Completion = await provider.complete(messages, model=model, tools=tools, response_schema=schema,
                                               temperature=temperature, max_tokens=max_tokens)
    if on_completion:
        await on_completion(comp)
    if comp.tool_calls:
        return {}, comp
    try:
        return parse_structured(comp.content), comp
    except StructuredOutputError as e:
        repair = list(messages) + [Message(role="assistant", content=comp.content or "(empty)"),
                                   Message(role="user", content=f"Your previous reply was not valid JSON ({e}). "
                                                                "Reply again with ONLY the JSON object, nothing else.")]
        comp2: Completion = await provider.complete(repair, model=model, tools=None, response_schema=schema,
                                                    temperature=0.0, max_tokens=max_tokens)
        if on_completion:
            await on_completion(comp2)
        return parse_structured(comp2.content), comp2


# ----------------------------------------------------------------------------- retry / timing

async def with_retries[T](fn: Callable[[], Awaitable[T]], *, attempts: int | None = None, provider: str = "",
                          delays: list[float] | None = None) -> T:
    """Retry `fn` on retryable ProviderError (429/5xx/timeouts). Non-retryable errors propagate immediately."""
    n = attempts or RETRY_ATTEMPTS
    ds = delays if delays is not None else RETRY_DELAYS
    last: Exception | None = None
    for i in range(n):
        try:
            return await fn()
        except ProviderError as e:
            last = e
            if not e.retryable or i == n - 1:
                raise
            delay = ds[min(i, len(ds) - 1)] * (1 + random.uniform(-0.25, 0.25))
            log.warning("provider.retry", provider=provider or e.provider, attempt=i + 1, status=e.status, delay=round(delay, 2))
            await asyncio.sleep(max(0.0, delay))
    assert last is not None
    raise last


class Timer:
    def __enter__(self) -> Timer:
        self._t0 = time.perf_counter()
        self.ms = 0
        return self

    def __exit__(self, *exc: Any) -> None:
        self.ms = int((time.perf_counter() - self._t0) * 1000)


# ----------------------------------------------------------------------------- token estimation

_enc = None


def _encoding():
    global _enc
    if _enc is None:
        try:
            import tiktoken
            _enc = tiktoken.get_encoding("cl100k_base")
        except Exception:  # pragma: no cover - tiktoken data unavailable offline
            _enc = False
    return _enc


def estimate_tokens_text(text: str, *, ratio: float = 1.0) -> int:
    enc = _encoding()
    if enc:
        try:
            return int(len(enc.encode(text, disallowed_special=())) * ratio) + 1
        except Exception:
            pass
    return int(len(text) / 3.8 * ratio) + 1


def estimate_tokens(messages: list[Message], tools: list[ToolSpec] | None = None, *, ratio: float = 1.0) -> int:
    total = 0
    for m in messages:
        total += 4 + estimate_tokens_text(content_text(m), ratio=ratio)
        for tc in m.tool_calls:
            total += estimate_tokens_text(json.dumps(tc.arguments, default=str), ratio=ratio) + 8
    for t in tools or []:
        total += estimate_tokens_text(json.dumps({"name": t.name, "description": t.description, "parameters": t.parameters},
                                                 default=str), ratio=ratio)
    return total


def make_completion(*, content: str, tool_calls: list[ToolCall], usage: Usage, model: str, provider: str,
                    finish_reason: str, latency_ms: int, raw: Any = None) -> Completion:
    return Completion(content=content, tool_calls=tool_calls, usage=usage, model=model, provider=provider,
                      finish_reason=finish_reason, latency_ms=latency_ms, raw=raw)


# ----------------------------------------------------------------------------- configuration helpers

#: Providers that work without an API key: local models and public free endpoints.
KEYLESS_PROVIDERS = frozenset({"ollama", "pollinations", "fake"})

PROVIDER_LABELS = {"anthropic": "Anthropic", "openai": "OpenAI", "google": "Google Gemini", "xai": "xAI", "groq": "Groq",
                   "openrouter": "OpenRouter", "huggingface": "Hugging Face", "pollinations": "Pollinations", "ollama": "Ollama"}


def configuration_hint() -> str:
    """One sentence telling an operator every way to make AI work, used by every "no provider" error."""
    return ("Add a key in Settings → AI → Provider keys or in .env (ANTHROPIC_API_KEY, OPENAI_API_KEY, GOOGLE_API_KEY with a free "
            "tier at aistudio.google.com, GROQ_API_KEY with a free tier at console.groq.com, OPENROUTER_API_KEY, HUGGINGFACE_API_KEY), "
            "run a local model with Ollama (`ollama pull llama3.1`), or set FREE_FALLBACK_MODELS=pollinations/openai to use the "
            "key-less public endpoint.")


def missing_key_error(provider: str) -> ProviderError:
    label = PROVIDER_LABELS.get(provider, provider)
    return ProviderError(f"No API key configured for {label}. {configuration_hint()}", provider=provider, status=401,
                         retryable=False, kind="auth")

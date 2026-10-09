"""`@tool(...)` decorator: derives the JSON schema from the function signature (Pydantic) and registers the tool."""
from __future__ import annotations

import inspect
from collections.abc import Callable
from typing import Any, get_type_hints

from pydantic import BaseModel, ConfigDict, Field, create_model

from app.tools import registry as _reg

_SKIP_PARAM_NAMES = {"ctx", "context", "self"}


def _first_paragraph(doc: str | None) -> str:
    if not doc:
        return ""
    text = inspect.cleandoc(doc)
    return text.split("\n\n", 1)[0].strip().replace("\n", " ")


def _strip_titles(schema: Any) -> Any:
    if isinstance(schema, dict):
        schema.pop("title", None)
        for k, v in list(schema.items()):
            if k in ("properties", "$defs", "definitions") and isinstance(v, dict):
                for sub in v.values():
                    _strip_titles(sub)
            elif isinstance(v, dict | list):
                _strip_titles(v)
    elif isinstance(schema, list):
        for item in schema:
            _strip_titles(item)
    return schema


def build_args_model(fn: Callable[..., Any], name: str) -> type[BaseModel]:
    sig = inspect.signature(fn)
    try:
        hints = get_type_hints(fn, include_extras=True)
    except Exception:  # noqa: BLE001 - unresolved forward refs: fall back to raw annotations
        hints = {p.name: (p.annotation if p.annotation is not inspect.Parameter.empty else Any) for p in sig.parameters.values()}
    fields: dict[str, Any] = {}
    for i, p in enumerate(sig.parameters.values()):
        if i == 0 and (p.name in _SKIP_PARAM_NAMES or hints.get(p.name) is _reg.ToolContext):
            continue
        if p.kind in (inspect.Parameter.VAR_POSITIONAL, inspect.Parameter.VAR_KEYWORD):
            continue
        ann = hints.get(p.name, Any)
        if ann is inspect.Parameter.empty:
            ann = Any
        if p.default is inspect.Parameter.empty:
            fields[p.name] = (ann, Field(...))
        else:
            fields[p.name] = (ann, p.default)
    model_name = "".join(part.capitalize() for part in name.replace(".", "_").split("_")) + "Args"
    return create_model(model_name, __config__=ConfigDict(extra="ignore"), **fields)  # type: ignore[call-overload]


def json_schema_for(model: type[BaseModel]) -> dict[str, Any]:
    schema = model.model_json_schema()
    schema = _strip_titles(schema)
    schema.setdefault("type", "object")
    schema.setdefault("properties", {})
    schema["additionalProperties"] = False
    return schema


def tool(name: str, side_effect: _reg.SideEffect | str = _reg.SideEffect.READ, roles: set[str] | list[str] | None = None,
         timeout_s: float = 20.0, idempotent: bool = False, description: str | None = None, *,
         untrusted_output: bool = False, rate_limit_per_run: int | None = None, registry: _reg.ToolRegistry | None = None):
    """Register an async tool. The first parameter must be `ctx: ToolContext`; the rest become the LLM-visible schema."""
    se = _reg.SideEffect(side_effect) if isinstance(side_effect, str) else side_effect

    def deco(fn: Callable[..., Any]) -> Callable[..., Any]:
        if not inspect.iscoroutinefunction(fn):
            raise TypeError(f"tool {name} must be an async function")
        args_model = build_args_model(fn, name)
        t = _reg.ToolDef(name=name, fn=fn, side_effect=se, description=description or _first_paragraph(fn.__doc__) or name,
                         parameters=json_schema_for(args_model), args_model=args_model,
                         roles=set(roles) if roles else None, timeout_s=timeout_s, idempotent=idempotent,
                         untrusted_output=untrusted_output, rate_limit_per_run=rate_limit_per_run, module=fn.__module__)
        (registry or _reg.registry).register(t)
        fn.__tool__ = t  # type: ignore[attr-defined]
        return fn
    return deco

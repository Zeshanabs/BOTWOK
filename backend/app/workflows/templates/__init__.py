"""Built-in workflow templates (doc 14 §14.7) stored as JSON next to this module.

Each file: ``{key, name, description, category, order, requires_autonomous_actions, params{name: {type, default,
description}}, workflow{name, description, settings, nodes[], edges[]}}``. ``[[param]]`` placeholders are substituted
at instantiation (a string that is exactly ``[[param]]`` becomes the native value; ``None`` values drop the key);
``{{ }}`` templates are left for the engine to render at run time.
"""
from __future__ import annotations

import copy
import json
import re
from functools import lru_cache
from pathlib import Path
from typing import Any

from app.core.errors import validation

DIR = Path(__file__).parent
_PH = re.compile(r"\[\[([a-z_][a-z0-9_]*)\]\]")
_TYPES = {"string": str, "number": (int, float), "integer": int, "boolean": bool, "array": list, "object": dict}


@lru_cache(maxsize=1)
def _load() -> dict[str, dict[str, Any]]:
    out = {}
    for p in sorted(DIR.glob("*.json")):
        data = json.loads(p.read_text(encoding="utf-8"))
        out[data["key"]] = data
    return dict(sorted(out.items(), key=lambda kv: (kv[1].get("order", 99), kv[0])))


def list_templates() -> list[dict[str, Any]]:
    return [copy.deepcopy(t) for t in _load().values()]


def get_template(key: str) -> dict[str, Any] | None:
    t = _load().get(key)
    return copy.deepcopy(t) if t else None


def _subst(value: Any, params: dict[str, Any]) -> Any:
    if isinstance(value, str):
        m = _PH.fullmatch(value)
        if m:
            return params.get(m.group(1))
        return _PH.sub(lambda mm: "" if params.get(mm.group(1)) is None else str(params.get(mm.group(1))), value)
    if isinstance(value, dict):
        res = {k: _subst(v, params) for k, v in value.items()}
        return {k: v for k, v in res.items() if v is not None}
    if isinstance(value, list):
        return [_subst(v, params) for v in value]
    return value


def resolve_params(template: dict[str, Any], given: dict[str, Any] | None) -> dict[str, Any]:
    spec = template.get("params") or {}
    given = dict(given or {})
    unknown = sorted(set(given) - set(spec))
    errors = [{"node_key": None, "code": "unknown_param", "message": f"unknown template parameter {k!r}"} for k in unknown]
    out: dict[str, Any] = {}
    for name, p in spec.items():
        v = given.get(name, p.get("default"))
        t = _TYPES.get(p.get("type", ""))
        if v is not None and t is not None and (not isinstance(v, t) or (p.get("type") in ("number", "integer")
                                                                           and isinstance(v, bool))):
            errors.append({"node_key": None, "code": "invalid_param", "message": f"parameter {name!r} must be {p['type']}"})
        if v is not None and p.get("enum") and v not in p["enum"]:
            errors.append({"node_key": None, "code": "invalid_param",
                           "message": f"parameter {name!r} must be one of {', '.join(map(str, p['enum']))}"})
        out[name] = v
    if errors:
        raise validation(errors[0]["message"], errors)
    return out


def instantiate(key: str, params: dict[str, Any] | None = None) -> dict[str, Any]:
    """→ ``{name, description, settings, nodes, edges, requires_autonomous_actions}`` ready for AutomationEngine.save."""
    t = get_template(key)
    if t is None:
        raise KeyError(key)
    values = resolve_params(t, params)
    wf = _subst(t["workflow"], values)
    return {"name": wf.get("name") or t["name"], "description": wf.get("description") or t.get("description"),
            "settings": wf.get("settings") or {}, "nodes": wf.get("nodes") or [], "edges": wf.get("edges") or [],
            "requires_autonomous_actions": bool(t.get("requires_autonomous_actions")), "template_key": key}

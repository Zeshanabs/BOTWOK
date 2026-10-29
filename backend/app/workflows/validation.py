"""Workflow definition validation (doc 14 §14.3): one trigger, acyclic except bounded wait loops, reachability,
config schema per node, valid branches, expressions/templates that compile, and the autonomous-actions guardrail.

Errors are ``[{node_key, message, code}]`` and surface as ``422 {errors:[…]}`` (doc 17 "Automations").
"""
from __future__ import annotations

import re
from typing import Any

from app.core.errors import validation as validation_error
from app.workflows import cron
from app.workflows.catalog import GUARDED_TYPES, NODE_TYPES, SETTINGS_SCHEMA, TRIGGER_TYPES, agent_actions
from app.workflows.expressions import check_expression, check_template, is_template
from app.workflows.graph import Graph

KEY_RE = re.compile(r"^[A-Za-z][A-Za-z0-9_]{0,63}$")
STEP_REF_RE = re.compile(r"\bsteps\.([A-Za-z_][A-Za-z0-9_]*)")
MAX_NODES = 100
MAX_EDGES = 300

_TYPES: dict[str, tuple[type, ...]] = {"string": (str,), "integer": (int,), "number": (int, float), "boolean": (bool,),
                                       "object": (dict,), "array": (list,), "null": (type(None),)}


# ============================================================================================ JSON-schema subset

def schema_errors(value: Any, schema: dict[str, Any], path: str = "", *, allow_templates: bool = True) -> list[str]:
    """Validate ``value`` against a JSON-schema subset: type, enum, const, properties, required,
    additionalProperties (bool), items, min/maxItems, min/maxLength, minimum/maximum, pattern, anyOf.
    With ``allow_templates`` a ``{{ }}`` string is accepted wherever a value is expected (checked after rendering)."""
    errs: list[str] = []
    where = path or "config"
    if allow_templates and is_template(value):
        return errs
    t = schema.get("type")
    if t:
        types = t if isinstance(t, list) else [t]
        ok = False
        for tn in types:
            py = _TYPES.get(tn, ())
            if isinstance(value, py) and not (tn in ("integer", "number") and isinstance(value, bool)):
                ok = True
                break
        if not ok:
            return [f"{where} must be {' or '.join(types)}"]
    if "enum" in schema and value not in schema["enum"]:
        opts = ", ".join(map(str, schema["enum"][:12]))
        errs.append(f"{where} must be one of: {opts}{'…' if len(schema['enum']) > 12 else ''}")
    if "const" in schema and value != schema["const"]:
        errs.append(f"{where} must be {schema['const']!r}")
    if isinstance(value, str):
        if "minLength" in schema and len(value) < schema["minLength"]:
            errs.append(f"{where} is too short (min {schema['minLength']})")
        if "maxLength" in schema and len(value) > schema["maxLength"]:
            errs.append(f"{where} is too long (max {schema['maxLength']})")
        if "pattern" in schema and not re.search(schema["pattern"], value):
            errs.append(f"{where} has an invalid format")
    if isinstance(value, int | float) and not isinstance(value, bool):
        if "minimum" in schema and value < schema["minimum"]:
            errs.append(f"{where} must be ≥ {schema['minimum']}")
        if "maximum" in schema and value > schema["maximum"]:
            errs.append(f"{where} must be ≤ {schema['maximum']}")
    if isinstance(value, list):
        if "minItems" in schema and len(value) < schema["minItems"]:
            errs.append(f"{where} needs at least {schema['minItems']} item(s)")
        if "maxItems" in schema and len(value) > schema["maxItems"]:
            errs.append(f"{where} allows at most {schema['maxItems']} item(s)")
        if isinstance(schema.get("items"), dict):
            for i, item in enumerate(value[:500]):
                errs += schema_errors(item, schema["items"], f"{where}[{i}]", allow_templates=allow_templates)
    if isinstance(value, dict):
        props = schema.get("properties") or {}
        for req in schema.get("required") or []:
            if value.get(req) in (None, "", []):
                errs.append(f"{where}.{req} is required" if path else f"{req} is required")
        if schema.get("additionalProperties") is False:
            for k in value:
                if k not in props:
                    errs.append(f"{where}.{k} is not a known field" if path else f"unknown field {k!r}")
        for k, sub in props.items():
            if k in value and value[k] is not None:
                errs += schema_errors(value[k], sub, f"{path}.{k}" if path else k, allow_templates=allow_templates)
    if "anyOf" in schema:
        if not any(not schema_errors(value, s, path, allow_templates=allow_templates) for s in schema["anyOf"]):
            alts = [", ".join(s.get("required", [])) for s in schema["anyOf"] if s.get("required")]
            errs.append(f"{where} needs one of: {' | '.join(alts)}" if alts else f"{where} matches no allowed shape")
    return errs


# ============================================================================================ node-specific checks

def _strings(value: Any) -> list[str]:
    if isinstance(value, str):
        return [value]
    if isinstance(value, dict):
        return [s for v in value.values() for s in _strings(v)]
    if isinstance(value, list):
        return [s for v in value for s in _strings(v)]
    return []


def node_specific_errors(ntype: str, cfg: dict[str, Any]) -> list[str]:
    errs: list[str] = []
    if ntype == "trigger.cron":
        msg = cron.validate_schedule(cfg)
        if msg:
            errs.append(msg)
    elif ntype == "trigger.event":
        if cfg.get("condition") and (m := check_expression(str(cfg["condition"]))):
            errs.append(f"condition: {m}")
        flt = cfg.get("filter") or {}
        if not isinstance(flt, dict):
            errs.append("filter must be an object")
    elif ntype == "condition":
        if (m := check_expression(str(cfg.get("expression") or ""))):
            errs.append(f"expression: {m}")
    elif ntype == "wait":
        has = [k for k in ("minutes", "hours", "days", "until", "until_expression") if cfg.get(k) not in (None, "")]
        if not has:
            errs.append("wait needs a duration (minutes/hours/days), an until time, or an until_expression")
        if cfg.get("until_expression") and (m := check_expression(str(cfg["until_expression"]))):
            errs.append(f"until_expression: {m}")
    elif ntype == "ai_agent":
        acts = agent_actions()
        agent, action = cfg.get("agent"), cfg.get("action")
        if acts and agent in acts and isinstance(action, str) and not is_template(action) and action not in acts[agent]:
            errs.append(f"agent {agent!r} has no action {action!r} (valid: {', '.join(acts[agent])})")
    elif ntype == "generate":
        kind = cfg.get("kind")
        if kind == "post":
            if not cfg.get("platform"):
                errs.append("generate post needs a platform")
            if not (cfg.get("idea") or cfg.get("prompt") or cfg.get("title") or cfg.get("content_item_id")):
                errs.append("generate post needs an idea, a content_item_id, a prompt or a title")
        elif kind == "variants":
            if not cfg.get("content_item_id") or not cfg.get("targets"):
                errs.append("generate variants needs content_item_id and targets")
        elif kind == "image" and not cfg.get("prompt"):
            errs.append("generate image needs a prompt")
    elif ntype == "transform":
        if cfg.get("mode") == "template" and "template" not in cfg:
            errs.append("transform template mode needs a template")
        if cfg.get("mode") == "ai" and not cfg.get("instructions"):
            errs.append("transform ai mode needs instructions")
    elif ntype == "schedule":
        if cfg.get("strategy") == "fixed" and not cfg.get("at"):
            errs.append("schedule strategy 'fixed' needs 'at'")
        if not (cfg.get("variant") or cfg.get("variants")):
            errs.append("schedule needs a variant (or variants)")
    elif ntype == "publish":
        if not (cfg.get("variant") or cfg.get("variants")):
            errs.append("publish needs a variant (or variants)")
    elif ntype == "webhook":
        url = str(cfg.get("url") or "")
        if not is_template(url) and not url.lower().startswith("https://"):
            errs.append("webhook url must use https://")
    elif ntype == "action":
        params = cfg.get("params") or {}
        if cfg.get("action") == "content.set_status" and str(params.get("status", "")) in ("approved", "rejected"):
            errs.append("content.set_status cannot approve or reject content; use an approve node")
        if cfg.get("action") == "memory.write" and not params.get("text"):
            errs.append("memory.write needs params.text")
    for s in _strings({k: v for k, v in cfg.items() if k not in (NODE_TYPES[ntype].raw_fields if ntype in NODE_TYPES else ())}):
        if (m := check_template(s)):
            errs.append(m)
    return errs


# ============================================================================================ definition

def _err(errors: list[dict[str, Any]], key: str | None, message: str, code: str = "invalid") -> None:
    errors.append({"node_key": key, "message": message, "code": code})


def validate_definition(nodes: list[dict[str, Any]], edges: list[dict[str, Any]], *, autonomous_actions_enabled: bool = False,
                        settings: dict[str, Any] | None = None) -> list[dict[str, Any]]:
    errors: list[dict[str, Any]] = []
    if not isinstance(nodes, list) or not nodes:
        _err(errors, None, "a workflow needs at least a trigger node", "empty")
        return errors
    if len(nodes) > MAX_NODES:
        _err(errors, None, f"a workflow may have at most {MAX_NODES} nodes", "too_large")
    if len(edges) > MAX_EDGES:
        _err(errors, None, f"a workflow may have at most {MAX_EDGES} edges", "too_large")
    for m in schema_errors(settings or {}, SETTINGS_SCHEMA, "settings", allow_templates=False):
        _err(errors, None, m, "invalid_settings")

    seen: set[str] = set()
    for n in nodes:
        key = str(n.get("key") or "")
        if not KEY_RE.match(key):
            _err(errors, key or None, f"node key {key!r} must start with a letter and contain only letters, digits "
                                      "and _ (max 64)", "invalid_key")
            continue
        if key in seen:
            _err(errors, key, f"duplicate node key {key!r}", "duplicate_key")
            continue
        seen.add(key)
        ntype = str(n.get("type") or "")
        nt = NODE_TYPES.get(ntype)
        if nt is None:
            _err(errors, key, f"unknown node type {ntype!r}", "unknown_type")
            continue
        cfg = n.get("config") or {}
        if not isinstance(cfg, dict):
            _err(errors, key, "config must be an object", "invalid_config")
            continue
        for m in schema_errors(cfg, nt.config_schema):
            _err(errors, key, m, "invalid_config")
        for m in node_specific_errors(ntype, cfg):
            _err(errors, key, m, "invalid_config")
        if ntype in GUARDED_TYPES and not autonomous_actions_enabled:
            _err(errors, key, f"'{nt.label}' nodes ({ntype}) act outside Botwok and are disabled until an admin "
                              "enables autonomous actions for this workflow (autonomous_actions_enabled=true). Generated "
                              "content still requires human approval.", "autonomous_actions_disabled")

    triggers = [str(n.get("key")) for n in nodes if str(n.get("type", "")) in TRIGGER_TYPES]
    if len(triggers) != 1:
        _err(errors, None, f"a workflow needs exactly one trigger node (found {len(triggers)})", "trigger_count")

    graph = Graph.build([n for n in nodes if str(n.get("key") or "") in seen], edges)
    pairs: set[tuple[str, str, str | None]] = set()
    for e in graph.edges:
        if e.src not in graph.nodes or e.dst not in graph.nodes:
            _err(errors, e.src or None, f"edge {e.src!r} → {e.dst!r} references an unknown node", "unknown_node")
            continue
        if (e.src, e.dst, e.branch) in pairs:
            _err(errors, e.src, f"duplicate edge {e.src} → {e.dst}", "duplicate_edge")
        pairs.add((e.src, e.dst, e.branch))
        if e.dst in triggers:
            _err(errors, e.dst, "a trigger cannot have incoming edges", "edge_into_trigger")
        src_type = NODE_TYPES.get(str(graph.nodes[e.src].get("type")))
        if src_type is not None and e.branch not in src_type.branches:
            allowed = [b for b in src_type.branches if b is not None]
            hint = f"edges from a {src_type.type} node must use branch {' or '.join(map(repr, allowed))}" \
                if None not in src_type.branches else f"branch must be empty or one of {', '.join(allowed)}"
            _err(errors, e.src, f"invalid branch {e.branch!r} on edge {e.src} → {e.dst}: {hint}", "invalid_branch")
        if e.src == e.dst and str(graph.nodes[e.src].get("type")) != "wait":
            _err(errors, e.src, "only a wait node may loop to itself", "cycle")

    if graph.trigger:
        unreachable = sorted(set(graph.nodes) - graph.reachable())
        for k in unreachable:
            _err(errors, k, f"node {k!r} is not reachable from the trigger", "unreachable")

    for comp in graph.cycles():
        waits = [k for k in comp if str(graph.nodes[k].get("type")) == "wait"]
        bounded = [k for k in waits if isinstance((graph.nodes[k].get("config") or {}).get("max_iterations"), int)]
        if not bounded:
            _err(errors, sorted(comp)[0], f"cycle {' → '.join(sorted(comp))} is not allowed: loops must pass through a "
                                          "wait node with max_iterations", "cycle")

    for n in nodes:
        key = str(n.get("key") or "")
        for s in _strings(n.get("config") or {}):
            for ref in STEP_REF_RE.findall(s):
                if ref not in graph.nodes:
                    _err(errors, key, f"template references unknown step {ref!r}", "unknown_step_ref")
    return errors


def raise_if_invalid(errors: list[dict[str, Any]]) -> None:
    if errors:
        first = errors[0]["message"]
        more = f" (+{len(errors) - 1} more)" if len(errors) > 1 else ""
        raise validation_error(f"Workflow is invalid: {first}{more}", errors)


def normalize_definition(nodes: list[Any], edges: list[Any]) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Accept pydantic models or dicts; edges may use from/to or from_node_key/to_node_key."""
    def as_dict(x: Any) -> dict[str, Any]:
        if hasattr(x, "model_dump"):
            return x.model_dump(by_alias=True, exclude_none=False)
        return dict(x)
    ns = []
    for n in nodes or []:
        d = as_dict(n)
        ns.append({"key": d.get("key"), "type": d.get("type"), "config": d.get("config") or {},
                   "label": d.get("label"), "position": d.get("position") or {"x": 0, "y": 0}})
    es = []
    for e in edges or []:
        d = as_dict(e)
        es.append({"from": d.get("from") or d.get("from_") or d.get("from_node_key"),
                   "to": d.get("to") or d.get("to_node_key"), "branch": d.get("branch") or None,
                   "condition": d.get("condition")})
    return ns, es

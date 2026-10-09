"""Sandboxed expression language for automations (doc 14 §14.5).

Two evaluators, neither uses Python ``eval``/``exec``:

* **Templates** — ``{{ ... }}`` / ``{% ... %}`` strings rendered with a Jinja2 ``ImmutableSandboxedEnvironment``
  (no private/dunder attribute access, no mutating methods, capped ``range``/repetition/output size). A string that is
  exactly one ``{{ expr }}`` evaluates to the native value (list, dict, number…) instead of a string.
* **Boolean expressions** — a small grammar (``trigger.score >= 80 and "news" in kinds``) parsed with :mod:`ast` and
  compiled to closures over a whitelist of node types, operators and functions (``len``, ``lower``, ``upper``,
  ``contains``, ``date_diff`` …). Attribute access is a dict-key lookup only (``a.b`` ≡ ``a["b"]``), never ``getattr``;
  names starting with ``_`` are rejected at compile time; unknown top-level names raise :class:`ExpressionError`.

Context exposed by the engine: ``trigger``, ``brand``, ``workspace``, ``steps``, ``now`` (ISO string), ``env``.
"""
from __future__ import annotations

import ast
import math
import operator
import re
from collections.abc import Callable, Mapping
from datetime import UTC, date, datetime
from functools import lru_cache
from typing import Any

from jinja2 import ChainableUndefined, TemplateError, Undefined
from jinja2.sandbox import ImmutableSandboxedEnvironment, SecurityError

MAX_EXPR_LEN = 2000
MAX_AST_NODES = 300
MAX_STR = 100_000
MAX_SEQ = 10_000
MAX_RANGE = 1000
MAX_LITERAL_ITEMS = 200

Scope = Mapping[str, Any]
Fn = Callable[[Scope], Any]


class ExpressionError(ValueError):
    """Invalid or unsafe expression/template, or an evaluation error."""


# ============================================================================================ helper functions

def _parse_dt(v: Any) -> datetime:
    if isinstance(v, datetime):
        dt = v
    elif isinstance(v, date):
        dt = datetime(v.year, v.month, v.day)
    elif isinstance(v, str) and v.strip():
        s = v.strip()
        if s.endswith("Z"):
            s = s[:-1] + "+00:00"
        try:
            dt = datetime.fromisoformat(s)
        except ValueError as e:
            raise ExpressionError(f"not a date/time: {v!r}") from e
    else:
        raise ExpressionError(f"not a date/time: {v!r}")
    return dt if dt.tzinfo else dt.replace(tzinfo=UTC)


_UNITS = {"seconds": 1, "second": 1, "minutes": 60, "minute": 60, "hours": 3600, "hour": 3600, "days": 86400,
          "day": 86400, "weeks": 604800, "week": 604800}


def fn_date_diff(a: Any, b: Any, unit: str = "days") -> float:
    """(a - b) in ``unit`` (seconds|minutes|hours|days|weeks); a/b are ISO strings or datetimes."""
    if unit not in _UNITS:
        raise ExpressionError(f"date_diff unit must be one of {', '.join(sorted(set(_UNITS)))}")
    return (_parse_dt(a) - _parse_dt(b)).total_seconds() / _UNITS[unit]


def fn_len(x: Any) -> int:
    if x is None:
        return 0
    if isinstance(x, str | list | tuple | dict):
        return len(x)
    raise ExpressionError(f"len() of {type(x).__name__} is not supported")


def fn_lower(x: Any) -> Any:
    return None if x is None else str(x).lower()


def fn_upper(x: Any) -> Any:
    return None if x is None else str(x).upper()


def fn_contains(container: Any, item: Any) -> bool:
    if container is None:
        return False
    if isinstance(container, str):
        return item is not None and str(item) in container
    if isinstance(container, list | tuple | dict):
        try:
            return item in container
        except TypeError:
            return False
    raise ExpressionError(f"contains() on {type(container).__name__} is not supported")


def _num(x: Any, fn: str) -> float | int:
    if isinstance(x, bool) or not isinstance(x, int | float):
        raise ExpressionError(f"{fn}() expects a number")
    return x


def fn_min(*args: Any) -> Any:
    vals = list(args[0]) if len(args) == 1 and isinstance(args[0], list | tuple) else list(args)
    vals = [v for v in vals if v is not None]
    return min(vals) if vals else None


def fn_max(*args: Any) -> Any:
    vals = list(args[0]) if len(args) == 1 and isinstance(args[0], list | tuple) else list(args)
    vals = [v for v in vals if v is not None]
    return max(vals) if vals else None


def fn_round(x: Any, n: Any = 0) -> float:
    return round(_num(x, "round"), int(_num(n, "round")))


def fn_int(x: Any) -> int:
    try:
        return int(float(x)) if isinstance(x, str) else int(_num(x, "int"))
    except (TypeError, ValueError) as e:
        raise ExpressionError(f"int() cannot convert {x!r}") from e


def fn_float(x: Any) -> float:
    try:
        return float(x) if isinstance(x, str) else float(_num(x, "float"))
    except (TypeError, ValueError) as e:
        raise ExpressionError(f"float() cannot convert {x!r}") from e


def fn_str(x: Any) -> str:
    s = "" if x is None else str(x)
    if len(s) > MAX_STR:
        raise ExpressionError("string too long")
    return s


def fn_startswith(s: Any, prefix: Any) -> bool:
    return isinstance(s, str) and isinstance(prefix, str) and s.startswith(prefix)


def fn_endswith(s: Any, suffix: Any) -> bool:
    return isinstance(s, str) and isinstance(suffix, str) and s.endswith(suffix)


FUNCTIONS: dict[str, Callable[..., Any]] = {
    "len": fn_len, "lower": fn_lower, "upper": fn_upper, "contains": fn_contains, "date_diff": fn_date_diff,
    "abs": lambda x: abs(_num(x, "abs")), "min": fn_min, "max": fn_max, "round": fn_round, "int": fn_int,
    "float": fn_float, "str": fn_str, "startswith": fn_startswith, "endswith": fn_endswith,
}
CONSTANT_NAMES = {"true": True, "false": False, "null": None, "none": None, "True": True, "False": False, "None": None}


# ============================================================================================ boolean grammar

def _check_size(v: Any) -> Any:
    if isinstance(v, str) and len(v) > MAX_STR:
        raise ExpressionError("string result too long")
    if isinstance(v, list | tuple) and len(v) > MAX_SEQ:
        raise ExpressionError("list result too long")
    return v


def _arith(op: type[ast.operator], a: Any, b: Any) -> Any:
    num = (int, float)
    a_num = isinstance(a, num) and not isinstance(a, bool)
    b_num = isinstance(b, num) and not isinstance(b, bool)
    try:
        if op is ast.Add:
            if a_num and b_num:
                return a + b
            if isinstance(a, str) and isinstance(b, str) or isinstance(a, list) and isinstance(b, list):
                return _check_size(a + b)
        elif op is ast.Sub and a_num and b_num:
            return a - b
        elif op is ast.Mult:
            if a_num and b_num:
                return a * b
            if isinstance(a, str | list) and isinstance(b, int) and not isinstance(b, bool):
                if len(a) * max(b, 0) > MAX_STR:
                    raise ExpressionError("repetition result too long")
                return a * b
        elif op in (ast.Div, ast.FloorDiv, ast.Mod) and a_num and b_num:
            if b == 0:
                raise ExpressionError("division by zero")
            return a / b if op is ast.Div else (a // b if op is ast.FloorDiv else a % b)
        elif op is ast.Pow and a_num and b_num:
            if abs(b) > 64 or abs(a) > 1e6:
                raise ExpressionError("exponent too large")
            return a ** b
    except OverflowError as e:
        raise ExpressionError("numeric overflow") from e
    raise ExpressionError(f"unsupported operand types for {op.__name__}: {type(a).__name__} and {type(b).__name__}")


def _safe_cmp(fn: Callable[[Any, Any], bool]) -> Callable[[Any, Any], bool]:
    def cmp(a: Any, b: Any) -> bool:
        try:
            return bool(fn(a, b))
        except TypeError:   # None >= 80, "a" < 3 … → False (missing data never raises)
            return False
    return cmp


_CMP: dict[type[ast.cmpop], Callable[[Any, Any], bool]] = {
    ast.Eq: operator.eq, ast.NotEq: operator.ne, ast.Lt: _safe_cmp(operator.lt), ast.LtE: _safe_cmp(operator.le),
    ast.Gt: _safe_cmp(operator.gt), ast.GtE: _safe_cmp(operator.ge),
    ast.In: lambda a, b: fn_contains(b, a), ast.NotIn: lambda a, b: not fn_contains(b, a),
    ast.Is: lambda a, b: a is b, ast.IsNot: lambda a, b: a is not b,
}
_BINOPS = (ast.Add, ast.Sub, ast.Mult, ast.Div, ast.FloorDiv, ast.Mod, ast.Pow)


def _get_key(obj: Any, key: Any) -> Any:
    if obj is None:
        return None
    if isinstance(obj, Mapping):
        if isinstance(key, str) and key.startswith("__"):
            raise ExpressionError("access to dunder keys is not allowed")
        return obj.get(key)
    if isinstance(obj, list | tuple | str):
        if isinstance(key, bool) or not isinstance(key, int):
            raise ExpressionError(f"index must be an integer, got {type(key).__name__}")
        try:
            return obj[key]
        except IndexError:
            return None
    raise ExpressionError(f"cannot index into {type(obj).__name__}")


class _Compiler:
    def __init__(self, allowed_names: set[str] | None) -> None:
        self.allowed = allowed_names
        self.names: set[str] = set()

    def compile(self, node: ast.AST) -> Fn:  # noqa: C901 - one dispatch table
        if isinstance(node, ast.Expression):
            return self.compile(node.body)
        if isinstance(node, ast.Constant):
            v = node.value
            if v is not None and not isinstance(v, str | int | float | bool):
                raise ExpressionError(f"unsupported literal {type(v).__name__}")
            if isinstance(v, str) and len(v) > MAX_STR:
                raise ExpressionError("string literal too long")
            return lambda s: v
        if isinstance(node, ast.Name):
            name = node.id
            if name in CONSTANT_NAMES:
                c = CONSTANT_NAMES[name]
                return lambda s: c
            if name.startswith("_"):
                raise ExpressionError(f"name {name!r} is not allowed")
            if name in FUNCTIONS:
                raise ExpressionError(f"{name} is a function; call it as {name}(...)")
            if self.allowed is not None and name not in self.allowed:
                raise ExpressionError(f"unknown name {name!r}")
            self.names.add(name)

            def load(s: Scope, name: str = name) -> Any:
                if name not in s:
                    raise ExpressionError(f"unknown name {name!r}")
                return s[name]
            return load
        if isinstance(node, ast.Attribute):
            attr = node.attr
            if attr.startswith("_"):
                raise ExpressionError(f"attribute {attr!r} is not allowed")
            base = self.compile(node.value)

            def get_attr(s: Scope) -> Any:
                obj = base(s)
                if obj is None:
                    return None
                if not isinstance(obj, Mapping):
                    raise ExpressionError(f"cannot read .{attr} of {type(obj).__name__}")
                return obj.get(attr)
            return get_attr
        if isinstance(node, ast.Subscript):
            base = self.compile(node.value)
            if isinstance(node.slice, ast.Slice):
                lo = self.compile(node.slice.lower) if node.slice.lower else (lambda s: None)
                hi = self.compile(node.slice.upper) if node.slice.upper else (lambda s: None)
                if node.slice.step is not None:
                    raise ExpressionError("slice steps are not supported")

                def get_slice(s: Scope) -> Any:
                    obj, a, b = base(s), lo(s), hi(s)
                    if obj is None:
                        return None
                    if not isinstance(obj, list | tuple | str):
                        raise ExpressionError(f"cannot slice {type(obj).__name__}")
                    for x in (a, b):
                        if x is not None and (isinstance(x, bool) or not isinstance(x, int)):
                            raise ExpressionError("slice bounds must be integers")
                    return obj[a:b]
                return get_slice
            idx = self.compile(node.slice)
            return lambda s: _get_key(base(s), idx(s))
        if isinstance(node, ast.BoolOp):
            parts = [self.compile(v) for v in node.values]
            if isinstance(node.op, ast.And):
                def and_(s: Scope) -> Any:
                    val: Any = True
                    for p in parts:
                        val = p(s)
                        if not val:
                            return val
                    return val
                return and_

            def or_(s: Scope) -> Any:
                val: Any = False
                for p in parts:
                    val = p(s)
                    if val:
                        return val
                return val
            return or_
        if isinstance(node, ast.UnaryOp):
            operand = self.compile(node.operand)
            if isinstance(node.op, ast.Not):
                return lambda s: not operand(s)
            if isinstance(node.op, ast.USub | ast.UAdd):
                neg = isinstance(node.op, ast.USub)

                def unary(s: Scope) -> Any:
                    v = operand(s)
                    if isinstance(v, bool) or not isinstance(v, int | float):
                        raise ExpressionError("unary +/- expects a number")
                    return -v if neg else v
                return unary
            raise ExpressionError(f"unsupported operator {type(node.op).__name__}")
        if isinstance(node, ast.BinOp):
            if not isinstance(node.op, _BINOPS):
                raise ExpressionError(f"operator {type(node.op).__name__} is not allowed")
            left, right, op = self.compile(node.left), self.compile(node.right), type(node.op)
            return lambda s: _arith(op, left(s), right(s))
        if isinstance(node, ast.Compare):
            for op in node.ops:
                if type(op) not in _CMP:
                    raise ExpressionError(f"comparison {type(op).__name__} is not allowed")
            ops = [_CMP[type(op)] for op in node.ops]
            for op, comp in zip(node.ops, node.comparators, strict=True):
                if isinstance(op, ast.Is | ast.IsNot) and not (isinstance(comp, ast.Constant) and comp.value is None
                                                                 or isinstance(comp, ast.Name) and comp.id in ("null", "none", "None")):
                    raise ExpressionError("'is' / 'is not' can only compare with null")
            first = self.compile(node.left)
            rest = [self.compile(c) for c in node.comparators]

            def compare(s: Scope) -> bool:
                a = first(s)
                for fn, nxt in zip(ops, rest, strict=True):
                    b = nxt(s)
                    if not fn(a, b):
                        return False
                    a = b
                return True
            return compare
        if isinstance(node, ast.Call):
            if not isinstance(node.func, ast.Name) or node.func.id not in FUNCTIONS:
                fname = node.func.id if isinstance(node.func, ast.Name) else type(node.func).__name__
                raise ExpressionError(f"function {fname!r} is not allowed (allowed: {', '.join(sorted(FUNCTIONS))})")
            if node.keywords:
                raise ExpressionError("keyword arguments are not supported")
            if len(node.args) > 4:
                raise ExpressionError("too many arguments")
            if any(isinstance(a, ast.Starred) for a in node.args):
                raise ExpressionError("*args is not supported")
            fn = FUNCTIONS[node.func.id]
            args = [self.compile(a) for a in node.args]

            def call(s: Scope) -> Any:
                try:
                    return _check_size(fn(*[a(s) for a in args]))
                except ExpressionError:
                    raise
                except (TypeError, ValueError, OverflowError) as e:
                    raise ExpressionError(f"{node.func.id}(): {e}") from e  # type: ignore[union-attr]
            return call
        if isinstance(node, ast.List | ast.Tuple):
            if len(node.elts) > MAX_LITERAL_ITEMS:
                raise ExpressionError("list literal too long")
            items = [self.compile(e) for e in node.elts]
            return lambda s: [i(s) for i in items]
        if isinstance(node, ast.IfExp):
            test, body, orelse = self.compile(node.test), self.compile(node.body), self.compile(node.orelse)
            return lambda s: body(s) if test(s) else orelse(s)
        raise ExpressionError(f"unsupported syntax: {type(node).__name__}")


class Expression:
    """A compiled boolean/value expression. ``evaluate(scope)`` → value, ``test(scope)`` → bool."""

    __slots__ = ("source", "names", "_fn")

    def __init__(self, source: str, fn: Fn, names: set[str]) -> None:
        self.source = source
        self._fn = fn
        self.names = frozenset(names)

    def evaluate(self, scope: Scope) -> Any:
        try:
            return self._fn(scope)
        except ExpressionError:
            raise
        except RecursionError as e:
            raise ExpressionError("expression too deeply nested") from e

    def test(self, scope: Scope) -> bool:
        return bool(self.evaluate(scope))


def compile_expression(source: str, *, allowed_names: set[str] | None = None) -> Expression:
    if not isinstance(source, str):
        raise ExpressionError("expression must be a string")
    src = source.strip()
    if not src:
        raise ExpressionError("expression is empty")
    if len(src) > MAX_EXPR_LEN:
        raise ExpressionError(f"expression longer than {MAX_EXPR_LEN} characters")
    try:
        tree = ast.parse(src, mode="eval")
    except SyntaxError as e:
        raise ExpressionError(f"syntax error: {e.msg}") from e
    except (RecursionError, MemoryError, ValueError) as e:
        raise ExpressionError("expression too complex") from e
    if sum(1 for _ in ast.walk(tree)) > MAX_AST_NODES:
        raise ExpressionError("expression too complex")
    comp = _Compiler(allowed_names)
    try:
        fn = comp.compile(tree)
    except RecursionError as e:
        raise ExpressionError("expression too deeply nested") from e
    return Expression(src, fn, comp.names)


@lru_cache(maxsize=512)
def _cached(source: str) -> Expression:
    return compile_expression(source)


def evaluate(source: str, scope: Scope) -> Any:
    return _cached(source).evaluate(scope)


def check_expression(source: str, allowed_names: set[str] | None = None) -> str | None:
    """None when the expression compiles, else a readable error."""
    try:
        compile_expression(source, allowed_names=allowed_names)
        return None
    except ExpressionError as e:
        return str(e)


# ============================================================================================ templates

class _SandboxEnv(ImmutableSandboxedEnvironment):
    intercepted_binops = frozenset({"*", "**", "+"})

    def is_safe_attribute(self, obj: Any, attr: str, value: Any) -> bool:
        if attr.startswith("_"):
            return False
        return super().is_safe_attribute(obj, attr, value)

    def unsafe_undefined(self, obj: Any, attribute: str) -> Undefined:
        raise SecurityError(f"access to attribute {attribute!r} is not allowed")

    def getattr(self, obj: Any, attribute: str) -> Any:
        if isinstance(attribute, str) and attribute.startswith("_"):
            raise SecurityError(f"access to attribute {attribute!r} is not allowed")
        return super().getattr(obj, attribute)

    def getitem(self, obj: Any, argument: Any) -> Any:
        if isinstance(argument, str) and argument.startswith("__"):
            raise SecurityError(f"access to key {argument!r} is not allowed")
        return super().getitem(obj, argument)

    def call_binop(self, context: Any, operator_: str, left: Any, right: Any) -> Any:
        if operator_ == "**":
            if isinstance(right, int | float) and abs(right) > 64 or isinstance(left, int | float) and abs(left) > 1e6:
                raise SecurityError("exponent too large")
            return left ** right
        if operator_ == "*":
            for seq, n in ((left, right), (right, left)):
                if isinstance(seq, str | list | tuple) and isinstance(n, int) and len(seq) * max(n, 0) > MAX_STR:
                    raise SecurityError("repetition result too long")
            return left * right
        res = left + right
        if isinstance(res, str | list | tuple) and len(res) > MAX_STR:
            raise SecurityError("concatenation result too long")
        return res


def _capped_range(*args: int) -> range:
    r = range(*args)
    if len(r) > MAX_RANGE:
        raise SecurityError(f"range() is limited to {MAX_RANGE} items")
    return r


_env = _SandboxEnv(undefined=ChainableUndefined, autoescape=False, trim_blocks=True, lstrip_blocks=True)
_env.globals.clear()
_env.globals.update({"range": _capped_range, **{k: v for k, v in FUNCTIONS.items() if k in
                                                   ("len", "lower", "upper", "contains", "date_diff", "min", "max")}})
_SINGLE = re.compile(r"^\s*\{\{(?P<expr>(?:(?!\}\}|\{\{).)*)\}\}\s*$", re.S)


def is_template(value: Any) -> bool:
    return isinstance(value, str) and ("{{" in value or "{%" in value)


@lru_cache(maxsize=512)
def _template(source: str) -> Any:
    return _env.from_string(source)


@lru_cache(maxsize=512)
def _native(expr: str) -> Any:
    return _env.compile_expression(expr, undefined_to_none=True)


def _plain(v: Any, _depth: int = 0) -> Any:
    """Native template results must be JSON-like (context data is); anything else is rejected."""
    if _depth > 30:
        raise ExpressionError("value nested too deeply")
    if v is None or isinstance(v, Undefined):
        return None
    if isinstance(v, float):
        return None if math.isnan(v) or math.isinf(v) else v
    if isinstance(v, bool | int):
        return v
    if isinstance(v, str):
        return str(v)
    if isinstance(v, list | tuple | range):
        return [_plain(x, _depth + 1) for x in v]
    if isinstance(v, dict):
        return {str(k): _plain(x, _depth + 1) for k, x in v.items()}
    raise ExpressionError(f"template produced an unsupported value ({type(v).__name__})")


def render_string(source: str, scope: Scope) -> Any:
    """Render one template string. ``"{{ expr }}"`` alone returns the native value; anything else a string."""
    if not is_template(source):
        return source
    if len(source) > MAX_STR:
        raise ExpressionError("template too long")
    try:
        m = _SINGLE.match(source)
        if m and "{%" not in source:
            return _plain(_native(m.group("expr").strip())(**dict(scope)))
        out: list[str] = []
        size = 0
        for chunk in _template(source).generate(**dict(scope)):
            size += len(chunk)
            if size > MAX_STR:
                raise ExpressionError("rendered template too long")
            out.append(chunk)
        return "".join(out)
    except ExpressionError:
        raise
    except SecurityError as e:
        raise ExpressionError(f"unsafe template: {e}") from e
    except TemplateError as e:
        raise ExpressionError(f"template error: {e}") from e
    except (TypeError, ValueError, ArithmeticError, LookupError) as e:
        raise ExpressionError(f"template error: {type(e).__name__}: {e}") from e
    except RecursionError as e:
        raise ExpressionError("template too deeply nested") from e


def render_value(value: Any, scope: Scope, *, skip_keys: frozenset[str] | set[str] = frozenset(), _depth: int = 0) -> Any:
    """Recursively render every template string inside ``value`` (dicts/lists). Keys in ``skip_keys`` are left raw
    at the top level (e.g. a condition's ``expression``)."""
    if _depth > 20:
        raise ExpressionError("config nested too deeply")
    if isinstance(value, str):
        return render_string(value, scope)
    if isinstance(value, dict):
        return {k: (v if _depth == 0 and k in skip_keys else render_value(v, scope, _depth=_depth + 1))
                for k, v in value.items()}
    if isinstance(value, list):
        return [render_value(v, scope, _depth=_depth + 1) for v in value]
    return value


def check_template(source: str) -> str | None:
    """None when the template parses (syntax only), else a readable error."""
    if not is_template(source):
        return None
    try:
        m = _SINGLE.match(source)
        if m and "{%" not in source:
            _env.compile_expression(m.group("expr").strip())
        else:
            _env.parse(source)
        return None
    except TemplateError as e:
        return f"template error: {e}"
    except RecursionError:
        return "template too deeply nested"

"""Sandboxed automation expressions/templates (doc 14 §14.5): what works, and what must be rejected."""
from __future__ import annotations

import random

import pytest

from app.workflows.expressions import (
    ExpressionError,
    check_expression,
    compile_expression,
    evaluate,
    render_string,
    render_value,
)

SCOPE = {
    "trigger": {"score": 85, "kinds": ["news", "web"], "label": "AI Billing", "trend": {"label": "AI billing"},
                "published_at": "2026-10-01T10:00:00Z"},
    "kinds": ["news"],
    "steps": {"i": {"ideas": [{"id": "idea-1", "title": "One"}, {"id": "idea-2", "title": "Two"}], "count": 2}},
    "brand": {"name": "Acme", "industry": None, "default_accounts": {"linkedin": "acc-1"}},
    "now": "2026-10-08T10:00:00+00:00",
}


@pytest.mark.parametrize("expr,expected", [
    ("trigger.score >= 80 and \"news\" in kinds", True),
    ("trigger.score >= 90 or len(trigger.kinds) == 2", True),
    ("not (trigger.score < 50)", True),
    ("1 + 2 * 3 - 4 / 2", 5.0),
    ("10 // 3 + 10 % 3", 4),
    ("2 ** 10", 1024),
    ("-trigger.score + 100", 15),
    ("\"a\" + \"b\" == \"ab\"", True),
    ("steps.i.ideas[0].id", "idea-1"),
    ("steps.i.ideas[-1][\"title\"]", "Two"),
    ("steps.i.ideas[5]", None),
    ("steps.i.ideas[0:1]", [{"id": "idea-1", "title": "One"}]),
    ("lower(trigger.label) == \"ai billing\"", True),
    ("upper(\"x\")", "X"),
    ("contains(trigger.kinds, \"web\") and contains(trigger.label, \"Bill\")", True),
    ("date_diff(now, trigger.published_at, \"days\")", 7.0),
    ("date_diff(now, trigger.published_at, \"hours\") > 100", True),
    ("brand.industry is null", True),
    ("brand.industry is not none", False),
    ("trigger.missing.deeper >= 3", False),       # missing data never raises, compares False
    ("trigger.missing == null", True),
    ("\"yes\" if trigger.score > 50 else \"no\"", "yes"),
    ("[1, 2, 3][1]", 2),
    ("min(3, 1, 2) + max([4, 5])", 6),
    ("round(2.456, 1)", 2.5),
    ("int(\"42\") + float(\"0.5\")", 42.5),
    ("1 < 2 < 3", True),
    ("true and not false", True),
])
def test_valid_expressions(expr, expected):
    assert evaluate(expr, SCOPE) == expected


@pytest.mark.parametrize("expr", [
    "trigger.__class__",
    "trigger._private",
    "steps.i.ideas[0].__class__.__mro__",
    "__import__(\"os\")",
    "__builtins__",
    "_x",
    "open(\"/etc/passwd\")",
    "eval(\"1\")",
    "exec(\"1\")",
    "getattr(trigger, \"x\")",
    "trigger.label.upper()",
    "(lambda: 1)()",
    "[x for x in kinds]",
    "{k: 1 for k in kinds}",
    "f\"{trigger}\"",
    "x := 1",
    "*kinds",
    "unknown_name > 1",
    "len",
    "\"a\" * 10 ** 9",
    "[1] * 100000000",
    "10 ** 1000",
    "1 / 0",
    "len(5)",
    "date_diff(now, \"not a date\")",
    "date_diff(now, now, \"fortnights\")",
    "trigger[\"__class__\"]",
    "\"x\".join",
    "1 if",
    "",
    "a" * 3000,
    "(" * 400 + "1" + ")" * 400,
    "trigger.label is \"x\"",
    "contains(5, 1)",
    "len(kinds, kinds, kinds, kinds, kinds)",
])
def test_rejected_expressions(expr):
    with pytest.raises(ExpressionError):
        evaluate(expr, SCOPE)


def test_unknown_names_rejected_at_compile_time_with_allowlist():
    assert check_expression("trigger.score > 1", {"trigger"}) is None
    assert "unknown name" in (check_expression("secrets > 1", {"trigger"}) or "")
    exp = compile_expression("trigger.score > 1 and len(kinds) > 0")
    assert exp.names == {"trigger", "kinds"}


def test_attribute_access_is_key_lookup_only():
    class Obj:
        secret = "s3cret"
    with pytest.raises(ExpressionError):
        evaluate("o.secret", {"o": Obj()})
    assert evaluate("o.secret", {"o": {"secret": "ok"}}) == "ok"


def test_fuzz_only_raises_expression_errors():
    rnd = random.Random(1234)
    tokens = ["trigger", ".", "score", "kinds", "steps", "[", "]", "(", ")", "0", "1", "-1", "\"x\"", "+", "-", "*", "/",
              "**", "%", "and", "or", "not", "in", "==", ">=", "<", "len", "lower", "contains", "date_diff", ",", "__class__",
              "_x", "lambda", ":", "if", "else", "null", "true", "import", "os", "{", "}", "'", "\\", "@", "is", "None"]
    for _ in range(3000):
        src = " ".join(rnd.choice(tokens) for _ in range(rnd.randint(1, 12)))
        try:
            evaluate(src, SCOPE)
        except ExpressionError:
            pass


# ------------------------------------------------------------------------------------------------ templates

def test_template_native_and_string_rendering():
    assert render_string("{{ steps.i.ideas[0].id }}", SCOPE) == "idea-1"
    assert render_string("{{ steps.i.ideas }}", SCOPE) == SCOPE["steps"]["i"]["ideas"]
    assert render_string("{{ steps.i.count }}", SCOPE) == 2
    assert render_string("Hot: {{ trigger.trend.label }} ({{ trigger.score }})", SCOPE) == "Hot: AI billing (85)"
    assert render_string("{{ brand.default_accounts.linkedin }}", SCOPE) == "acc-1"
    assert render_string("{{ brand.default_accounts.tiktok }}", SCOPE) is None
    assert render_string("{{ nothing.at.all }}", SCOPE) is None
    assert render_string("{% for i in steps.i.ideas %}{{ i.title }};{% endfor %}", SCOPE) == "One;Two;"
    assert render_string("{{ brand.industry or brand.name }} news", SCOPE) == "Acme news"
    assert render_string("plain text", SCOPE) == "plain text"


def test_render_value_recurses_and_skips_raw_keys():
    cfg = {"expression": "{{ not rendered }}", "nested": {"a": ["{{ trigger.score }}", "x"]}, "n": 3}
    out = render_value(cfg, SCOPE, skip_keys={"expression"})
    assert out == {"expression": "{{ not rendered }}", "nested": {"a": [85, "x"]}, "n": 3}


@pytest.mark.parametrize("src", [
    "{{ ''.__class__.__mro__[1].__subclasses__() }}",
    "{{ trigger.__class__ }}",
    "{{ trigger['__class__'] }}",
    "{{ trigger._private }}",
    "{{ trigger.update({'x': 1}) }}",
    "{{ steps.i.ideas.append(1) }}",
    "{{ steps.i.ideas.pop() }}",
    "{% for i in range(100000) %}x{% endfor %}",
    "{{ 'a' * 1000000 }}",
    "{{ 10 ** 100 }}",
    "{% for i in range(1000) %}{% for j in range(1000) %}xxxxxxxxxx{% endfor %}{% endfor %}",
    "{{ broken ",
    "{% if %}",
])
def test_template_escapes_and_abuse_rejected(src):
    with pytest.raises(ExpressionError):
        render_string(src, SCOPE)


@pytest.mark.parametrize("src", ["{{ lipsum.__globals__ }}", "{{ cycler.__init__.__globals__ }}", "{{ joiner }}",
                                 "{{ namespace }}", "{{ self }}", "{{ config }}", "{{ request }}"])
def test_template_dangerous_globals_unavailable(src):
    try:
        out = render_string(src, SCOPE)
    except ExpressionError:
        return
    assert out in (None, "")

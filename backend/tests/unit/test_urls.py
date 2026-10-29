"""URL canonicalization and domain helpers."""
from __future__ import annotations

import pytest

from app.research.urls import (
    canonicalize,
    domain_of,
    matches_domain,
    registrable_domain,
    safe_canonicalize,
    same_site,
)


@pytest.mark.parametrize(("raw", "expected"), [
    ("HTTPS://Example.COM/Path/", "https://example.com/Path"),
    ("https://example.com", "https://example.com/"),
    ("https://example.com/", "https://example.com/"),
    ("http://example.com:80/a", "http://example.com/a"),
    ("https://example.com:443/a", "https://example.com/a"),
    ("https://example.com:8443/a", "https://example.com:8443/a"),
    ("https://example.com/a?utm_source=x&utm_medium=y&b=2&a=1", "https://example.com/a?a=1&b=2"),
    ("https://example.com/a?fbclid=abc&gclid=def&ref=hn", "https://example.com/a"),
    ("https://example.com/a#section-2", "https://example.com/a"),
    ("https://example.com/a/./b/../c", "https://example.com/a/c"),
    ("https://example.com//double//slash/", "https://example.com/double/slash"),
    ("https://example.com/a%2fb", "https://example.com/a%2Fb"),
    ("https://example.com/a b", "https://example.com/a%20b"),
    ("example.com/blog/", "https://example.com/blog"),
    ("https://bücher.de/x", "https://xn--bcher-kva.de/x"),
    ("https://example.com/?q=", "https://example.com/?q="),
])
def test_canonicalize(raw: str, expected: str) -> None:
    assert canonicalize(raw) == expected


def test_canonicalize_is_idempotent() -> None:
    for u in ("https://Example.com/A/b/?z=1&a=2&utm_campaign=q#x", "http://news.bbc.co.uk/1/hi/"):
        assert canonicalize(canonicalize(u)) == canonicalize(u)


def test_safe_canonicalize_rejects_non_http() -> None:
    assert safe_canonicalize("ftp://example.com/x") is None
    assert safe_canonicalize("mailto:a@b.c") is None
    assert safe_canonicalize("https://example.com/x") == "https://example.com/x"


def test_domains() -> None:
    assert domain_of("https://www.Example.com/x") == "example.com"
    assert domain_of("blog.example.com") == "blog.example.com"
    assert registrable_domain("https://news.bbc.co.uk/x") == "bbc.co.uk"
    assert registrable_domain("a.b.example.com") == "example.com"
    assert same_site("https://blog.acme.io/x", "https://www.acme.io/")
    assert not same_site("https://acme.io", "https://acme.com")
    assert matches_domain("https://docs.python.org/3/", ["python.org"])
    assert matches_domain("www.reddit.com", ["https://reddit.com/"])
    assert not matches_domain("notreddit.com", ["reddit.com"])

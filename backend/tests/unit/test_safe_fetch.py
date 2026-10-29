"""SafeFetcher SSRF guard: private ranges (IPv4/IPv6/mapped/metadata), scheme/host rules, redirect re-validation,
size and content-type caps, robots.txt."""
from __future__ import annotations

import httpx
import pytest
import respx

from app.core.resilience import CircuitBreaker, ResilienceError, ResilientClient
from app.core.safe_fetch import (
    ContentTypeNotAllowedError,
    RobotsDisallowedError,
    SafeFetcher,
    UnsafeURLError,
    ip_block_reason,
    is_public_ip,
)

BLOCKED = [
    "127.0.0.1", "127.8.9.10", "10.0.0.5", "172.16.3.4", "192.168.1.1", "169.254.169.254", "169.254.1.1", "0.0.0.0",
    "100.64.0.1", "224.0.0.1", "240.0.0.1", "255.255.255.255", "192.0.0.192", "100.100.100.200",
    "::1", "::", "fe80::1", "fc00::1", "fd12:3456::1", "fd00:ec2::254", "ff02::1",
    "::ffff:127.0.0.1", "::ffff:10.0.0.1", "::ffff:169.254.169.254", "64:ff9b::a00:1", "2002:a00:1::1", "::127.0.0.1",
]
PUBLIC = ["93.184.216.34", "8.8.8.8", "1.1.1.1", "2606:4700:4700::1111", "2a00:1450:4001:80b::200e", "::ffff:8.8.8.8"]


def make_fetcher(mapping: dict[str, list[str]], **kw) -> SafeFetcher:
    async def resolver(host: str, port: int) -> list[str]:
        if host not in mapping:
            raise OSError(f"unknown host {host}")
        return mapping[host]

    async def nosleep(_s: float) -> None:
        return None

    return SafeFetcher(resolver=resolver, rate_per_host=0, sleep=nosleep, **kw)


@pytest.mark.parametrize("ip", BLOCKED)
def test_blocked_addresses(ip: str) -> None:
    assert ip_block_reason(ip) is not None, ip
    assert not is_public_ip(ip)


@pytest.mark.parametrize("ip", PUBLIC)
def test_public_addresses(ip: str) -> None:
    assert ip_block_reason(ip) is None, ip


async def test_metadata_reason_is_explicit() -> None:
    assert "metadata" in (ip_block_reason("169.254.169.254") or "")
    assert "metadata" in (ip_block_reason("fd00:ec2::254") or "")


@pytest.mark.parametrize("url", [
    "file:///etc/passwd", "ftp://example.com/x", "gopher://example.com/", "javascript:alert(1)", "http://localhost/",
    "http://foo.localhost/", "http://metadata.google.internal/computeMetadata/v1/", "http://user:pass@example.com/",
    "http://127.0.0.1:8080/", "http://[::1]/", "http://[::ffff:7f00:1]/", "http://169.254.169.254/latest/meta-data/",
    "http://[fd00:ec2::254]/", "http://internal.test/",
])
async def test_validate_url_rejects(url: str) -> None:
    f = make_fetcher({"internal.test": ["10.1.2.3"], "example.com": ["93.184.216.34"]})
    with pytest.raises(UnsafeURLError):
        await f.validate_url(url)


async def test_validate_url_rejects_if_any_address_private() -> None:
    f = make_fetcher({"dual.test": ["93.184.216.34", "192.168.0.10"]})
    with pytest.raises(UnsafeURLError):
        await f.validate_url("https://dual.test/")


async def test_validate_url_accepts_public() -> None:
    f = make_fetcher({"example.com": ["93.184.216.34", "2606:2800:220:1:248:1893:25c8:1946"]})
    assert await f.validate_url("https://example.com/page?q=1")


@respx.mock
async def test_redirect_to_private_host_is_blocked() -> None:
    f = make_fetcher({"public.test": ["93.184.216.34"], "evil-internal.test": ["10.0.0.7"]}, respect_robots=False)
    respx.get("https://public.test/start").mock(return_value=httpx.Response(302, headers={"Location": "http://evil-internal.test/admin"}))
    internal = respx.get("http://evil-internal.test/admin").mock(return_value=httpx.Response(200, text="secret"))
    with pytest.raises(UnsafeURLError):
        await f.fetch("https://public.test/start")
    assert not internal.called


@respx.mock
async def test_redirect_to_metadata_ip_literal_is_blocked() -> None:
    f = make_fetcher({"public2.test": ["93.184.216.34"]}, respect_robots=False)
    respx.get("https://public2.test/r").mock(return_value=httpx.Response(301, headers={"Location": "http://169.254.169.254/latest/"}))
    with pytest.raises(UnsafeURLError):
        await f.fetch("https://public2.test/r")


@respx.mock
async def test_redirect_chain_followed_and_revalidated() -> None:
    f = make_fetcher({"a.test": ["93.184.216.34"], "b.test": ["93.184.216.35"]}, respect_robots=False)
    respx.get("https://a.test/1").mock(return_value=httpx.Response(302, headers={"Location": "/2"}))
    respx.get("https://a.test/2").mock(return_value=httpx.Response(307, headers={"Location": "https://b.test/final"}))
    respx.get("https://b.test/final").mock(return_value=httpx.Response(200, headers={"Content-Type": "text/html"},
                                                                       text="<html><body>ok</body></html>"))
    res = await f.fetch("https://a.test/1")
    assert res.final_url == "https://b.test/final"
    assert res.redirects == ["https://a.test/2", "https://b.test/final"]
    assert res.status == 200 and b"ok" in res.content


@respx.mock
async def test_too_many_redirects() -> None:
    f = make_fetcher({"loop.test": ["93.184.216.34"]}, respect_robots=False)
    for i in range(10):
        respx.get(f"https://loop.test/{i}").mock(return_value=httpx.Response(302, headers={"Location": f"/{i + 1}"}))
    with pytest.raises(ResilienceError) as ei:
        await f.fetch("https://loop.test/0")
    assert ei.value.code == "too_many_redirects"


@respx.mock
async def test_size_cap_by_content_length_and_stream() -> None:
    f = make_fetcher({"big.test": ["93.184.216.34"]}, respect_robots=False, max_bytes=1000)
    respx.get("https://big.test/declared").mock(return_value=httpx.Response(
        200, headers={"Content-Type": "text/html", "Content-Length": "5000"}, content=b"x" * 5000))
    with pytest.raises(ResilienceError) as e1:
        await f.fetch("https://big.test/declared")
    assert e1.value.code == "too_large"

    def streamed(_request: httpx.Request) -> httpx.Response:
        async def gen():
            for _ in range(10):
                yield b"y" * 300
        return httpx.Response(200, headers={"Content-Type": "text/html"}, content=gen())

    respx.get("https://big.test/stream").mock(side_effect=streamed)
    with pytest.raises(ResilienceError) as e2:
        await f.fetch("https://big.test/stream")
    assert e2.value.code == "too_large"


@respx.mock
async def test_content_type_allowlist() -> None:
    f = make_fetcher({"bin.test": ["93.184.216.34"]}, respect_robots=False)
    respx.get("https://bin.test/app.exe").mock(return_value=httpx.Response(
        200, headers={"Content-Type": "application/octet-stream"}, content=b"MZ"))
    with pytest.raises(ContentTypeNotAllowedError):
        await f.fetch("https://bin.test/app.exe")
    respx.get("https://bin.test/doc.pdf").mock(return_value=httpx.Response(
        200, headers={"Content-Type": "application/pdf"}, content=b"%PDF-1.4"))
    assert (await f.fetch("https://bin.test/doc.pdf")).is_pdf


@respx.mock
async def test_robots_txt_respected_in_crawl_and_fetch_modes() -> None:
    f = make_fetcher({"robots.test": ["93.184.216.34"]})
    respx.get("https://robots.test/robots.txt").mock(return_value=httpx.Response(
        200, headers={"Content-Type": "text/plain"}, text="User-agent: *\nDisallow: /private\n"))
    page = respx.get("https://robots.test/private/x").mock(return_value=httpx.Response(
        200, headers={"Content-Type": "text/html"}, text="<p>hi</p>"))
    respx.get("https://robots.test/public").mock(return_value=httpx.Response(
        200, headers={"Content-Type": "text/html"}, text="<p>ok</p>"))
    with pytest.raises(RobotsDisallowedError):
        await f.fetch("https://robots.test/private/x", mode="crawl")
    with pytest.raises(RobotsDisallowedError):
        await f.fetch("https://robots.test/private/x")  # single-URL fetch honors robots by default
    assert not page.called
    # crawl mode ignores an attempted opt-out; explicit single-URL opt-out works
    with pytest.raises(RobotsDisallowedError):
        await f.fetch("https://robots.test/private/x", mode="crawl", respect_robots=False)
    res = await f.fetch("https://robots.test/private/x", respect_robots=False)
    assert res.status == 200
    assert (await f.fetch("https://robots.test/public", mode="crawl")).status == 200


@respx.mock
async def test_robots_missing_allows_and_unreachable_disallows() -> None:
    f = make_fetcher({"norobots.test": ["93.184.216.34"], "down.test": ["93.184.216.36"]})
    respx.get("https://norobots.test/robots.txt").mock(return_value=httpx.Response(404))
    respx.get("https://norobots.test/a").mock(return_value=httpx.Response(200, headers={"Content-Type": "text/html"}, text="a"))
    assert (await f.fetch("https://norobots.test/a", mode="crawl")).status == 200
    respx.get("https://down.test/robots.txt").mock(return_value=httpx.Response(503))
    with pytest.raises(RobotsDisallowedError):
        await f.fetch("https://down.test/a", mode="crawl")


@respx.mock
async def test_resilient_client_retries_then_breaker_opens() -> None:
    sleeps: list[float] = []

    async def fake_sleep(s: float) -> None:
        sleeps.append(s)

    breaker = CircuitBreaker(failure_threshold=5, reset_after_s=30)
    client = ResilientClient(breaker=breaker, rate_per_host=0, sleep=fake_sleep, attempts=3)
    route = respx.get("https://flaky.test/x").mock(side_effect=[httpx.Response(503), httpx.Response(502), httpx.Response(200, text="ok")])
    resp = await client.get("https://flaky.test/x")
    assert resp.status_code == 200 and route.call_count == 3 and len(sleeps) == 2
    respx.get("https://dead.test/x").mock(return_value=httpx.Response(500))
    for _ in range(2):
        with pytest.raises(ResilienceError):
            await client.get("https://dead.test/x")
    assert breaker.state("dead.test") == "open"
    with pytest.raises(ResilienceError) as ei:
        await client.get("https://dead.test/x")
    assert ei.value.code == "circuit_open"
    await client.aclose()


@respx.mock
async def test_resilient_client_error_mapping() -> None:
    client = ResilientClient(rate_per_host=0, attempts=1, breaker=CircuitBreaker())
    respx.get("https://auth.test/x").mock(return_value=httpx.Response(401))
    with pytest.raises(ResilienceError) as ei:
        await client.get("https://auth.test/x")
    assert ei.value.category == "auth" and ei.value.status == 401
    respx.get("https://conn.test/x").mock(side_effect=httpx.ConnectError("boom"))
    with pytest.raises(ResilienceError) as ec:
        await client.get("https://conn.test/x")
    assert ec.value.category == "transient"
    await client.aclose()

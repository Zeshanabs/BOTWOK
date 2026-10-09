"""SafeFetcher — the only way research code fetches arbitrary URLs (doc 19 §19.5 SSRF guard).

* scheme allowlist (http/https), no userinfo, sane ports
* DNS is resolved first (asyncio getaddrinfo) and EVERY resolved address must be public: private, loopback, link-local,
  multicast, reserved, unspecified, CGNAT, IPv6 ULA/site-local, IPv4-mapped / 6to4 / Teredo / NAT64 embedded IPv4 and cloud
  metadata endpoints (169.254.169.254, fd00:ec2::254, …) are rejected
* redirects are followed manually (max 5) and each hop is re-validated
* 5 MB size cap enforced while streaming; content-type allowlist checked before the body is read
* identifies itself with a Botwok UA and honors robots.txt (cached per host for 1 h)

Residual risk: a DNS-rebinding attacker could return a different address between our check and httpx's own resolution.
Deployments run research workers in an egress-restricted network namespace as the second layer (doc 19 §19.5).
"""
from __future__ import annotations

import asyncio
import ipaddress
import socket
import time
import urllib.robotparser
from collections.abc import Awaitable, Callable, Iterable
from dataclasses import dataclass, field
from urllib.parse import urljoin, urlsplit, urlunsplit

import httpx

from app.core.logging import get_logger
from app.core.resilience import ErrorCategory, HostLimiterRegistry, ResilienceError, ResilientClient

log = get_logger("safe_fetch")

USER_AGENT = "BotwokResearch/0.1 (+https://botwok.dev/bot)"
ROBOTS_AGENT = "BotwokResearch"
MAX_BYTES = 5 * 1024 * 1024
MAX_REDIRECTS = 5
ROBOTS_TTL_S = 3600
ALLOWED_CONTENT_TYPES = frozenset({
    "text/html", "application/xhtml+xml", "text/plain", "application/pdf", "application/rss+xml",
    "application/atom+xml", "application/xml", "text/xml", "application/json",
})
METADATA_IPS = frozenset({
    ipaddress.ip_address("169.254.169.254"),   # AWS / GCP / Azure / OpenStack
    ipaddress.ip_address("169.254.170.2"),     # AWS ECS task metadata
    ipaddress.ip_address("169.254.169.123"),   # AWS time sync
    ipaddress.ip_address("100.100.100.200"),   # Alibaba Cloud
    ipaddress.ip_address("192.0.0.192"),       # Oracle Cloud
    ipaddress.ip_address("fd00:ec2::254"),     # AWS IMDS over IPv6
    ipaddress.ip_address("fd00:ec2::23"),      # AWS DNS over IPv6
})
BLOCKED_HOST_SUFFIXES = (".localhost", ".local", ".internal", ".intranet", ".lan", ".home.arpa", ".corp")
BLOCKED_HOSTS = frozenset({"localhost", "metadata", "metadata.google.internal", "instance-data", "ip6-localhost",
                           "ip6-loopback"})
_NAT64 = ipaddress.ip_network("64:ff9b::/96")
_NAT64_LOCAL = ipaddress.ip_network("64:ff9b:1::/48")

Resolver = Callable[[str, int], Awaitable[list[str]]]


class UnsafeURLError(ResilienceError):
    def __init__(self, message: str, url: str | None = None):
        super().__init__(ErrorCategory.VALIDATION, message, url=url, code="unsafe_url")


class RobotsDisallowedError(ResilienceError):
    def __init__(self, url: str):
        super().__init__(ErrorCategory.PERMANENT, "disallowed by robots.txt", url=url, code="robots_disallowed")


class ContentTypeNotAllowedError(ResilienceError):
    def __init__(self, url: str, content_type: str):
        super().__init__(ErrorCategory.UNSUPPORTED, f"content-type not allowed: {content_type}", url=url, code="content_type")


@dataclass
class FetchResult:
    url: str
    final_url: str
    status: int
    content_type: str
    headers: dict[str, str]
    content: bytes
    redirects: list[str] = field(default_factory=list)
    elapsed_ms: int = 0

    @property
    def encoding(self) -> str:
        ct = self.headers.get("content-type", "")
        for part in ct.split(";")[1:]:
            k, _, v = part.strip().partition("=")
            if k.lower() == "charset" and v:
                return v.strip("\"' ")
        return "utf-8"

    @property
    def text(self) -> str:
        try:
            return self.content.decode(self.encoding, errors="replace")
        except LookupError:
            return self.content.decode("utf-8", errors="replace")

    @property
    def is_pdf(self) -> bool:
        return self.content_type == "application/pdf" or self.content[:5] == b"%PDF-"


def _embedded_ipv4(ip: ipaddress.IPv6Address) -> ipaddress.IPv4Address | None:
    if ip.ipv4_mapped is not None:
        return ip.ipv4_mapped
    if ip.sixtofour is not None:
        return ip.sixtofour
    if ip.teredo is not None:
        return ip.teredo[1]
    if ip in _NAT64 or ip in _NAT64_LOCAL:
        return ipaddress.IPv4Address(int(ip) & 0xFFFFFFFF)
    # IPv4-compatible (deprecated) ::a.b.c.d
    if int(ip) >> 32 == 0 and int(ip) > 1:
        return ipaddress.IPv4Address(int(ip) & 0xFFFFFFFF)
    return None


def ip_block_reason(addr: str | ipaddress.IPv4Address | ipaddress.IPv6Address) -> str | None:
    """Return why an address is not allowed as a fetch target, or None if it is a public unicast address."""
    try:
        ip = ipaddress.ip_address(addr) if isinstance(addr, str) else addr
    except ValueError:
        return "invalid address"
    if isinstance(ip, ipaddress.IPv6Address):
        if ip.scope_id:
            return "scoped ipv6"
        if ip in METADATA_IPS:
            return "cloud metadata"
        v4 = _embedded_ipv4(ip)
        if v4 is not None:
            inner = ip_block_reason(v4)
            return f"embedded ipv4 {inner}" if inner else None
    if ip in METADATA_IPS:
        return "cloud metadata"
    checks = (("loopback", ip.is_loopback), ("private", ip.is_private), ("link-local", ip.is_link_local),
              ("multicast", ip.is_multicast), ("reserved", ip.is_reserved), ("unspecified", ip.is_unspecified))
    for name, hit in checks:
        if hit:
            return name
    if isinstance(ip, ipaddress.IPv6Address) and ip.is_site_local:
        return "site-local"
    if not ip.is_global:
        return "non-global"
    return None


def is_public_ip(addr: str) -> bool:
    return ip_block_reason(addr) is None


async def system_resolver(host: str, port: int) -> list[str]:
    loop = asyncio.get_running_loop()
    infos = await loop.getaddrinfo(host, port, type=socket.SOCK_STREAM, proto=socket.IPPROTO_TCP)
    return sorted({str(info[4][0]) for info in infos})


def _norm_content_type(raw: str | None) -> str:
    return (raw or "").split(";", 1)[0].strip().lower()


@dataclass
class _RobotsEntry:
    parser: urllib.robotparser.RobotFileParser | None  # None = allow all
    disallow_all: bool
    fetched_at: float


class SafeFetcher:
    def __init__(self, client: ResilientClient | None = None, *, resolver: Resolver | None = None,
                 max_bytes: int = MAX_BYTES, max_redirects: int = MAX_REDIRECTS, user_agent: str = USER_AGENT,
                 allowed_content_types: Iterable[str] = ALLOWED_CONTENT_TYPES, respect_robots: bool = True,
                 robots_ttl_s: float = ROBOTS_TTL_S, transport: httpx.AsyncBaseTransport | None = None,
                 attempts: int = 3, read_timeout: float = 30.0, rate_per_host: float = 1.0, concurrency_per_host: int = 2,
                 sleep: Callable[[float], Awaitable[object]] | None = None):
        self.resolver = resolver or system_resolver
        self.max_bytes = max_bytes
        self.max_redirects = max_redirects
        self.user_agent = user_agent
        self.allowed_content_types = frozenset(allowed_content_types)
        self.respect_robots = respect_robots
        self.robots_ttl_s = robots_ttl_s
        self._own_client = client is None
        kwargs: dict = {"sleep": sleep} if sleep is not None else {}
        self.client = client or ResilientClient(
            headers={"User-Agent": user_agent, "Accept": "text/html,application/xhtml+xml,application/pdf;q=0.9,"
                                                          "application/xml;q=0.8,text/plain;q=0.7,*/*;q=0.1",
                     "Accept-Language": "en;q=1.0, *;q=0.5"},
            transport=transport, attempts=attempts, read_timeout=read_timeout,
            limiters=HostLimiterRegistry(rate_per_s=rate_per_host, concurrency=concurrency_per_host),
            follow_redirects=False, trust_env=False, **kwargs)
        self._robots: dict[str, _RobotsEntry] = {}

    async def __aenter__(self) -> SafeFetcher:
        return self

    async def __aexit__(self, *exc: object) -> None:
        await self.aclose()

    async def aclose(self) -> None:
        if self._own_client:
            await self.client.aclose()

    # ------------------------------------------------------------------ validation
    async def validate_url(self, url: str) -> list[str]:
        """Raise UnsafeURLError unless ``url`` is http(s) and every address its host resolves to is public."""
        try:
            parts = urlsplit(url)
        except ValueError as e:
            raise UnsafeURLError(f"unparseable url: {e}", url) from e
        if parts.scheme.lower() not in ("http", "https"):
            raise UnsafeURLError(f"scheme not allowed: {parts.scheme or '(none)'}", url)
        if parts.username or parts.password:
            raise UnsafeURLError("credentials in url are not allowed", url)
        host = (parts.hostname or "").strip().rstrip(".").lower()
        if not host:
            raise UnsafeURLError("missing host", url)
        try:
            port = parts.port or (443 if parts.scheme.lower() == "https" else 80)
        except ValueError as e:
            raise UnsafeURLError("invalid port", url) from e
        if host in BLOCKED_HOSTS or host.endswith(BLOCKED_HOST_SUFFIXES):
            raise UnsafeURLError(f"host not allowed: {host}", url)
        literal: str | None = None
        try:
            literal = str(ipaddress.ip_address(host.strip("[]")))
        except ValueError:
            literal = None
        if literal is not None:
            addrs = [literal]
        else:
            try:
                addrs = await self.resolver(host, port)
            except (OSError, UnicodeError) as e:
                raise ResilienceError(ErrorCategory.PERMANENT, f"dns resolution failed for {host}: {e}", host=host, url=url,
                                      code="dns") from e
        if not addrs:
            raise ResilienceError(ErrorCategory.PERMANENT, f"no addresses for {host}", host=host, url=url, code="dns")
        for a in addrs:
            reason = ip_block_reason(a)
            if reason:
                raise UnsafeURLError(f"{host} resolves to a blocked address ({reason})", url)
        return addrs

    # ------------------------------------------------------------------ robots.txt
    async def allowed_by_robots(self, url: str) -> bool:
        parts = urlsplit(url)
        origin = f"{parts.scheme.lower()}://{(parts.netloc or '').lower()}"
        now = time.monotonic()
        entry = self._robots.get(origin)
        if entry is None or now - entry.fetched_at > self.robots_ttl_s:
            entry = await self._load_robots(origin)
            if len(self._robots) > 5000:  # bound the per-process cache
                self._robots.clear()
            self._robots[origin] = entry
        if entry.disallow_all:
            return False
        if entry.parser is None:
            return True
        return entry.parser.can_fetch(ROBOTS_AGENT, url)

    async def _load_robots(self, origin: str) -> _RobotsEntry:
        robots_url = origin + "/robots.txt"
        now = time.monotonic()
        try:
            res = await self._fetch_raw(robots_url, accept_types=None, max_bytes=512 * 1024, attempts=1)
        except ResilienceError as e:  # includes UnsafeURLError on a redirect hop → treated as unreachable
            # RFC 9309: unreachable (5xx / network) → assume complete disallow; 4xx → no restrictions.
            if e.status is not None and 400 <= e.status < 500:
                return _RobotsEntry(None, False, now)
            log.info("robots.unreachable", origin=origin, error=e.message)
            return _RobotsEntry(None, True, now)
        if 400 <= res.status < 500:
            return _RobotsEntry(None, False, now)
        if res.status >= 500:
            return _RobotsEntry(None, True, now)
        rp = urllib.robotparser.RobotFileParser()
        rp.parse(res.text.splitlines())
        return _RobotsEntry(rp, False, now)

    # ------------------------------------------------------------------ fetching
    async def _fetch_raw(self, url: str, *, accept_types: frozenset[str] | None, max_bytes: int,
                         attempts: int | None = None, extra_headers: dict[str, str] | None = None) -> FetchResult:
        started = time.monotonic()
        redirects: list[str] = []
        current = url

        def check_headers(resp: httpx.Response) -> None:
            if resp.is_redirect or resp.status_code >= 400 or accept_types is None:
                return
            ct = _norm_content_type(resp.headers.get("content-type"))
            if ct and ct not in accept_types:
                raise ContentTypeNotAllowedError(current, ct)

        for _hop in range(self.max_redirects + 1):
            await self.validate_url(current)
            resp = await self.client.request("GET", current, raise_for_status=False, max_bytes=max_bytes,
                                             on_headers=check_headers, attempts=attempts, headers=extra_headers or None)
            if resp.is_redirect and resp.headers.get("location"):
                nxt = urljoin(current, resp.headers["location"].strip())
                p = urlsplit(nxt)
                nxt = urlunsplit((p.scheme, p.netloc, p.path or "/", p.query, ""))
                redirects.append(nxt)
                current = nxt
                continue
            if resp.status_code >= 400:
                cat = ErrorCategory.RATE_LIMITED if resp.status_code == 429 else (
                    ErrorCategory.TRANSIENT if resp.status_code >= 500 else ErrorCategory.PERMANENT)
                raise ResilienceError(cat, f"HTTP {resp.status_code}", status=resp.status_code,
                                      host=urlsplit(current).hostname, url=current)
            headers = {k.lower(): v for k, v in resp.headers.items()}
            return FetchResult(url=url, final_url=current, status=resp.status_code,
                               content_type=_norm_content_type(resp.headers.get("content-type")), headers=headers,
                               content=resp.content, redirects=redirects,
                               elapsed_ms=int((time.monotonic() - started) * 1000))
        raise ResilienceError(ErrorCategory.PERMANENT, f"too many redirects (>{self.max_redirects})", url=url,
                              code="too_many_redirects")

    async def fetch(self, url: str, *, mode: str = "fetch", respect_robots: bool | None = None,
                    allowed_content_types: Iterable[str] | None = None, max_bytes: int | None = None,
                    headers: dict[str, str] | None = None) -> FetchResult:
        """Fetch one URL safely. ``mode="crawl"`` always honors robots.txt; ``mode="fetch"`` honors it unless
        ``respect_robots=False`` is passed explicitly for a single user-supplied URL."""
        honor = True if mode == "crawl" else (self.respect_robots if respect_robots is None else respect_robots)
        await self.validate_url(url)
        if honor and not await self.allowed_by_robots(url):
            raise RobotsDisallowedError(url)
        types = frozenset(allowed_content_types) if allowed_content_types is not None else self.allowed_content_types
        return await self._fetch_raw(url, accept_types=types, max_bytes=max_bytes or self.max_bytes, extra_headers=headers)


_shared: SafeFetcher | None = None


def get_fetcher() -> SafeFetcher:
    """Process-wide fetcher (robots cache + per-host politeness shared across jobs)."""
    global _shared
    if _shared is None:
        _shared = SafeFetcher()
    return _shared

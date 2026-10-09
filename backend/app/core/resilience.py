"""ResilientClient — httpx.AsyncClient wrapper with timeouts, retries, circuit breaker and per-host politeness (doc 28 §28.1).

* connect timeout 5 s, read timeout 30 s
* retries (default 3 attempts) with exponential backoff + full jitter on 429 / 5xx / connection errors;
  only idempotent methods are retried unless the caller passes ``retry=True`` (e.g. search APIs that use POST for reads)
* in-process circuit breaker per host: opens after 5 consecutive failures, half-open after 30 s
* in-process per-host rate limiter (default 1 req/s) and concurrency limit (default 2) via asyncio primitives
* structured error mapping to the failure taxonomy: transient | rate_limited | auth | validation | permanent |
  ambiguous | unsupported
"""
from __future__ import annotations

import asyncio
import random
import time
import weakref
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from email.utils import parsedate_to_datetime
from typing import Any
from urllib.parse import urlsplit

import httpx

from app.core.logging import get_logger

log = get_logger("resilience")

IDEMPOTENT_METHODS = frozenset({"GET", "HEAD", "OPTIONS", "PUT", "DELETE"})
RETRY_STATUSES = frozenset({429, 500, 502, 503, 504, 520, 521, 522, 523, 524})


class ErrorCategory:
    TRANSIENT = "transient"
    RATE_LIMITED = "rate_limited"
    AUTH = "auth"
    VALIDATION = "validation"
    PERMANENT = "permanent"
    AMBIGUOUS = "ambiguous"
    UNSUPPORTED = "unsupported"


class ResilienceError(Exception):
    """A mapped outbound-HTTP failure. ``category`` follows the doc-28 taxonomy; native details are preserved."""

    def __init__(self, category: str, message: str, *, status: int | None = None, host: str | None = None,
                 url: str | None = None, retry_after_s: float | None = None, code: str | None = None):
        super().__init__(message)
        self.category = category
        self.message = message
        self.status = status
        self.host = host
        self.url = url
        self.retry_after_s = retry_after_s
        self.code = code

    def to_dict(self) -> dict[str, Any]:
        return {"category": self.category, "message": self.message, "status": self.status, "host": self.host,
                "code": self.code, "retry_after_s": self.retry_after_s}


class CircuitOpenError(ResilienceError):
    def __init__(self, host: str, retry_in_s: float):
        super().__init__(ErrorCategory.TRANSIENT, f"circuit open for {host}", host=host, retry_after_s=retry_in_s,
                         code="circuit_open")


class ResponseTooLargeError(ResilienceError):
    def __init__(self, url: str, limit: int):
        super().__init__(ErrorCategory.PERMANENT, f"response exceeds {limit} bytes", url=url, code="too_large")


def map_status(status: int) -> str:
    if status == 429:
        return ErrorCategory.RATE_LIMITED
    if status in (401, 403, 407):
        return ErrorCategory.AUTH
    if status in (400, 409, 413, 414, 415, 422):
        return ErrorCategory.VALIDATION
    if status in (501, 505):
        return ErrorCategory.UNSUPPORTED
    if status >= 500 or status == 408:
        return ErrorCategory.TRANSIENT
    return ErrorCategory.PERMANENT


def map_exception(exc: BaseException, *, host: str | None = None, url: str | None = None) -> ResilienceError:
    if isinstance(exc, ResilienceError):
        return exc
    if isinstance(exc, httpx.TimeoutException):
        return ResilienceError(ErrorCategory.TRANSIENT, f"timeout: {type(exc).__name__}", host=host, url=url, code="timeout")
    if isinstance(exc, httpx.TransportError):
        return ResilienceError(ErrorCategory.TRANSIENT, f"connection error: {type(exc).__name__}: {exc}", host=host, url=url,
                               code="connection")
    if isinstance(exc, httpx.InvalidURL | httpx.UnsupportedProtocol):
        return ResilienceError(ErrorCategory.VALIDATION, str(exc), host=host, url=url, code="invalid_url")
    return ResilienceError(ErrorCategory.PERMANENT, f"{type(exc).__name__}: {exc}", host=host, url=url)


def parse_retry_after(value: str | None) -> float | None:
    if not value:
        return None
    value = value.strip()
    try:
        return max(0.0, float(value))
    except ValueError:
        pass
    try:
        dt = parsedate_to_datetime(value)
        return max(0.0, dt.timestamp() - time.time())
    except (TypeError, ValueError):
        return None


# ---------------------------------------------------------------------------------------------------------------------
# Circuit breaker (in-process, per host; state is loop-independent plain data)
# ---------------------------------------------------------------------------------------------------------------------
@dataclass
class _BreakerState:
    failures: int = 0
    opened_at: float | None = None
    half_open_probe: bool = False


class CircuitBreaker:
    def __init__(self, failure_threshold: int = 5, reset_after_s: float = 30.0, clock: Callable[[], float] = time.monotonic):
        self.failure_threshold = failure_threshold
        self.reset_after_s = reset_after_s
        self.clock = clock
        self._hosts: dict[str, _BreakerState] = {}

    def state(self, host: str) -> str:
        st = self._hosts.get(host)
        if not st or st.opened_at is None:
            return "closed"
        if self.clock() - st.opened_at >= self.reset_after_s:
            return "half_open"
        return "open"

    def before_request(self, host: str) -> None:
        st = self._hosts.get(host)
        if not st or st.opened_at is None:
            return
        elapsed = self.clock() - st.opened_at
        if elapsed < self.reset_after_s:
            raise CircuitOpenError(host, self.reset_after_s - elapsed)
        if st.half_open_probe:  # one probe at a time while half-open
            raise CircuitOpenError(host, 1.0)
        st.half_open_probe = True

    def record_success(self, host: str) -> None:
        self._hosts.pop(host, None)

    def record_failure(self, host: str) -> None:
        st = self._hosts.setdefault(host, _BreakerState())
        st.failures += 1
        st.half_open_probe = False
        if st.opened_at is not None or st.failures >= self.failure_threshold:
            if st.opened_at is None:
                log.warning("circuit.open", host=host, failures=st.failures)
            st.opened_at = self.clock()

    def reset(self, host: str | None = None) -> None:
        if host is None:
            self._hosts.clear()
        else:
            self._hosts.pop(host, None)


# ---------------------------------------------------------------------------------------------------------------------
# Per-host limiter (asyncio primitives are bound to an event loop, so they are kept per loop)
# ---------------------------------------------------------------------------------------------------------------------
@dataclass
class _HostLimiter:
    semaphore: asyncio.Semaphore
    interval_s: float
    lock: asyncio.Lock = field(default_factory=asyncio.Lock)
    next_at: float = 0.0

    async def wait_turn(self) -> None:
        if self.interval_s <= 0:
            return
        async with self.lock:
            now = time.monotonic()
            delay = self.next_at - now
            self.next_at = max(now, self.next_at) + self.interval_s
        if delay > 0:
            await asyncio.sleep(delay)


class HostLimiterRegistry:
    def __init__(self, rate_per_s: float = 1.0, concurrency: int = 2, overrides: dict[str, tuple[float, int]] | None = None):
        self.rate_per_s = rate_per_s
        self.concurrency = concurrency
        self.overrides = dict(overrides or {})
        self._by_loop: weakref.WeakKeyDictionary[asyncio.AbstractEventLoop, dict[str, _HostLimiter]] = weakref.WeakKeyDictionary()

    def configure_host(self, host: str, rate_per_s: float, concurrency: int) -> None:
        self.overrides[host] = (rate_per_s, concurrency)

    def get(self, host: str) -> _HostLimiter:
        loop = asyncio.get_running_loop()
        table = self._by_loop.get(loop)
        if table is None:
            table = {}
            self._by_loop[loop] = table
        lim = table.get(host)
        if lim is None:
            rate, conc = self.overrides.get(host, (self.rate_per_s, self.concurrency))
            lim = _HostLimiter(semaphore=asyncio.Semaphore(max(1, conc)), interval_s=(1.0 / rate) if rate > 0 else 0.0)
            table[host] = lim
        return lim


# Process-wide defaults shared by every ResilientClient that doesn't bring its own.
DEFAULT_BREAKER = CircuitBreaker()
DEFAULT_LIMITERS = HostLimiterRegistry()

HeadersHook = Callable[[httpx.Response], Awaitable[None] | None]


class ResilientClient:
    """Thin resilient wrapper over ``httpx.AsyncClient``.

    ``request()`` always streams the body so a ``max_bytes`` cap can abort early; ``on_headers`` lets callers reject a
    response (e.g. content-type allowlist) before the body is read. The returned ``httpx.Response`` has its content loaded.
    """

    def __init__(self, *, connect_timeout: float = 5.0, read_timeout: float = 30.0, attempts: int = 3,
                 backoff_base_s: float = 1.0, backoff_cap_s: float = 60.0, headers: dict[str, str] | None = None,
                 breaker: CircuitBreaker | None = None, limiters: HostLimiterRegistry | None = None,
                 rate_per_host: float | None = None, concurrency_per_host: int | None = None,
                 transport: httpx.AsyncBaseTransport | None = None, follow_redirects: bool = False,
                 trust_env: bool = False, sleep: Callable[[float], Awaitable[Any]] = asyncio.sleep):
        self.timeout = httpx.Timeout(connect=connect_timeout, read=read_timeout, write=read_timeout, pool=connect_timeout)
        self.attempts = max(1, attempts)
        self.backoff_base_s = backoff_base_s
        self.backoff_cap_s = backoff_cap_s
        self.breaker = breaker or DEFAULT_BREAKER
        if limiters is None and (rate_per_host is not None or concurrency_per_host is not None):
            limiters = HostLimiterRegistry(rate_per_s=rate_per_host if rate_per_host is not None else 1.0,
                                           concurrency=concurrency_per_host or 2)
        self.limiters = limiters or DEFAULT_LIMITERS
        self._sleep = sleep
        self._client = httpx.AsyncClient(timeout=self.timeout, headers=headers or {}, transport=transport,
                                         follow_redirects=follow_redirects, trust_env=trust_env)

    async def __aenter__(self) -> ResilientClient:
        return self

    async def __aexit__(self, *exc: object) -> None:
        await self.aclose()

    async def aclose(self) -> None:
        await self._client.aclose()

    def backoff_delay(self, attempt: int, retry_after: float | None = None) -> float:
        if retry_after is not None:
            return min(self.backoff_cap_s, retry_after)
        return random.uniform(0, min(self.backoff_cap_s, self.backoff_base_s * (2 ** attempt)))

    async def request(self, method: str, url: str, *, retry: bool | None = None, raise_for_status: bool = True,
                      max_bytes: int | None = None, on_headers: HeadersHook | None = None, attempts: int | None = None,
                      **kwargs: Any) -> httpx.Response:
        method = method.upper()
        host = (urlsplit(url).hostname or "").lower()
        may_retry = (method in IDEMPOTENT_METHODS) if retry is None else retry
        total = (attempts or self.attempts) if may_retry else 1
        last_exc: ResilienceError | None = None
        for attempt in range(total):
            self.breaker.before_request(host)
            limiter = self.limiters.get(host)
            retry_after: float | None = None
            try:
                async with limiter.semaphore:
                    await limiter.wait_turn()
                    resp = await self._send(method, url, max_bytes=max_bytes, on_headers=on_headers, **kwargs)
            except ResilienceError as e:  # raised by hooks / size cap — not retried, not a host failure
                self.breaker.record_success(host)
                raise e
            except (httpx.TransportError, httpx.TimeoutException) as e:
                self.breaker.record_failure(host)
                last_exc = map_exception(e, host=host, url=url)
                log.info("http.retryable_error", host=host, attempt=attempt + 1, error=last_exc.message)
            else:
                if resp.status_code in RETRY_STATUSES:
                    retry_after = parse_retry_after(resp.headers.get("retry-after"))
                    if resp.status_code >= 500:
                        self.breaker.record_failure(host)
                    else:
                        self.breaker.record_success(host)
                    last_exc = ResilienceError(map_status(resp.status_code), f"HTTP {resp.status_code}", status=resp.status_code,
                                               host=host, url=url, retry_after_s=retry_after)
                    if attempt + 1 >= total:
                        if raise_for_status:
                            raise last_exc
                        return resp
                    if retry_after is not None and retry_after > self.backoff_cap_s:
                        raise last_exc  # the window resets too far in the future; let the caller reschedule
                else:
                    self.breaker.record_success(host)
                    if raise_for_status and resp.status_code >= 400:
                        raise ResilienceError(map_status(resp.status_code), f"HTTP {resp.status_code}", status=resp.status_code,
                                              host=host, url=url)
                    return resp
            if attempt + 1 < total:
                await self._sleep(self.backoff_delay(attempt, retry_after))
        assert last_exc is not None
        raise last_exc

    async def _send(self, method: str, url: str, *, max_bytes: int | None, on_headers: HeadersHook | None,
                    **kwargs: Any) -> httpx.Response:
        req = self._client.build_request(method, url, **kwargs)
        resp = await self._client.send(req, stream=True)
        try:
            if on_headers is not None:
                maybe = on_headers(resp)
                if asyncio.iscoroutine(maybe):
                    await maybe
            if max_bytes is not None:
                declared = resp.headers.get("content-length")
                if declared and declared.isdigit() and int(declared) > max_bytes:
                    raise ResponseTooLargeError(url, max_bytes)
            buf = bytearray()
            async for chunk in resp.aiter_bytes():
                buf.extend(chunk)
                if max_bytes is not None and len(buf) > max_bytes:
                    raise ResponseTooLargeError(url, max_bytes)
        finally:
            await resp.aclose()
        # aiter_bytes() already decoded any Content-Encoding; drop framing headers so httpx doesn't decode twice.
        headers = [(k, v) for k, v in resp.headers.multi_items()
                   if k.lower() not in ("content-encoding", "content-length", "transfer-encoding")]
        return httpx.Response(resp.status_code, headers=headers, content=bytes(buf), request=req)

    async def get(self, url: str, **kwargs: Any) -> httpx.Response:
        return await self.request("GET", url, **kwargs)

    async def post(self, url: str, **kwargs: Any) -> httpx.Response:
        return await self.request("POST", url, **kwargs)

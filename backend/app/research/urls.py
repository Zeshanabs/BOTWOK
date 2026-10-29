"""URL canonicalization and domain helpers (pipeline stage ③)."""
from __future__ import annotations

import posixpath
import re
from collections.abc import Iterable
from urllib.parse import parse_qsl, quote, urlencode, urlsplit, urlunsplit

TRACKING_PARAMS = frozenset({
    "fbclid", "gclid", "dclid", "gbraid", "wbraid", "msclkid", "yclid", "twclid", "ttclid", "li_fat_id", "igshid",
    "mc_cid", "mc_eid", "_ga", "_gl", "_hsenc", "_hsmi", "mkt_tok", "ref", "ref_src", "ref_url", "referrer", "source",
    "spm", "s_cid", "cmpid", "oly_anon_id", "oly_enc_id", "vero_id", "rb_clickid", "trk", "si",
})
TRACKING_PREFIXES = ("utm_", "pk_", "mtm_", "hsa_", "__hs")
DEFAULT_PORTS = {"http": 80, "https": 443}
# Small public-suffix subset for registrable-domain approximation (no network access needed).
MULTI_PART_SUFFIXES = frozenset({
    "co.uk", "org.uk", "ac.uk", "gov.uk", "ltd.uk", "plc.uk", "me.uk", "net.uk", "sch.uk", "nhs.uk", "police.uk",
    "com.au", "net.au", "org.au", "edu.au", "gov.au", "asn.au", "id.au", "co.nz", "org.nz", "govt.nz", "ac.nz",
    "co.jp", "ne.jp", "or.jp", "ac.jp", "go.jp", "co.kr", "or.kr", "ac.kr", "go.kr", "com.br", "gov.br", "org.br",
    "com.cn", "gov.cn", "edu.cn", "org.cn", "net.cn", "com.hk", "gov.hk", "edu.hk", "com.sg", "gov.sg", "edu.sg",
    "co.in", "gov.in", "ac.in", "org.in", "net.in", "co.za", "gov.za", "ac.za", "org.za", "com.mx", "gob.mx",
    "com.ar", "gob.ar", "com.tr", "gov.tr", "edu.tr", "co.il", "gov.il", "ac.il", "com.tw", "gov.tw", "edu.tw",
    "com.my", "gov.my", "co.id", "go.id", "ac.id", "com.ph", "gov.ph", "com.pk", "gov.pk", "com.ng", "gov.ng",
    "co.ke", "go.ke", "com.eg", "gov.eg", "com.sa", "gov.sa", "com.ua", "gov.ua", "com.pl", "gov.pl", "gc.ca",
    "github.io", "gitlab.io", "blogspot.com", "wordpress.com", "substack.com", "medium.com", "herokuapp.com",
    "netlify.app", "vercel.app", "pages.dev", "web.app", "firebaseapp.com", "azurewebsites.net", "cloudfront.net",
})
_SCHEME_RE = re.compile(r"^[a-zA-Z][a-zA-Z0-9+.-]*://")
_OPAQUE_SCHEME_RE = re.compile(r"^([a-zA-Z][a-zA-Z0-9+.-]*):(?!//)(.*)$", re.S)
_PCT_RE = re.compile(r"%[0-9a-fA-F]{2}")


def _clean_host(host: str) -> str:
    host = host.strip().rstrip(".").lower()
    try:
        return host.encode("idna").decode("ascii") if host and not host.isascii() else host
    except UnicodeError:
        return host


def _is_tracking(key: str) -> bool:
    k = key.lower()
    return k in TRACKING_PARAMS or k.startswith(TRACKING_PREFIXES)


def _normalize_path(path: str) -> str:
    if not path:
        return "/"
    # Uppercase percent-escapes and encode stray unsafe characters; never decode (``%2F`` must stay distinct from ``/``).
    path = _PCT_RE.sub(lambda m: m.group(0).upper(), path)
    path = quote(path, safe="/:@!$&'()*+,;=-._~%")
    # posixpath.normpath resolves dot-segments, collapses duplicate slashes and drops the trailing slash, which is
    # our trailing-slash rule: ``/blog/`` ≡ ``/blog`` for non-root paths; the root stays ``/``.
    norm = posixpath.normpath(path)
    if norm.startswith("//"):
        norm = "/" + norm.lstrip("/")
    if norm in (".", ""):
        norm = "/"
    return norm


def canonicalize(url: str) -> str:
    """Canonical form used as the per-workspace identity of a source.

    lowercase scheme/host, IDNA host, default port dropped, tracking params (utm_*, fbclid, gclid, ref, …) removed,
    remaining query sorted, fragment dropped, dot-segments resolved, trailing slash removed except for the root path.
    """
    raw = url.strip()
    opaque = _OPAQUE_SCHEME_RE.match(raw)
    if opaque and not re.match(r"^\d+(/|$)", opaque.group(2)):  # mailto:, javascript:, data: … (not host:port)
        raise ValueError(f"unsupported url scheme: {opaque.group(1)}")
    if not _SCHEME_RE.match(raw):
        raw = "https://" + raw.lstrip("/")
    parts = urlsplit(raw)
    scheme = parts.scheme.lower()
    host = _clean_host(parts.hostname or "")
    try:
        port = parts.port
    except ValueError:
        port = None
    netloc = host
    if port and DEFAULT_PORTS.get(scheme) != port:
        netloc = f"{host}:{port}"
    if ":" in host and not host.startswith("["):  # IPv6 literal
        netloc = f"[{host}]" + (f":{port}" if port and DEFAULT_PORTS.get(scheme) != port else "")
    path = _normalize_path(parts.path)
    query_items = [(k, v) for k, v in parse_qsl(parts.query, keep_blank_values=True) if not _is_tracking(k)]
    query = urlencode(sorted(query_items), doseq=True)
    return urlunsplit((scheme, netloc, path, query, ""))


def safe_canonicalize(url: str) -> str | None:
    try:
        c = canonicalize(url)
    except (ValueError, UnicodeError):
        return None
    p = urlsplit(c)
    if p.scheme not in ("http", "https") or not p.hostname:
        return None
    return c


def host_of(url: str) -> str:
    try:
        return _clean_host(urlsplit(url if _SCHEME_RE.match(url) else "https://" + url).hostname or "")
    except ValueError:
        return ""


def domain_of(url: str) -> str:
    """Host without a leading ``www.`` (what the UI shows and what diversity limits use)."""
    h = host_of(url)
    return h[4:] if h.startswith("www.") else h


def registrable_domain(host_or_url: str) -> str:
    """Approximate eTLD+1 (``news.bbc.co.uk`` → ``bbc.co.uk``)."""
    host = host_of(host_or_url) if "/" in host_or_url or ":" in host_or_url else _clean_host(host_or_url)
    labels = [p for p in host.split(".") if p]
    if len(labels) <= 2:
        return ".".join(labels)
    last2 = ".".join(labels[-2:])
    if last2 in MULTI_PART_SUFFIXES:
        return ".".join(labels[-3:])
    return last2


def same_site(a: str, b: str) -> bool:
    return bool(registrable_domain(a)) and registrable_domain(a) == registrable_domain(b)


def matches_domain(host_or_url: str, domains: Iterable[str]) -> bool:
    """True if host equals or is a subdomain of any entry (entries may be URLs or bare domains)."""
    host = domain_of(host_or_url)
    for d in domains:
        d = domain_of(d.strip()) if d else ""
        if d and (host == d or host.endswith("." + d)):
            return True
    return False

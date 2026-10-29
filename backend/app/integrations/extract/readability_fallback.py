"""Readability-style fallback extractor (selectolax): strips script/style/nav/footer/hidden elements and returns the main
text as paragraphs. Also exposes link / feed / metadata helpers used by the crawler."""
from __future__ import annotations

import re
from urllib.parse import urljoin

from app.core.ports.extractor_provider import ExtractedDocument
from app.integrations.search.base import parse_date

STRIP_TAGS = ("script", "style", "noscript", "template", "svg", "canvas", "iframe", "object", "embed", "nav", "footer",
              "header", "aside", "form", "button", "select", "input", "textarea", "dialog", "menu")
BLOCK_TAGS = ("p", "h1", "h2", "h3", "h4", "h5", "h6", "li", "blockquote", "pre", "td", "th", "dd", "dt", "figcaption",
              "summary")
_HIDDEN_STYLE = re.compile(r"(display\s*:\s*none|visibility\s*:\s*hidden|font-size\s*:\s*0(px|em|rem|%)?\s*(;|$)|"
                           r"opacity\s*:\s*0(\.0+)?\s*(;|$)|left\s*:\s*-\d{3,}px|text-indent\s*:\s*-\d{3,}px)", re.I)
HIDDEN_CLASSES = frozenset({
    "sr-only", "visually-hidden", "screen-reader-text", "hidden", "d-none", "is-hidden", "cookie-banner", "cookie-consent",
    "cookie-notice", "newsletter-signup", "share-buttons", "social-share", "sharing", "related-posts", "advertisement",
    "ad", "ads", "promo", "breadcrumb", "breadcrumbs", "comments", "comment-list", "skip-link", "visuallyhidden",
})
FEED_TYPES = ("application/rss+xml", "application/atom+xml", "application/feed+json", "application/rss", "text/xml")


def _parser(html: str):
    """selectolax ≥ 1.0 ships only the Lexbor backend (``selectolax.parser`` raises on import)."""
    try:
        from selectolax.lexbor import LexborHTMLParser
        return LexborHTMLParser(html)
    except ImportError:  # older selectolax
        from selectolax.parser import HTMLParser
        return HTMLParser(html)


def strip_hidden(tree) -> None:
    for tag in STRIP_TAGS:
        for n in tree.css(tag):
            n.decompose()
    for n in tree.css("[hidden], [aria-hidden=true], [style]"):
        attrs = n.attributes
        if "hidden" in attrs or attrs.get("aria-hidden") == "true" or _HIDDEN_STYLE.search(attrs.get("style") or ""):
            n.decompose()
    for n in tree.css("[class]"):
        classes = {c.lower() for c in (n.attributes.get("class") or "").split()}
        if classes & HIDDEN_CLASSES and n.tag not in ("html", "body", "main", "article"):
            n.decompose()


def _meta(tree, *names: str) -> str | None:
    for name in names:
        for sel in (f'meta[property="{name}"]', f'meta[name="{name}"]', f'meta[itemprop="{name}"]'):
            n = tree.css_first(sel)
            if n is not None and (n.attributes.get("content") or "").strip():
                return (n.attributes.get("content") or "").strip()
    return None


def page_metadata(html: str) -> dict[str, str | None]:
    try:
        tree = _parser(html)
    except Exception:
        return {}
    title_node = tree.css_first("title")
    lang = None
    html_node = tree.css_first("html")
    if html_node is not None:
        lang = (html_node.attributes.get("lang") or "").split("-")[0].lower() or None
    return {
        "title": _meta(tree, "og:title", "twitter:title") or (title_node.text(strip=True) if title_node else None),
        "author": _meta(tree, "author", "article:author", "parsely-author", "byl"),
        "published": _meta(tree, "article:published_time", "datePublished", "pubdate", "date", "dc.date", "og:updated_time"),
        "description": _meta(tree, "description", "og:description"),
        "language": lang,
    }


def extract_links(html: str, base_url: str, *, limit: int = 500) -> list[str]:
    try:
        tree = _parser(html)
    except Exception:
        return []
    out: list[str] = []
    seen: set[str] = set()
    for a in tree.css("a[href]"):
        href = (a.attributes.get("href") or "").strip()
        if not href or href.startswith(("#", "mailto:", "tel:", "javascript:", "data:")):
            continue
        rel = (a.attributes.get("rel") or "").lower()
        if "nofollow" in rel:
            continue
        absu = urljoin(base_url, href).split("#", 1)[0]
        if absu.startswith(("http://", "https://")) and absu not in seen:
            seen.add(absu)
            out.append(absu)
        if len(out) >= limit:
            break
    return out


def discover_feeds(html: str, base_url: str) -> list[str]:
    try:
        tree = _parser(html)
    except Exception:
        return []
    feeds: list[str] = []
    for link in tree.css("link[rel][href]"):
        rels = (link.attributes.get("rel") or "").lower().split()
        typ = (link.attributes.get("type") or "").lower()
        if "alternate" in rels and any(typ.startswith(t) for t in FEED_TYPES):
            u = urljoin(base_url, (link.attributes.get("href") or "").strip())
            if u.startswith(("http://", "https://")) and u not in feeds:
                feeds.append(u)
    return feeds


class ReadabilityFallbackExtractor:
    name = "readability_fallback"

    def extract(self, html: str, url: str) -> ExtractedDocument | None:
        try:
            tree = _parser(html)
        except Exception:
            return None
        meta = page_metadata(html)
        strip_hidden(tree)
        root = tree.css_first("article") or tree.css_first("main") or tree.css_first("[role=main]") or tree.body
        if root is None:
            return None
        blocks: list[str] = []
        for node in root.css(",".join(BLOCK_TAGS)):
            # skip nested blocks (e.g. <p> inside <li>) by only taking leaf-ish nodes
            if any(child.tag in BLOCK_TAGS for child in node.iter()):
                continue
            t = re.sub(r"\s+", " ", node.text(separator=" ", strip=True)).strip()
            if t and (len(t.split()) >= 3 or node.tag.startswith("h")):
                blocks.append(t)
        if not blocks:
            raw = re.sub(r"[ \t]+", " ", root.text(separator="\n", strip=True))
            blocks = [ln.strip() for ln in raw.split("\n") if len(ln.split()) >= 3]
        dedup: list[str] = []
        seen: set[str] = set()
        for b in blocks:
            if b not in seen:
                seen.add(b)
                dedup.append(b)
        text = "\n\n".join(dedup).strip()
        if not text:
            return None
        return ExtractedDocument(url=url, title=meta.get("title"), text=text, author=meta.get("author"),
                                 published_at=parse_date(meta.get("published")), language=meta.get("language"),
                                 links=extract_links(html, url, limit=200), extractor=self.name)

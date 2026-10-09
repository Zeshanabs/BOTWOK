"""Pure adapter validation tests (no DB, no network): X, Instagram, LinkedIn, YouTube, Threads limits from doc 26."""
from __future__ import annotations

import pytest

from app.core.ports.social_adapter import MediaInput, PublishRequest
from app.integrations.social.base import (
    fingerprint,
    map_http_error,
    pkce_challenge_hex,
    pkce_challenge_s256,
    pkce_pair,
)
from app.integrations.social.linkedin import LinkedInAdapter
from app.integrations.social.meta.instagram import InstagramAdapter
from app.integrations.social.meta.threads import ThreadsAdapter, threads_length
from app.integrations.social.x import XAdapter, weighted_length
from app.integrations.social.youtube import YouTubeAdapter, tags_length


class Account:
    def __init__(self, platform: str, **kw):
        self.id = "acc-1"
        self.platform = platform
        self.auth_flavor = kw.pop("auth_flavor", "default")
        self.external_id = "ext"
        self.handle = "botwok"
        self.scopes = kw.pop("scopes", [])
        self.health = kw.pop("health", {})
        self.capabilities = kw.pop("capabilities", {})


def req(text: str = "hello", media: list[MediaInput] | None = None, segments: list[str] | None = None, **meta) -> PublishRequest:
    r = PublishRequest(text=text, segments=segments or [], media=media or [], metadata=meta)
    infos = meta.get("media_info") or []
    if media and not infos:
        r.metadata["media_info"] = [{} for _ in media]
    return r


def codes(result) -> set[str]:
    return {i.code for i in result.issues}


def errors(result) -> set[str]:
    return {i.code for i in result.issues if i.severity == "error"}


# ---------------------------------------------------------------- X
async def test_x_280_weighted_and_url_cost_warning():
    x = XAdapter()
    long = "a" * 281
    res = await x.validate_content(Account("x"), req(long))
    assert "x_text_too_long" in errors(res)
    ok = "a" * 256 + " https://example.com/some/very/long/path/that/would/exceed/280/chars/if/counted/literally"
    assert weighted_length(ok) == 256 + 1 + 23
    res = await x.validate_content(Account("x"), req(ok))
    assert "x_text_too_long" not in errors(res)
    assert "url_post_costs_0_20" in codes(res)
    assert all(i.severity == "warning" for i in res.issues if i.code == "url_post_costs_0_20")
    assert res.ok


async def test_x_quote_posts_unsupported_and_media_limits():
    x = XAdapter()
    res = await x.validate_content(Account("x"), req("hi", quote_tweet_id="123"))
    assert "quote_posts_unsupported" in errors(res)
    media = [MediaInput(url=None, bytes_loader=None, mime="image/png", kind="image") for _ in range(5)]
    res = await x.validate_content(Account("x"), req("hi", media))
    assert "x_too_many_media" in errors(res)
    res = await x.validate_content(Account("x"), req("hi", segments=["ok", "b" * 300]))
    assert "x_text_too_long" in errors(res)
    res = await x.validate_content(Account("x"), req("q", poll={"options": ["a"], "duration_minutes": 3}))
    assert {"x_poll_shape", "x_poll_duration"} <= errors(res)


# ---------------------------------------------------------------- Instagram
async def test_instagram_jpeg_aspect_public_url_caption():
    ig = InstagramAdapter()
    acc = Account("instagram", auth_flavor="facebook_login")
    res = await ig.validate_content(acc, req("caption"))
    assert "instagram_media_required" in errors(res)
    png = MediaInput(url="https://cdn.example.com/a.png", bytes_loader=None, mime="image/png", kind="image", alt_text="x")
    res = await ig.validate_content(acc, req("c", [png], media_info=[{"width": 1000, "height": 1000, "bytes": 100}]))
    assert "instagram_jpeg_only" in errors(res)
    tall = MediaInput(url="https://cdn.example.com/a.jpg", bytes_loader=None, mime="image/jpeg", kind="image", alt_text="x")
    res = await ig.validate_content(acc, req("c", [tall], media_info=[{"width": 1000, "height": 2000, "bytes": 100}]))
    assert "instagram_aspect_ratio" in errors(res)
    good = MediaInput(url="https://cdn.example.com/a.jpg", bytes_loader=None, mime="image/jpeg", kind="image", alt_text="x")
    res = await ig.validate_content(acc, req("c", [good], media_info=[{"width": 1080, "height": 1350, "bytes": 100}]))
    assert res.ok, res.issues
    local = MediaInput(url=None, bytes_loader=None, mime="image/jpeg", kind="image", alt_text="x")
    res = await ig.validate_content(acc, req("c", [local], media_info=[{"width": 1080, "height": 1080, "bytes": 100}]))
    assert "instagram_requires_public_media_url" in errors(res)
    res = await ig.validate_content(acc, req("#a " * 31, [good], media_info=[{"width": 1080, "height": 1080, "bytes": 100}]))
    assert "instagram_too_many_hashtags" in errors(res)
    near = Account("instagram", auth_flavor="facebook_login", health={"publishing_quota_usage": 95})
    res = await ig.validate_content(near, req("c", [good], media_info=[{"width": 1080, "height": 1080, "bytes": 100}]))
    assert "ig_daily_limit_near" in codes(res) and res.ok
    full = Account("instagram", auth_flavor="facebook_login", health={"publishing_quota_usage": 100})
    res = await ig.validate_content(full, req("c", [good], media_info=[{"width": 1080, "height": 1080, "bytes": 100}]))
    assert "instagram_daily_limit_reached" in errors(res)


# ---------------------------------------------------------------- LinkedIn
async def test_linkedin_multi_image_bounds_and_polls():
    li = LinkedInAdapter()
    acc = Account("linkedin", auth_flavor="member")
    imgs = [MediaInput(url=None, bytes_loader=None, mime="image/jpeg", kind="image", alt_text="x") for _ in range(21)]
    res = await li.validate_content(acc, req("post", imgs))
    assert "linkedin_too_many_images" in errors(res)
    res = await li.validate_content(acc, req("post", imgs[:20]))
    assert "linkedin_too_many_images" not in errors(res) and res.ok
    res = await li.validate_content(acc, req("post", imgs[:2]))
    assert res.ok
    res = await li.validate_content(acc, req("x" * 3001))
    assert "linkedin_text_too_long" in errors(res)
    res = await li.validate_content(acc, req("q", poll={"options": ["a", "b", "c", "d", "e"]}))
    assert "linkedin_poll_options" in errors(res)
    res = await li.validate_content(acc, req("", article={"source": "https://x.y"}))
    assert "linkedin_article_title" in errors(res)
    assert li.can_list_posts(acc) is False
    assert li.can_list_posts(Account("linkedin", auth_flavor="organization")) is True


# ---------------------------------------------------------------- YouTube
async def test_youtube_title_description_bytes_tags_publish_at():
    yt = YouTubeAdapter()
    acc = Account("youtube")
    video = [MediaInput(url=None, bytes_loader=None, mime="video/mp4", kind="video")]
    res = await yt.validate_content(acc, req("desc", video, title="t" * 101))
    assert "youtube_title_too_long" in errors(res)
    res = await yt.validate_content(acc, req("desc", video, title="a <b>"))
    assert "youtube_title_angle_brackets" in errors(res)
    # 5,000 bytes, not characters: 1,700 three-byte characters = 5,100 bytes
    res = await yt.validate_content(acc, req("€" * 1700, video, title="ok"))
    assert "youtube_description_too_long" in errors(res)
    res = await yt.validate_content(acc, req("€" * 1600, video, title="ok"))
    assert "youtube_description_too_long" not in errors(res)
    assert tags_length(["Foo Baz"]) == 9 and tags_length(["a", "b"]) == 3
    res = await yt.validate_content(acc, req("d", video, title="ok", tags=["x" * 300, "y" * 300]))
    assert "youtube_tags_too_long" in errors(res)
    res = await yt.validate_content(acc, req("d", video, title="ok", publish_at="2030-01-01T00:00:00Z", privacy_status="public"))
    assert "youtube_publish_at_requires_private" in errors(res)
    res = await yt.validate_content(acc, req("d", [], title="ok"))
    assert "youtube_one_video" in errors(res)


# ---------------------------------------------------------------- Threads + shared helpers
async def test_threads_500_bytes_and_links():
    th = ThreadsAdapter()
    acc = Account("threads")
    assert threads_length("abc") == 3 and threads_length("😀") == 4
    res = await th.validate_content(acc, req("😀" * 126))
    assert "threads_text_too_long" in errors(res)
    res = await th.validate_content(acc, req(" ".join(f"https://e.com/{i}" for i in range(6))))
    assert "threads_too_many_links" in errors(res)


def test_pkce_variants_and_fingerprint():
    v, c = pkce_pair()
    assert 43 <= len(v) <= 128 and c == pkce_challenge_s256(v) and "=" not in c
    assert len(pkce_challenge_hex(v)) == 64 and all(ch in "0123456789abcdef" for ch in pkce_challenge_hex(v))
    a = fingerprint(PublishRequest(text="Hello  World ", metadata={"media_sha256": ["h1"]}), "acc")
    b = fingerprint(PublishRequest(text="hello world", metadata={"media_sha256": ["h1"]}), "acc")
    c2 = fingerprint(PublishRequest(text="hello world", metadata={"media_sha256": ["h2"]}), "acc")
    assert a == b and a != c2 and a != fingerprint(PublishRequest(text="hello world", metadata={"media_sha256": ["h1"]}), "other")


@pytest.mark.parametrize("status,headers,category", [
    (401, {}, "auth"), (429, {"Retry-After": "30"}, "rate_limited"), (403, {}, "permanent"), (400, {}, "validation"),
    (404, {}, "permanent"), (500, {}, "transient"), (503, {}, "transient"),
])
def test_map_http_error_categories(status, headers, category):
    import httpx
    resp = httpx.Response(status, headers=headers, text='{"message":"x"}', request=httpx.Request("GET", "https://api"))
    err = map_http_error(resp)
    assert err.category == category
    if status == 429:
        assert err.retry_after_s == 30


def test_map_http_error_ambiguous_on_gateway_write():
    import httpx
    resp = httpx.Response(502, text="bad gateway", request=httpx.Request("POST", "https://api"))
    assert map_http_error(resp, write=True).category == "ambiguous"
    assert map_http_error(resp, write=False).category == "transient"
    resp = httpx.Response(403, text='{"error":"token expired"}', request=httpx.Request("POST", "https://api"))
    assert map_http_error(resp).category == "auth"

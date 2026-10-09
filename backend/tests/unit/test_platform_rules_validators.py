"""Property-style tests for the platform-rule engine and deterministic validators (seeded random inputs, no DB)."""
from __future__ import annotations

import random
import string

import pytest

from app.content.platform_rules import FORMATS, PLATFORMS, describe_rules, rules_for, support_of
from app.content.validators import (
    compose_text,
    fingerprint,
    measure,
    validate_variant,
    x_weighted_length,
    youtube_tags_length,
)

SEEDS = range(25)


def _codes(res: dict) -> set[str]:
    return {i["code"] for i in res["issues"]}


def _errors(res: dict) -> set[str]:
    return {i["code"] for i in res["issues"] if i["severity"] == "error"}


def _rand_word(rng: random.Random, n: int) -> str:
    return "".join(rng.choice(string.ascii_lowercase) for _ in range(n))


def _rand_url(rng: random.Random) -> str:
    path = "/".join(_rand_word(rng, rng.randint(1, 30)) for _ in range(rng.randint(0, 6)))
    return f"https://{_rand_word(rng, rng.randint(3, 20))}.com/{path}"


# ── rule table ─────────────────────────────────────────────────────────────────

def test_every_pair_resolves_and_describes():
    for p in PLATFORMS:
        for f in FORMATS:
            r = rules_for(p, f)
            assert r["platform"] == p and r["format"] == f
            assert isinstance(r["supported"], bool)
            text = describe_rules(p, f)
            assert text.startswith(f"PLATFORM RULES — {p} / {f}")
            if not r["supported"]:
                assert "NOT SUPPORTED" in text


def test_key_limits_match_doc_26():
    assert rules_for("x", "text")["text"]["max"] == 280
    assert rules_for("x", "text")["segments"]["max"] == 25
    assert rules_for("linkedin", "text")["text"]["max"] == 3000
    assert rules_for("instagram", "image")["text"]["max"] == 2200
    assert rules_for("instagram", "image")["hashtags"]["max"] == 30
    assert rules_for("threads", "text")["text"]["max"] == 500
    assert rules_for("youtube", "video")["title"]["max"] == 100
    assert rules_for("youtube", "video")["text"] == {"field": "text", "max": 5000, "unit": "utf8_bytes", "required": False}
    assert rules_for("pinterest", "image")["title"]["max"] == 100
    assert rules_for("pinterest", "image")["text"]["max"] == 800
    assert rules_for("gbp", "text")["text"]["max"] == 1500
    assert rules_for("facebook", "text")["text"]["max"] == 63206
    assert rules_for("tiktok", "video")["text"]["max"] == 2200
    assert rules_for("tiktok", "carousel")["text"]["max"] == 4000
    assert rules_for("instagram", "carousel")["media"]["max"] == 10
    assert rules_for("x", "carousel")["media"]["max"] == 4
    assert (rules_for("linkedin", "carousel")["media"]["min"], rules_for("linkedin", "carousel")["media"]["max"]) == (2, 20)
    assert (rules_for("threads", "carousel")["media"]["min"], rules_for("threads", "carousel")["media"]["max"]) == (2, 20)
    assert (rules_for("pinterest", "carousel")["media"]["min"], rules_for("pinterest", "carousel")["media"]["max"]) == (2, 5)
    assert rules_for("tiktok", "carousel")["media"]["max"] == 35
    assert rules_for("instagram", "image")["links"]["strategy"] == "link_in_bio"
    assert not support_of("tiktok", "text") and not support_of("instagram", "text") and support_of("linkedin", "poll")


# ── X weighting ────────────────────────────────────────────────────────────────

@pytest.mark.parametrize("seed", SEEDS)
def test_x_url_counts_as_23_regardless_of_length(seed: int):
    rng = random.Random(seed)
    n = rng.randint(0, 250)
    url = _rand_url(rng)
    text = ("a" * n + " " + url) if n else url
    assert x_weighted_length(text) == n + (1 if n else 0) + 23
    res = validate_variant("x", "text", {"text": text})
    expected_ok = x_weighted_length(text) <= 280
    assert ("text_too_long" not in _errors(res)) == expected_ok
    assert "x_url_cost" in _codes(res)


def test_x_boundary_and_weighting():
    assert validate_variant("x", "text", {"text": "a" * 280})["ok"]
    res = validate_variant("x", "text", {"text": "a" * 281})
    assert not res["ok"] and "text_too_long" in _errors(res)
    # CJK and emoji weigh 2
    assert x_weighted_length("日本") == 4
    assert x_weighted_length("👍") == 2
    assert x_weighted_length("👩‍💻") == 2          # ZWJ sequence counts once
    assert x_weighted_length("é") == 1
    assert not validate_variant("x", "text", {"text": "日" * 141})["ok"]
    assert validate_variant("x", "text", {"text": "日" * 140})["ok"]


def test_x_hashtags_appended_count_toward_length():
    text = "a" * 275
    assert compose_text(text, ["growth"]).endswith("\n\n#growth")      # 275 + 2 + 7 = 284 > 280
    res = validate_variant("x", "text", {"text": text, "hashtags": ["growth"]})
    assert "text_too_long" in _errors(res)


@pytest.mark.parametrize("seed", SEEDS)
def test_x_thread_segments(seed: int):
    rng = random.Random(seed)
    k = rng.randint(1, 30)
    segs = [_rand_word(rng, rng.randint(1, 280)) for _ in range(k)]
    res = validate_variant("x", "text", {"segments": segs})
    assert ("too_many_segments" in _errors(res)) == (k > 25)
    assert "segment_too_long" not in _errors(res)
    long_seg = validate_variant("x", "text", {"segments": ["ok", "b" * 281]})
    assert any(i["field"] == "segments[1]" for i in long_seg["issues"] if i["code"] == "segment_too_long")


# ── Instagram hashtag cap ──────────────────────────────────────────────────────

@pytest.mark.parametrize("seed", SEEDS)
def test_instagram_hashtag_cap(seed: int):
    rng = random.Random(seed)
    n = rng.randint(0, 40)
    tags = list(dict.fromkeys(_rand_word(rng, 8) + str(i) for i in range(n)))
    in_text = rng.random() < 0.5
    variant = {"text": "caption " + " ".join(f"#{t}" for t in tags)} if in_text else {"text": "caption", "hashtags": tags}
    res = validate_variant("instagram", "image", variant)
    assert ("too_many_hashtags" in _errors(res)) == (len(tags) > 30)
    if 5 < len(tags) <= 30:
        assert "hashtags_above_recommended" in _codes(res)


def test_banned_and_invalid_hashtags():
    res = validate_variant("instagram", "image", {"text": "hi #FollowMe", "hashtags": ["growth", "bad tag"]},
                           banned_hashtags=["#followme"])
    assert {"banned_hashtag", "invalid_hashtag"} <= _errors(res)


def test_instagram_link_and_mentions_and_jpeg():
    res = validate_variant("instagram", "image", {
        "text": "see https://acme.com " + " ".join(f"@user{i}" for i in range(21)),
        "assets": [{"kind": "image", "mime": "image/png", "alt_text": "x"}]})
    codes = _codes(res)
    assert "link_not_clickable" in codes and "too_many_mentions" in _errors(res)
    assert "unsupported_media_type" in _errors(res)


# ── YouTube bytes / chars ──────────────────────────────────────────────────────

@pytest.mark.parametrize("seed", SEEDS)
def test_youtube_description_is_measured_in_bytes(seed: int):
    rng = random.Random(seed)
    chars = rng.choice(["é", "ü", "€", "日", "a"])
    per = len(chars.encode())
    limit_chars = 5000 // per
    n = limit_chars + rng.choice([-3, 0, 1, 2])
    desc = chars * n
    res = validate_variant("youtube", "video", {"text": desc, "platform_metadata": {"title": "Title"}})
    assert measure(desc, "utf8_bytes") == n * per
    assert ("description_too_long_bytes" in _errors(res)) == (n * per > 5000)


def test_youtube_title_tags_and_forbidden_chars():
    res = validate_variant("youtube", "video", {"text": "desc <b>", "platform_metadata": {"title": "x" * 101}})
    errs = _errors(res)
    assert {"title_too_long", "forbidden_characters"} <= errs
    assert "title_required" in _errors(validate_variant("youtube", "video", {"text": "d"}))
    assert youtube_tags_length(["Foo Baz", "abc"]) == 9 + 3 + 1
    tags = ["tag" + str(i) * 10 for i in range(60)]
    assert "tags_too_long" in _errors(validate_variant("youtube", "video", {"platform_metadata": {"title": "t", "tags": tags}}))


# ── LinkedIn multi-image bounds ────────────────────────────────────────────────

@pytest.mark.parametrize("n", [1, 2, 3, 10, 19, 20, 21, 25])
def test_linkedin_multi_image_bounds(n: int):
    assets = [{"kind": "image", "mime": "image/jpeg", "alt_text": f"slide {i}"} for i in range(n)]
    res = validate_variant("linkedin", "carousel", {"text": "deck", "assets": assets})
    errs = _errors(res)
    assert ("too_few_media" in errs) == (n < 2)
    assert ("too_many_media" in errs) == (n > 20)
    assert res["ok"] == (2 <= n <= 20)


def test_missing_alt_text_is_an_error_where_supported():
    res = validate_variant("linkedin", "image", {"text": "x", "assets": [{"kind": "image", "mime": "image/jpeg"}]})
    assert "missing_alt_text" in _errors(res)


def test_carousel_slide_counts_from_segments_without_media():
    res = validate_variant("instagram", "carousel", {"text": "c", "segments": [f"slide {i}" for i in range(11)]})
    assert "too_many_media" in _errors(res)


# ── polls & misc ───────────────────────────────────────────────────────────────

def test_poll_shapes():
    ok = validate_variant("x", "poll", {"text": "Which?", "platform_metadata": {"poll": {"options": ["A", "B"],
                                                                                         "duration_minutes": 60}}})
    assert ok["ok"], ok
    bad = validate_variant("x", "poll", {"text": "Which?", "platform_metadata": {"poll": {
        "options": ["A", "B", "C", "D", "E"], "duration_minutes": 3}}})
    assert {"poll_invalid_options", "poll_invalid_duration"} <= _errors(bad)
    li = validate_variant("linkedin", "poll", {"text": "Q?", "platform_metadata": {"poll": {
        "options": ["one", "x" * 31], "duration": "TWO_DAYS"}}})
    assert {"poll_option_too_long", "poll_invalid_duration"} <= _errors(li)
    assert "poll_not_supported" in _errors(validate_variant("instagram", "image", {"platform_metadata": {"poll": {"options": ["a", "b"]}}}))


def test_unsupported_format_and_threads_links():
    assert "format_not_supported" in _errors(validate_variant("tiktok", "text", {"text": "hi"}))
    links = " ".join(f"https://site{i}.com" for i in range(6))
    assert "too_many_links" in _errors(validate_variant("threads", "text", {"text": links}))


@pytest.mark.parametrize("seed", SEEDS)
def test_fingerprint_is_normalized_and_order_insensitive(seed: int):
    rng = random.Random(seed)
    words = [_rand_word(rng, rng.randint(1, 8)) for _ in range(rng.randint(1, 20))]
    hashes = [_rand_word(rng, 16) for _ in range(rng.randint(0, 4))]
    a = fingerprint(" ".join(words), hashes, "acc1")
    b = fingerprint("  " + "   ".join(w.upper() for w in words) + "\n", list(reversed(hashes)), "acc1")
    assert a == b
    assert a != fingerprint(" ".join(words), hashes, "acc2")

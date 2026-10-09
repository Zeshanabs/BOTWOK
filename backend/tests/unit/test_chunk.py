"""Paragraph-aware ~400-token chunking."""
from __future__ import annotations

from app.research.chunk import MAX_TOKENS, TARGET_TOKENS, chunk_text, count_tokens

PARA = ("Content marketing teams increasingly rely on short-form video to reach new audiences, but measuring the "
        "return on that investment remains difficult because attribution windows are short and platforms report "
        "metrics differently. ")


def test_count_tokens_positive() -> None:
    assert count_tokens("") == 0
    assert 1 <= count_tokens("hello world") <= 4


def test_short_text_single_chunk() -> None:
    chunks = chunk_text("One paragraph only. It is short.")
    assert len(chunks) == 1 and chunks[0].index == 0 and chunks[0].token_count > 0


def test_long_text_split_near_target() -> None:
    text = "\n\n".join(PARA * 3 for _ in range(30))
    chunks = chunk_text(text)
    assert len(chunks) > 3
    assert [c.index for c in chunks] == list(range(len(chunks)))
    for c in chunks[:-1]:
        assert c.token_count <= MAX_TOKENS
        assert c.token_count >= TARGET_TOKENS * 0.4
    joined = " ".join(c.text for c in chunks)
    assert joined.count("attribution windows") == text.count("attribution windows")


def test_oversized_paragraph_split_by_sentences() -> None:
    text = PARA * 60  # one huge paragraph
    chunks = chunk_text(text)
    assert len(chunks) >= 3
    assert all(c.token_count <= MAX_TOKENS for c in chunks)


def test_headings_become_sections() -> None:
    text = "# Pricing\n\n" + "\n\n".join([PARA * 2] * 6) + "\n\n## Integrations\n\n" + "\n\n".join([PARA * 2] * 6)
    chunks = chunk_text(text)
    sections = {c.section for c in chunks}
    assert "Pricing" in sections and "Integrations" in sections


def test_empty() -> None:
    assert chunk_text("   \n\n ") == []

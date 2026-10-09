"""Paragraph-aware chunking (~400 tokens) for research_chunks."""
from __future__ import annotations

import re
from dataclasses import dataclass
from functools import lru_cache
from typing import Any

from app.research.text import sentences

TARGET_TOKENS = 400
MAX_TOKENS = 520
_HEADING_MD = re.compile(r"^\s{0,3}#{1,6}\s+(.+?)\s*#*\s*$")


@lru_cache(maxsize=1)
def _encoder() -> Any | None:
    try:
        import tiktoken
        return tiktoken.get_encoding("cl100k_base")
    except Exception:  # not installed, or BPE file not downloadable offline
        return None


def count_tokens(text: str) -> int:
    if not text:
        return 0
    enc = _encoder()
    if enc is not None:
        try:
            return len(enc.encode(text, disallowed_special=()))
        except Exception:
            pass
    return int(round(len(text.split()) / 0.75))


@dataclass
class Chunk:
    index: int
    text: str
    token_count: int
    section: str | None = None


def _is_heading(line: str) -> str | None:
    m = _HEADING_MD.match(line)
    if m:
        return m.group(1).strip()
    s = line.strip()
    if 0 < len(s) <= 90 and len(s.split()) <= 12 and not s.endswith((".", ",", ";", ":", "?", "!", "\"", "”")) \
            and s[0].isupper() and "\n" not in s:
        return s
    return None


def _split_long(paragraph: str, max_tokens: int) -> list[str]:
    parts: list[str] = []
    buf: list[str] = []
    buf_tokens = 0
    for sent in sentences(paragraph) or [paragraph]:
        t = count_tokens(sent)
        if t > max_tokens:  # a single monster sentence → hard split on words
            ws = sent.split()
            step = max(1, int(max_tokens * 0.75))
            for i in range(0, len(ws), step):
                parts.append(" ".join(ws[i:i + step]))
            continue
        if buf and buf_tokens + t > max_tokens:
            parts.append(" ".join(buf))
            buf, buf_tokens = [], 0
        buf.append(sent)
        buf_tokens += t
    if buf:
        parts.append(" ".join(buf))
    return parts


def chunk_text(text: str, *, target_tokens: int = TARGET_TOKENS, max_tokens: int = MAX_TOKENS) -> list[Chunk]:
    """Greedy paragraph packing: paragraphs are accumulated until ~``target_tokens``; oversized paragraphs are split by
    sentences; heading-like lines start a new chunk and become its ``section``."""
    if not text or not text.strip():
        return []
    paragraphs = [p.strip() for p in re.split(r"\n\s*\n|\n", text) if p.strip()]
    chunks: list[Chunk] = []
    buf: list[str] = []
    buf_tokens = 0
    section: str | None = None
    buf_section: str | None = None

    def flush() -> None:
        nonlocal buf, buf_tokens
        if buf:
            body = "\n\n".join(buf)
            chunks.append(Chunk(index=len(chunks), text=body, token_count=count_tokens(body), section=buf_section))
        buf, buf_tokens = [], 0

    for para in paragraphs:
        heading = _is_heading(para)
        if heading is not None:
            if buf_tokens >= target_tokens * 0.25:
                flush()
            section = heading
            if not buf:
                buf_section = section
            buf.append(para)
            buf_tokens += count_tokens(para)
            continue
        t = count_tokens(para)
        pieces = _split_long(para, max_tokens) if t > max_tokens else [para]
        for piece in pieces:
            pt = count_tokens(piece) if len(pieces) > 1 else t
            if buf and buf_tokens + pt > target_tokens:
                flush()
            if not buf:
                buf_section = section
            buf.append(piece)
            buf_tokens += pt
    flush()
    return chunks

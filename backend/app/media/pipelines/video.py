"""Video pipeline: ffprobe / ffmpeg wrappers via subprocess (never via a shell).

FFmpeg may be missing on a dev machine: every entry point calls `require_ffmpeg()` which raises a 501 Problem
`ffmpeg_missing`. `sniff_av_mime()` is a pure magic-byte check usable without FFmpeg.
"""
from __future__ import annotations

import asyncio
import json
import os
import shutil
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from app.core.errors import ProblemError

FFMPEG_TIMEOUT_S = 15 * 60
PROBE_TIMEOUT_S = 60
VIDEO_MIMES = frozenset({"video/mp4", "video/quicktime", "video/webm"})
AUDIO_MIMES = frozenset({"audio/mpeg", "audio/mp4", "audio/wav", "audio/x-wav", "audio/ogg", "audio/aac"})


@dataclass(frozen=True)
class VideoInfo:
    duration_ms: int | None
    width: int | None
    height: int | None
    fps: float | None
    codec: str | None
    audio_codec: str | None
    format_name: str | None
    bit_rate: int | None
    has_video: bool
    has_audio: bool

    def as_dict(self) -> dict[str, Any]:
        return dict(self.__dict__)


def ffmpeg_path() -> str | None:
    return shutil.which("ffmpeg")


def ffprobe_path() -> str | None:
    return shutil.which("ffprobe")


def ffmpeg_available() -> bool:
    return bool(ffmpeg_path() and ffprobe_path())


def require_ffmpeg() -> tuple[str, str]:
    ff, fp = ffmpeg_path(), ffprobe_path()
    if not ff or not fp:
        raise ProblemError(501, "ffmpeg_missing", "FFmpeg is not installed",
                           "Video processing needs ffmpeg and ffprobe on PATH (macOS: `brew install ffmpeg`, "
                           "Debian/Ubuntu: `apt-get install ffmpeg`; the Docker worker image ships it).")
    return ff, fp


def sniff_av_mime(data: bytes) -> str | None:
    """Magic-byte sniff for the audio/video containers we accept (no FFmpeg needed)."""
    head = data[:64]
    if len(head) >= 12 and head[4:8] == b"ftyp":
        brand = head[8:12]
        if brand in (b"heic", b"heix", b"hevc", b"mif1", b"msf1", b"avif"):
            return None  # HEIF/AVIF still images, not video
        if brand == b"qt  ":
            return "video/quicktime"
        if brand in (b"M4A ", b"M4B ", b"M4P "):
            return "audio/mp4"
        return "video/mp4"
    if head.startswith(b"\x1a\x45\xdf\xa3"):
        return "video/webm"
    if head.startswith(b"ID3") or (len(head) > 1 and head[0] == 0xFF and (head[1] & 0xE0) == 0xE0):
        return "audio/mpeg"
    if head.startswith(b"RIFF") and head[8:12] == b"WAVE":
        return "audio/wav"
    if head.startswith(b"OggS"):
        return "audio/ogg"
    return None


async def _run(args: list[str], timeout_s: float) -> tuple[bytes, bytes]:
    proc = await asyncio.create_subprocess_exec(*args, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE)
    try:
        out, err = await asyncio.wait_for(proc.communicate(), timeout=timeout_s)
    except TimeoutError as e:
        proc.kill()
        await proc.wait()
        raise ProblemError(504, "media_timeout", "Media processing timed out", " ".join(args[:2])) from e
    if proc.returncode != 0:
        tail = err.decode(errors="replace")[-800:]
        raise ProblemError(422, "media_processing_failed", "Media processing failed", tail)
    return out, err


def _parse_fps(rate: str | None) -> float | None:
    if not rate or rate in ("0/0", "0"):
        return None
    try:
        if "/" in rate:
            a, b = rate.split("/", 1)
            return round(float(a) / float(b), 3) if float(b) else None
        return round(float(rate), 3)
    except ValueError:
        return None


def parse_probe(payload: dict[str, Any]) -> VideoInfo:
    streams = payload.get("streams") or []
    fmt = payload.get("format") or {}
    v = next((s for s in streams if s.get("codec_type") == "video" and not (s.get("disposition") or {}).get("attached_pic")),
             None)
    a = next((s for s in streams if s.get("codec_type") == "audio"), None)
    dur = fmt.get("duration") or (v or {}).get("duration") or (a or {}).get("duration")
    width, height = (v or {}).get("width"), (v or {}).get("height")
    rotation = 0
    for sd in (v or {}).get("side_data_list") or []:
        if "rotation" in sd:
            rotation = abs(int(sd["rotation"])) % 180
    if rotation == 90 and width and height:
        width, height = height, width
    return VideoInfo(
        duration_ms=int(float(dur) * 1000) if dur else None, width=width, height=height,
        fps=_parse_fps((v or {}).get("avg_frame_rate") or (v or {}).get("r_frame_rate")),
        codec=(v or {}).get("codec_name"), audio_codec=(a or {}).get("codec_name"),
        format_name=fmt.get("format_name"), bit_rate=int(fmt["bit_rate"]) if fmt.get("bit_rate") else None,
        has_video=v is not None, has_audio=a is not None)


class _TempFile:
    def __init__(self, data: bytes | None = None, suffix: str = ""):
        fd, name = tempfile.mkstemp(prefix="botwok-media-", suffix=suffix)
        with os.fdopen(fd, "wb") as f:
            if data:
                f.write(data)
        self.path = Path(name)

    def __enter__(self) -> Path:
        return self.path

    def __exit__(self, *exc: object) -> None:
        self.path.unlink(missing_ok=True)


async def probe(source: bytes | str | Path) -> VideoInfo:
    """ffprobe a file path or bytes."""
    _, fp = require_ffmpeg()
    if isinstance(source, (bytes, bytearray)):
        with _TempFile(bytes(source)) as path:
            return await probe(path)
    out, _ = await _run([fp, "-v", "error", "-print_format", "json", "-show_format", "-show_streams", str(source)],
                        PROBE_TIMEOUT_S)
    try:
        return parse_probe(json.loads(out or b"{}"))
    except (ValueError, TypeError) as e:
        raise ProblemError(422, "invalid_video", "Invalid video", f"ffprobe output unreadable: {e}") from e


async def transcode(data: bytes, *, width: int | None = None, height: int | None = None, pad_color: str = "#000000",
                    fit: str = "pad", fps: float | None = None, max_duration_s: float | None = None,
                    video_codec: str = "libx264", audio_codec: str = "aac", crf: int = 23, preset: str = "veryfast",
                    audio_bitrate: str = "128k", audio_rate: int = 48000) -> bytes:
    """Re-encode to MP4 (H.264/AAC, yuv420p, faststart = moov atom first). With width/height the frame is scaled to fit
    and padded (`fit="pad"`) or scaled to cover and center-cropped (`fit="crop"`) to exactly width×height.
    `fps` forces a constant output frame rate (pass it only when the source exceeds the platform maximum)."""
    ff, _ = require_ffmpeg()
    filters: list[str] = []
    if width and height:
        w, h = int(width) // 2 * 2, int(height) // 2 * 2
        if fit == "crop":
            filters.append(f"scale={w}:{h}:force_original_aspect_ratio=increase,crop={w}:{h}")
        else:
            color = "0x" + pad_color.lstrip("#")[:6]
            filters.append(f"scale={w}:{h}:force_original_aspect_ratio=decrease,"
                           f"pad={w}:{h}:(ow-iw)/2:(oh-ih)/2:color={color}")
        filters.append("setsar=1")
    if fps:
        filters.append(f"fps={float(fps):g}")
    with _TempFile(data) as src, _TempFile(suffix=".mp4") as dst:
        args = [ff, "-y", "-hide_banner", "-loglevel", "error", "-i", str(src)]
        if max_duration_s:
            args += ["-t", f"{float(max_duration_s):.3f}"]
        if filters:
            args += ["-vf", ",".join(filters)]
        args += ["-c:v", video_codec, "-preset", preset, "-crf", str(crf), "-pix_fmt", "yuv420p",
                 "-c:a", audio_codec, "-b:a", audio_bitrate, "-ar", str(audio_rate), "-ac", "2",
                 "-movflags", "+faststart", "-map_metadata", "-1", str(dst)]
        await _run(args, FFMPEG_TIMEOUT_S)
        return dst.read_bytes()


async def extract_frame(data: bytes, at_s: float = 1.0) -> bytes:
    """Grab one frame as JPEG (cover/thumbnail)."""
    ff, _ = require_ffmpeg()
    with _TempFile(data) as src, _TempFile(suffix=".jpg") as dst:
        await _run([ff, "-y", "-hide_banner", "-loglevel", "error", "-ss", f"{max(0.0, at_s):.3f}", "-i", str(src),
                    "-frames:v", "1", "-q:v", "3", str(dst)], PROBE_TIMEOUT_S)
        out = dst.read_bytes()
    if not out:
        raise ProblemError(422, "media_processing_failed", "Could not extract a frame")
    return out

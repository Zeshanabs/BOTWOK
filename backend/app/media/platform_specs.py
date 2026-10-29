"""Declarative per-platform media specs (doc 10 §10.4, doc 26, docs/platforms/*).

Specs are DATA: update them when platforms change. Values marked `# UNVERIFIED` are not confirmed by the platform docs
we read (doc 26 "?" items / docs/platforms/open-questions.md) and are conservative Botwok defaults.
Aspect ratios are width / height (4:5 → 0.8, 1.91:1 → 1.91, 9:16 → 0.5625).

Lookup: `get_spec(platform, format, kind)` where kind is "image" | "video".
"""
from __future__ import annotations

from dataclasses import dataclass, field, replace
from typing import Literal

VERIFIED_AT = "2026-10-08"
MB = 1024 * 1024
GB = 1024 * MB

MediaKind = Literal["image", "video"]

JPEG = ("image/jpeg",)
JPEG_PNG = ("image/jpeg", "image/png")
MP4_MOV = ("video/mp4", "video/quicktime")


@dataclass(frozen=True)
class MediaSpec:
    kind: MediaKind
    mimes: tuple[str, ...]
    min_aspect: float | None = None          # width/height lower bound (None = unbounded)
    max_aspect: float | None = None          # width/height upper bound
    recommended_size: tuple[int, int] | None = None   # (w, h) render target when we have to pick
    min_width: int | None = None
    min_height: int | None = None
    max_width: int | None = None
    max_height: int | None = None
    max_pixels: int | None = None
    max_bytes: int | None = None
    min_duration_s: float | None = None
    max_duration_s: float | None = None
    min_fps: float | None = None
    max_fps: float | None = None
    video_codecs: tuple[str, ...] = ()
    audio_codecs: tuple[str, ...] = ()
    max_items: int | None = None             # per post (carousel / multi-image)
    min_items: int | None = None
    notes: str = ""

    @property
    def recommended_aspect(self) -> float | None:
        if self.recommended_size:
            return self.recommended_size[0] / self.recommended_size[1]
        return None

    @property
    def preferred_mime(self) -> str:
        return self.mimes[0]


@dataclass(frozen=True)
class FormatSpec:
    platform: str
    format: str
    image: MediaSpec | None = None
    video: MediaSpec | None = None
    notes: str = ""
    sources: tuple[str, ...] = field(default_factory=tuple)


# ---------------------------------------------------------------------------- reusable sub-specs
_IG_IMAGE = MediaSpec(kind="image", mimes=JPEG, min_aspect=0.8, max_aspect=1.91, recommended_size=(1080, 1350),
                      min_width=320, max_width=1440, max_bytes=8 * MB, notes="JPEG only, sRGB, public URL")
_IG_REELS = MediaSpec(kind="video", mimes=MP4_MOV, min_aspect=0.01, max_aspect=10.0, recommended_size=(1080, 1920),
                      max_width=1920, max_bytes=300 * MB, min_duration_s=3, max_duration_s=15 * 60, min_fps=23,
                      max_fps=60, video_codecs=("h264", "hevc"), audio_codecs=("aac",),
                      notes="moov atom at front, no edit lists, AAC ≤48 kHz, ≤25 Mbps VBR")
_IG_STORY_IMAGE = MediaSpec(kind="image", mimes=JPEG, recommended_size=(1080, 1920), max_bytes=8 * MB,
                            min_aspect=0.1, max_aspect=10.0,  # UNVERIFIED: only "9:16 recommended" documented for images
                            notes="9:16 recommended")
_IG_STORY_VIDEO = MediaSpec(kind="video", mimes=MP4_MOV, min_aspect=0.1, max_aspect=10.0, recommended_size=(1080, 1920),
                            max_bytes=100 * MB, min_duration_s=3, max_duration_s=60, min_fps=23, max_fps=60,
                            video_codecs=("h264", "hevc"), audio_codecs=("aac",))
_IG_CAROUSEL_VIDEO = MediaSpec(kind="video", mimes=MP4_MOV, min_aspect=0.8, max_aspect=1.91,  # UNVERIFIED (feed ratio)
                               recommended_size=(1080, 1350), max_bytes=300 * MB,   # UNVERIFIED
                               min_duration_s=3, max_duration_s=60,                  # UNVERIFIED
                               min_fps=23, max_fps=60, video_codecs=("h264", "hevc"), audio_codecs=("aac",),
                               max_items=10, notes="Reels-type children not supported")

_FB_IMAGE = MediaSpec(kind="image", mimes=JPEG_PNG, recommended_size=(1080, 1350),
                      max_bytes=10 * MB,  # UNVERIFIED (Facebook photo size limit not in fetched docs)
                      notes="no hard aspect limit documented for Page photos")
_FB_REELS = MediaSpec(kind="video", mimes=MP4_MOV, min_aspect=0.5625, max_aspect=0.5625, recommended_size=(1080, 1920),
                      min_width=540, min_height=960, min_duration_s=3, max_duration_s=90, min_fps=24, max_fps=60,
                      max_bytes=1 * GB,  # UNVERIFIED
                      video_codecs=("h264", "hevc", "vp9", "av1"), audio_codecs=("aac",),
                      notes="9:16; AAC 48 kHz stereo ≥128 kbps; 30 API Reels / Page / 24 h")
_FB_VIDEO = MediaSpec(kind="video", mimes=MP4_MOV, max_bytes=10 * GB,  # UNVERIFIED (public FB guidance: 10 GB / 240 min)
                      max_duration_s=240 * 60, video_codecs=("h264", "hevc"), audio_codecs=("aac",))
_FB_STORY_VIDEO = MediaSpec(kind="video", mimes=MP4_MOV, recommended_size=(1080, 1920), min_duration_s=3,
                            max_duration_s=60,  # docs contradict (60 vs 90 s): assume 60
                            min_fps=24, max_fps=60, video_codecs=("h264", "hevc"), audio_codecs=("aac",))
_FB_STORY_IMAGE = MediaSpec(kind="image", mimes=JPEG_PNG, recommended_size=(1080, 1920), max_bytes=10 * MB)  # UNVERIFIED

_THREADS_IMAGE = MediaSpec(kind="image", mimes=JPEG_PNG, min_aspect=0.1, max_aspect=10.0, min_width=320, max_width=1440,
                           max_bytes=8 * MB, recommended_size=(1080, 1350))
_THREADS_VIDEO = MediaSpec(kind="video", mimes=MP4_MOV, max_width=1920, max_bytes=1 * GB, max_duration_s=5 * 60,
                           min_fps=23, max_fps=60, recommended_size=(1080, 1920), video_codecs=("h264", "hevc"),
                           audio_codecs=("aac",), notes="9:16 recommended, ≤100 Mbps")

_LI_IMAGE = MediaSpec(kind="image", mimes=("image/jpeg", "image/png", "image/gif"), max_pixels=36_152_320,
                      recommended_size=(1200, 627),  # UNVERIFIED: common 1.91:1 guidance, not an API rule
                      max_bytes=8 * MB,  # UNVERIFIED (Images API documents pixels, not bytes)
                      notes="GIF up to 250 frames")
_LI_VIDEO = MediaSpec(kind="video", mimes=("video/mp4",), max_bytes=5 * GB,
                      min_duration_s=3, max_duration_s=30 * 60,  # UNVERIFIED (ads spec page)
                      video_codecs=("h264",), audio_codecs=("aac",), notes="multipart upload in 4 MB parts")

_X_IMAGE = MediaSpec(kind="image", mimes=("image/jpeg", "image/png", "image/webp", "image/gif"), max_bytes=5 * MB,
                     recommended_size=(1600, 900),  # UNVERIFIED: 16:9 display guidance
                     max_items=4, notes="animated GIF up to 15 MB")
_X_VIDEO = MediaSpec(kind="video", mimes=("video/mp4", "video/quicktime"), max_bytes=8 * GB, max_duration_s=20 * 60,
                     max_fps=60,  # UNVERIFIED
                     video_codecs=("h264",), audio_codecs=("aac",), recommended_size=(1920, 1080),
                     notes="v2 chunked upload; Premium: 16 GB / 125 min")

_TT_VIDEO = MediaSpec(kind="video", mimes=("video/mp4", "video/webm", "video/quicktime"), min_width=360, min_height=360,
                      max_width=4096, max_height=4096, max_bytes=4 * GB, max_duration_s=10 * 60,
                      min_duration_s=3,  # UNVERIFIED (Business API documents 3-600 s)
                      min_fps=23, max_fps=60, recommended_size=(1080, 1920), video_codecs=("h264", "hevc", "vp8", "vp9"),
                      notes="creator cap: creator_info.max_video_post_duration_sec")
_TT_PHOTO = MediaSpec(kind="image", mimes=("image/jpeg", "image/webp"), max_width=1080, max_height=1920,  # "max 1080p"
                      max_bytes=20 * MB, recommended_size=(1080, 1920), max_items=35,
                      notes="PULL_FROM_URL from a verified domain only")

_YT_VIDEO = MediaSpec(kind="video", mimes=("video/mp4", "video/quicktime", "video/webm"), max_bytes=256 * GB,
                      recommended_size=(1920, 1080), video_codecs=("h264", "hevc", "vp9", "av1"),
                      audio_codecs=("aac", "opus"))
_YT_SHORT = MediaSpec(kind="video", mimes=("video/mp4", "video/quicktime", "video/webm"), max_aspect=1.0,
                      max_duration_s=3 * 60, max_bytes=256 * GB, recommended_size=(1080, 1920),
                      video_codecs=("h264", "hevc", "vp9", "av1"), notes="auto-detected: ≤3 min, square/vertical")

_PIN_IMAGE = MediaSpec(kind="image", mimes=("image/jpeg", "image/png", "image/webp"),  # UNVERIFIED mime list
                       recommended_size=(1000, 1500), max_bytes=20 * MB,  # UNVERIFIED
                       notes="2:3 recommended")
_PIN_VIDEO = MediaSpec(kind="video", mimes=MP4_MOV, max_bytes=2 * GB, min_duration_s=4, max_duration_s=15 * 60,  # UNVERIFIED
                       recommended_size=(1080, 1920), video_codecs=("h264",), audio_codecs=("aac",))

_GBP_IMAGE = MediaSpec(kind="image", mimes=JPEG_PNG, min_width=250, min_height=250, max_bytes=5 * MB,  # UNVERIFIED
                       recommended_size=(1200, 900), notes="media by public URL only")
_GBP_VIDEO = MediaSpec(kind="video", mimes=("video/mp4",), max_bytes=75 * MB, max_duration_s=30,  # UNVERIFIED
                       notes="media by public URL only")


def _fs(platform: str, fmt: str, image: MediaSpec | None = None, video: MediaSpec | None = None,
        notes: str = "") -> tuple[tuple[str, str], FormatSpec]:
    return (platform, fmt), FormatSpec(platform=platform, format=fmt, image=image, video=video, notes=notes)


def _items(spec: MediaSpec, max_items: int | None, min_items: int | None = None) -> MediaSpec:
    return replace(spec, max_items=max_items, min_items=min_items)


SPECS: dict[tuple[str, str], FormatSpec] = dict([
    # Instagram (Professional)
    _fs("instagram", "image", image=_IG_IMAGE),
    _fs("instagram", "carousel", image=_items(_IG_IMAGE, 10, 2), video=_IG_CAROUSEL_VIDEO, notes="≤10 items, 1 post"),
    _fs("instagram", "video", video=_IG_REELS, notes="published as REELS"),
    _fs("instagram", "short_video", video=_IG_REELS),
    _fs("instagram", "story", image=_IG_STORY_IMAGE, video=_IG_STORY_VIDEO),
    # Facebook Page
    _fs("facebook", "image", image=_FB_IMAGE),
    _fs("facebook", "carousel", image=_items(_FB_IMAGE, 10, 2),  # UNVERIFIED max (attached_media pattern)
        notes="multi-photo via attached_media (param name UNVERIFIED)"),
    _fs("facebook", "video", video=_FB_VIDEO),
    _fs("facebook", "short_video", video=_FB_REELS),
    _fs("facebook", "story", image=_FB_STORY_IMAGE, video=_FB_STORY_VIDEO, notes="no API scheduling"),
    # Threads
    _fs("threads", "image", image=_THREADS_IMAGE),
    _fs("threads", "carousel", image=_items(_THREADS_IMAGE, 20, 2), video=_items(_THREADS_VIDEO, 20, 2)),
    _fs("threads", "video", video=_THREADS_VIDEO),
    _fs("threads", "short_video", video=_THREADS_VIDEO),
    # LinkedIn
    _fs("linkedin", "image", image=_LI_IMAGE),
    _fs("linkedin", "carousel", image=_items(_LI_IMAGE, 20, 2), notes="MultiImage 2–20, organic only"),
    _fs("linkedin", "video", video=_LI_VIDEO),
    _fs("linkedin", "short_video", video=_LI_VIDEO),
    _fs("linkedin", "document", notes="PDF/PPT/DOC ≤100 MB, ≤300 pages (Documents API)"),
    # X
    _fs("x", "image", image=_X_IMAGE),
    _fs("x", "carousel", image=_items(_X_IMAGE, 4, 2), notes="≤4 images"),
    _fs("x", "video", video=_X_VIDEO),
    _fs("x", "short_video", video=_X_VIDEO),
    # TikTok
    _fs("tiktok", "video", video=_TT_VIDEO),
    _fs("tiktok", "short_video", video=_TT_VIDEO),
    _fs("tiktok", "image", image=_items(_TT_PHOTO, 35, 1)),
    _fs("tiktok", "carousel", image=_items(_TT_PHOTO, 35, 2)),
    # YouTube
    _fs("youtube", "video", video=_YT_VIDEO),
    _fs("youtube", "short_video", video=_YT_SHORT),
    # Pinterest
    _fs("pinterest", "image", image=_PIN_IMAGE),
    _fs("pinterest", "carousel", image=_items(_PIN_IMAGE, 5, 2)),
    _fs("pinterest", "video", video=_PIN_VIDEO),
    _fs("pinterest", "short_video", video=_PIN_VIDEO),
    # Google Business Profile
    _fs("gbp", "image", image=_GBP_IMAGE),
    _fs("gbp", "video", video=_GBP_VIDEO),
])

DOCUMENT_SPECS: dict[str, dict[str, int]] = {"linkedin": {"max_bytes": 100 * MB, "max_pages": 300}}


def parse_aspect(value: str | float | int) -> float:
    """'4:5' → 0.8, '1.91:1' → 1.91, '16x9' → 1.777…, 0.8 → 0.8."""
    if isinstance(value, (int, float)):
        if value <= 0:
            raise ValueError("aspect must be positive")
        return float(value)
    s = value.strip().lower().replace("x", ":").replace("/", ":")
    if ":" in s:
        a, b = s.split(":", 1)
        w, h = float(a), float(b)
    else:
        w, h = float(s), 1.0
    if w <= 0 or h <= 0:
        raise ValueError("aspect must be positive")
    return w / h


def get_format_spec(platform: str, fmt: str) -> FormatSpec:
    key = (str(getattr(platform, "value", platform)), str(getattr(fmt, "value", fmt)))
    if key not in SPECS:
        raise KeyError(f"no media spec for {key[0]}/{key[1]}")
    return SPECS[key]


def get_spec(platform: str, fmt: str, kind: str) -> MediaSpec:
    fs = get_format_spec(platform, fmt)
    spec = fs.image if kind == "image" else fs.video if kind == "video" else None
    if spec is None:
        raise KeyError(f"{fs.platform}/{fs.format} does not accept {kind}")
    return spec


def list_specs() -> list[FormatSpec]:
    return list(SPECS.values())


def clamp_aspect(aspect: float, spec: MediaSpec) -> float:
    """Nearest aspect inside the spec's [min, max] range."""
    if spec.min_aspect is not None and aspect < spec.min_aspect:
        return spec.min_aspect
    if spec.max_aspect is not None and aspect > spec.max_aspect:
        return spec.max_aspect
    return aspect


def aspect_allowed(aspect: float, spec: MediaSpec, tolerance: float = 0.01) -> bool:
    if spec.min_aspect is not None and aspect < spec.min_aspect * (1 - tolerance):
        return False
    return not (spec.max_aspect is not None and aspect > spec.max_aspect * (1 + tolerance))

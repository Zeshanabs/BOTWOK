"""Media pipelines: Pillow image ops, carousel composer, platform specs, video helpers, image providers (no DB/S3)."""
from __future__ import annotations

import io

import numpy as np
import pytest
from PIL import Image

from app.core.errors import ProblemError
from app.integrations.media import registry
from app.integrations.media.base import nearest_size, parse_size
from app.integrations.media.fake_images import FakeImageProvider
from app.media import platform_specs as specs
from app.media.pipelines import image as imgp
from app.media.pipelines import video as vidp
from app.media.pipelines.carousel import compose_slides, contrast_text_color, slides_to_pdf


def _png(w: int = 400, h: int = 300, color: tuple = (200, 30, 30), mode: str = "RGB") -> bytes:
    buf = io.BytesIO()
    Image.new(mode, (w, h), color).save(buf, "PNG")
    return buf.getvalue()


def _jpeg_with_exif(w: int = 400, h: int = 200, orientation: int = 6) -> bytes:
    img = Image.new("RGB", (w, h), (10, 120, 200))
    exif = Image.Exif()
    exif[0x0112] = orientation              # Orientation
    exif[0x010F] = "SpyCam"                 # Make
    exif[0x0131] = "secret-software"        # Software
    buf = io.BytesIO()
    img.save(buf, "JPEG", exif=exif.tobytes())
    return buf.getvalue()


# ------------------------------------------------------------------ validate / reencode
def test_validate_image_reports_metadata():
    data = _png(640, 480)
    info = imgp.validate_image(data)
    assert info["mime"] == "image/png" and (info["width"], info["height"]) == (640, 480)
    assert info["sha256"] == imgp.sha256_hex(data) and info["bytes"] == len(data)
    assert info["has_alpha"] is False and info["animated"] is False


def test_validate_image_rejects_garbage_truncation_and_size():
    with pytest.raises(ProblemError) as ei:
        imgp.validate_image(b"<svg xmlns='http://www.w3.org/2000/svg'></svg>")
    assert ei.value.status_code == 422 and ei.value.type == "invalid_image"
    with pytest.raises(ProblemError):
        imgp.validate_image(_png()[:60])
    with pytest.raises(ProblemError) as ei:
        imgp.validate_image(_png(), max_bytes=10)
    assert ei.value.status_code == 413
    with pytest.raises(ProblemError):
        imgp.validate_image(b"")


def test_reencode_strips_exif_and_applies_orientation():
    data = _jpeg_with_exif(400, 200, orientation=6)
    with Image.open(io.BytesIO(data)) as src:
        assert src.getexif().get(0x010F) == "SpyCam"
    enc = imgp.reencode(data)
    assert enc.mime == "image/jpeg" and enc.ext == "jpg"
    assert (enc.width, enc.height) == (200, 400)  # rotated per EXIF orientation 6
    with Image.open(io.BytesIO(enc.data)) as out:
        assert len(out.getexif()) == 0
        assert "exif" not in out.info
    assert b"SpyCam" not in enc.data and b"secret-software" not in enc.data


def test_reencode_keeps_alpha_as_png_and_forces_jpeg_flatten():
    rgba = _png(100, 80, (0, 255, 0, 128), mode="RGBA")
    enc = imgp.reencode(rgba)
    assert enc.mime == "image/png"
    with Image.open(io.BytesIO(enc.data)) as out:
        assert out.mode == "RGBA"
    jpg = imgp.reencode(rgba, "JPEG")
    assert jpg.mime == "image/jpeg"
    with Image.open(io.BytesIO(jpg.data)) as out:
        assert out.mode == "RGB"


def test_reencode_keeps_animated_gif_animated():
    frames = [Image.new("RGB", (40, 40), c) for c in [(255, 0, 0), (0, 255, 0), (0, 0, 255)]]
    buf = io.BytesIO()
    frames[0].save(buf, "GIF", save_all=True, append_images=frames[1:], duration=80, loop=0)
    enc = imgp.reencode(buf.getvalue())
    assert enc.mime == "image/gif"
    with Image.open(io.BytesIO(enc.data)) as out:
        assert getattr(out, "n_frames", 1) == 3


def test_encode_respects_max_bytes():
    noisy = Image.effect_noise((1200, 1200), 90).convert("RGB")
    unconstrained = imgp.encode(noisy, "JPEG", quality=95)
    limit = len(unconstrained) // 3
    small = imgp.encode(noisy, "JPEG", quality=95, max_bytes=limit)
    assert len(small) <= limit


# ------------------------------------------------------------------ geometry
def test_resize_fit_and_thumbnail_and_bounds():
    img = imgp.open_image(_png(2000, 1000))
    assert imgp.resize_fit(img, 1000, 1000).size == (1000, 500)
    assert imgp.resize_fit(_png(200, 100), 1000, 1000).size == (200, 100)          # no upscale by default
    assert imgp.resize_fit(_png(200, 100), 1000, 1000, upscale=True).size == (1000, 500)
    assert max(imgp.thumbnail(_png(2000, 1000), 256).size) == 256
    assert imgp.fit_bounds(Image.new("RGB", (200, 100)), min_width=320).size == (320, 160)
    assert imgp.fit_bounds(Image.new("RGB", (3000, 1000)), max_width=1440).size == (1440, 480)


def test_smart_crop_within_budget_is_pure_crop():
    out = imgp.smart_crop_to_aspect(_png(1000, 1000), 0.8, max_crop=0.2)
    assert out.size == (800, 1000)


def test_smart_crop_beyond_budget_crops_then_pads_with_color():
    out = imgp.smart_crop_to_aspect(_png(2000, 500, (200, 30, 30)), 0.8, pad_color="#0B2545", max_crop=0.2)
    w, h = out.size
    assert abs(w / h - 0.8) < 0.01 and w == 1600
    assert out.getpixel((5, 5))[:3] == (11, 37, 69)            # padding (brand navy)
    assert out.getpixel((w // 2, h // 2))[:3] == (200, 30, 30)  # original content centered


def test_pad_only_and_saliency_focus():
    padded = imgp.pad_to_aspect(_png(1000, 500), 1.0, pad_color="#FFFFFF")
    assert padded.size == (1000, 1000) and padded.getpixel((500, 10)) == (255, 255, 255)
    # detail on the right third of a flat image → saliency crop keeps it, center crop does not
    img = Image.new("RGB", (1200, 400), (255, 255, 255))
    for x in range(900, 1200, 6):
        for y in range(400):
            img.putpixel((x, y), (0, 0, 0))
    sal = imgp.smart_crop_to_aspect(img, 1.0, max_crop=1.0, focus="saliency")
    ctr = imgp.smart_crop_to_aspect(img, 1.0, max_crop=1.0, focus="center")
    assert sal.size == ctr.size == (400, 400)
    dark = lambda im: int((np.asarray(im.convert("L")) < 128).sum())  # noqa: E731
    assert dark(sal) > dark(ctr)


def test_parse_color():
    assert imgp.parse_color("#0B2545") == (11, 37, 69)
    assert imgp.parse_color("#fff") == (255, 255, 255)
    with pytest.raises(ValueError):
        imgp.parse_color("navy")


# ------------------------------------------------------------------ carousel
def test_compose_slides_renders_brand_colored_pngs():
    slides = [{"headline": "Why claims get denied", "body": "Three root causes we see every week."},
              {"headline": "1. Eligibility", "body": "Verify coverage before the visit. " * 20},
              {"headline": "Book a 15-min audit " * 6, "body": ""}]
    out = compose_slides(slides, {"colors": {"primary": "#0B2545", "accent": "#13A89E"}, "footer": "@acme"})
    assert len(out) == 3
    for i, png in enumerate(out):
        with Image.open(io.BytesIO(png)) as im:
            assert im.format == "PNG" and im.size == (1080, 1350)
            assert im.convert("RGB").getpixel((5, 5)) == (11, 37, 69)
            if i == 0:
                assert len(np.unique(np.asarray(im.convert("L")))) > 2   # text actually drawn
    pdf = slides_to_pdf(out)
    assert pdf.startswith(b"%PDF")


def test_compose_slides_defaults_and_contrast():
    out = compose_slides([{"headline": "Hello"}])
    with Image.open(io.BytesIO(out[0])) as im:
        assert im.convert("RGB").getpixel((5, 5)) == (255, 255, 255)
    assert contrast_text_color((255, 255, 255)) == (17, 17, 17)
    assert contrast_text_color((11, 37, 69)) == (255, 255, 255)
    with pytest.raises(ValueError):
        compose_slides([])


# ------------------------------------------------------------------ platform specs
def test_platform_specs_lookup_and_aspects():
    ig = specs.get_spec("instagram", "image", "image")
    assert ig.mimes == ("image/jpeg",) and ig.max_bytes == 8 * 1024 * 1024
    assert (ig.min_aspect, ig.max_aspect) == (0.8, 1.91)
    assert specs.clamp_aspect(0.5, ig) == 0.8 and specs.clamp_aspect(3.0, ig) == 1.91
    assert specs.clamp_aspect(1.0, ig) == 1.0
    assert specs.parse_aspect("4:5") == 0.8 and specs.parse_aspect("1.91:1") == 1.91
    assert abs(specs.parse_aspect("16x9") - 16 / 9) < 1e-9
    assert specs.get_spec("instagram", "short_video", "video").max_duration_s == 900
    assert specs.get_spec("youtube", "short_video", "video").max_aspect == 1.0
    with pytest.raises(KeyError):
        specs.get_spec("tiktok", "video", "image")
    with pytest.raises(KeyError):
        specs.get_spec("myspace", "image", "image")
    assert not specs.aspect_allowed(0.5, ig) and specs.aspect_allowed(0.8, ig)
    assert all(fs.image or fs.video or fs.notes for fs in specs.list_specs())


# ------------------------------------------------------------------ video helpers
def test_sniff_av_mime():
    assert vidp.sniff_av_mime(b"\x00\x00\x00\x18ftypmp42" + b"\x00" * 20) == "video/mp4"
    assert vidp.sniff_av_mime(b"\x00\x00\x00\x14ftypqt  " + b"\x00" * 20) == "video/quicktime"
    assert vidp.sniff_av_mime(b"\x00\x00\x00\x18ftypheic" + b"\x00" * 20) is None
    assert vidp.sniff_av_mime(b"\x1a\x45\xdf\xa3" + b"\x00" * 20) == "video/webm"
    assert vidp.sniff_av_mime(b"ID3\x04" + b"\x00" * 20) == "audio/mpeg"
    assert vidp.sniff_av_mime(_png()) is None


async def test_ffmpeg_missing_is_a_clear_problem(monkeypatch):
    monkeypatch.setattr(vidp.shutil, "which", lambda name: None)
    assert vidp.ffmpeg_available() is False
    with pytest.raises(ProblemError) as ei:
        await vidp.probe(b"\x00\x00\x00\x18ftypmp42")
    assert ei.value.status_code == 501 and ei.value.type == "ffmpeg_missing"


def test_parse_probe_output():
    info = vidp.parse_probe({"format": {"duration": "12.5", "format_name": "mov,mp4", "bit_rate": "800000"},
                             "streams": [{"codec_type": "video", "codec_name": "h264", "width": 1920, "height": 1080,
                                          "avg_frame_rate": "30000/1001",
                                          "side_data_list": [{"rotation": -90}]},
                                         {"codec_type": "audio", "codec_name": "aac"}]})
    assert info.duration_ms == 12500 and (info.width, info.height) == (1080, 1920)
    assert info.fps == 29.97 and info.codec == "h264" and info.audio_codec == "aac" and info.has_audio


# ------------------------------------------------------------------ providers
async def test_fake_provider_generates_png_of_requested_size():
    imgs = await FakeImageProvider().generate("navy and teal abstract", size="512x640", n=2)
    assert len(imgs) == 2 and imgs[0].seed != imgs[1].seed
    with Image.open(io.BytesIO(imgs[0].data)) as im:
        assert im.format == "PNG" and im.size == (512, 640)
    again = await FakeImageProvider().generate("navy and teal abstract", size="512x640", n=1)
    assert again[0].data == imgs[0].data  # deterministic


def test_registry_fallback_and_explicit_provider(monkeypatch):
    monkeypatch.setattr(registry.settings, "openai_api_key", "")
    monkeypatch.setattr(registry.settings, "xai_api_key", "")
    monkeypatch.setattr(registry.settings, "app_env", "local")
    monkeypatch.delenv("BOTWOK_IMAGE_PROVIDER", raising=False)
    assert registry.get_image_provider().name == "fake"
    assert registry.available_image_providers() == ["fake"]
    with pytest.raises(ProblemError) as ei:
        registry.get_image_provider("openai")
    assert ei.value.type == "image_provider_not_configured"
    chain = registry.image_provider_chain(keys={"openai": "sk-test", "xai": "xai-test"})
    assert [p.name for p in chain] == ["openai", "xai"]
    chain = registry.image_provider_chain(keys={"openai": "sk-test", "xai": "xai-test"}, preferred=["xai"])
    assert [p.name for p in chain] == ["xai", "openai"]
    monkeypatch.setattr(registry.settings, "app_env", "production")
    with pytest.raises(ProblemError) as ei:
        registry.get_image_provider()
    assert ei.value.status_code == 501


def test_size_helpers():
    assert parse_size("1024x1536") == (1024, 1536) and parse_size("auto") == (1024, 1024)
    assert nearest_size("1100x1000", ["1024x1024", "1536x1024", "1024x1536"], "1024x1024") == "1024x1024"
    assert nearest_size("1080x1350", ["1024x1024", "1536x1024", "1024x1536"], "1024x1024") == "1024x1536"
    assert nearest_size("1080x1920", ["1024x1024", "1536x1024", "1024x1536"], "1024x1024") == "1024x1536"
    with pytest.raises(ValueError):
        parse_size("big")

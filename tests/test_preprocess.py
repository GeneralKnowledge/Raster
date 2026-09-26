"""Preprocess pipeline tests."""

from __future__ import annotations

from pathlib import Path

from PIL import Image

from app.services.image import validate_and_normalize
from app.services.preprocess import (
    PHOTO_MAX_COLORS,
    apply_preprocess,
    resolve_denoise,
    resolve_max_colors,
)


def test_photo_default_max_colors() -> None:
    assert resolve_max_colors("photo", "low", None) == 12
    assert resolve_max_colors("photo", "medium", None) == 24
    assert resolve_max_colors("photo", "high", None) == 40
    assert resolve_max_colors("logo", "medium", None) is None
    assert resolve_max_colors("logo", "medium", 8) == 8


def test_denoise_defaults() -> None:
    assert resolve_denoise("photo", None) is True
    assert resolve_denoise("logo", None) is False
    assert resolve_denoise("photo", False) is False
    assert resolve_denoise("logo", True) is True


def test_photo_quantize(
    fixtures_dir: Path,
) -> None:
    data = (fixtures_dir / "photo_sample.png").read_bytes()
    normalized = validate_and_normalize(data, "photo_sample.png")
    result = apply_preprocess(
        normalized.png_bytes,
        preset="photo",
        detail="low",
        max_colors=None,
        denoise=True,
    )
    assert result.quantized is True
    assert result.denoise is True
    assert result.max_colors == PHOTO_MAX_COLORS["low"]
    # Upscaled because long edge 120 < 800
    assert result.upscaled is True
    assert result.width == normalized.width * 2

    with Image.open(__import__("io").BytesIO(result.png_bytes)) as img:
        # Palette size after quantize should be bounded
        colors = img.convert("RGB").getcolors(maxcolors=256)
        assert colors is not None
        assert len(colors) <= 12 + 2  # small slack for alpha compositing edges


def test_logo_no_quantize_by_default(fixtures_dir: Path) -> None:
    data = (fixtures_dir / "tiny.png").read_bytes()
    normalized = validate_and_normalize(data, "tiny.png")
    result = apply_preprocess(
        normalized.png_bytes,
        preset="logo",
        detail="medium",
    )
    assert result.quantized is False
    assert result.denoise is False
    assert result.upscaled is False


def test_explicit_max_colors_triggers_quantize(fixtures_dir: Path) -> None:
    data = (fixtures_dir / "logo.png").read_bytes()
    normalized = validate_and_normalize(data, "logo.png")
    result = apply_preprocess(
        normalized.png_bytes,
        preset="logo",
        detail="medium",
        max_colors=4,
        denoise=False,
    )
    assert result.quantized is True
    assert result.max_colors == 4


def test_flatten_transparency(fixtures_dir: Path) -> None:
    data = (fixtures_dir / "transparent.png").read_bytes()
    normalized = validate_and_normalize(data, "transparent.png")
    result = apply_preprocess(
        normalized.png_bytes,
        preset="logo",
        flatten_transparency=True,
    )
    assert result.flattened is True
    with Image.open(__import__("io").BytesIO(result.png_bytes)) as img:
        # Corner should be opaque white-ish after flatten
        corner = img.convert("RGBA").getpixel((0, 0))
        assert corner[3] == 255

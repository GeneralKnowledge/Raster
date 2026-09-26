"""Preprocess pipeline tests (slim 1.x hygiene path)."""

from __future__ import annotations

import io
from pathlib import Path

from PIL import Image

from app.services.image import validate_and_normalize
from app.services.preprocess import (
    PHOTO_MAX_COLORS,
    apply_preprocess,
    resolve_denoise,
    resolve_max_colors,
)
from app.services.presets import resolve


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


def test_photo_upscale_and_denoise(fixtures_dir: Path) -> None:
    data = (fixtures_dir / "photo_sample.png").read_bytes()
    normalized = validate_and_normalize(data, "photo_sample.png")
    result = apply_preprocess(
        normalized.png_bytes,
        preset="photo",
        detail="low",
        denoise=True,
    )
    assert result.denoise is True
    assert result.upscaled is True
    assert result.width == normalized.width * 2
    assert result.max_colors == PHOTO_MAX_COLORS["low"]


def test_logo_passthrough_by_default(fixtures_dir: Path) -> None:
    data = (fixtures_dir / "tiny.png").read_bytes()
    normalized = validate_and_normalize(data, "tiny.png")
    result = apply_preprocess(
        normalized.png_bytes,
        preset="logo",
        detail="medium",
    )
    assert result.denoise is False
    assert result.upscaled is False
    assert result.flattened is False


def test_flatten_transparency(fixtures_dir: Path) -> None:
    data = (fixtures_dir / "transparent.png").read_bytes()
    normalized = validate_and_normalize(data, "transparent.png")
    result = apply_preprocess(
        normalized.png_bytes,
        preset="logo",
        flatten_transparency=True,
    )
    assert result.flattened is True
    with Image.open(io.BytesIO(result.png_bytes)) as img:
        corner = img.convert("RGBA").getpixel((0, 0))
        assert corner is not None
        assert corner[3] == 255


def test_presets_use_vtracer_1x_features() -> None:
    photo = resolve("photo", 3, "medium", max_colors=24, compression_level=2)
    assert photo.kwargs["clustering"] == "watershed"
    assert photo.kwargs["hierarchical"] == "cutout"
    assert photo.kwargs["max_colors"] == 24
    assert photo.kwargs["simplify"] == 1.2
    assert photo.kwargs["optimize"] == 2
    assert "watershed_detail" in photo.kwargs

    line = resolve("lineart", 3, "medium", compression_level=1)
    assert line.kwargs["clustering"] == "bw"
    assert line.kwargs["adaptive"] is True
    assert line.kwargs["optimize"] == 1

    pixel = resolve("pixelart", 1, "medium", compression_level=2)
    assert pixel.kwargs["mode"] == "polygon"
    assert "simplify" not in pixel.kwargs

    logo = resolve("logo", 5, "high", compression_level=3)
    assert logo.kwargs["clustering"] == "color-cluster"
    assert logo.kwargs["simplify"] == 2.5
    assert logo.kwargs["optimize"] == 2  # capped; Scour handles level 3

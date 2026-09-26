"""Preprocess + optional Pillow enhance tests."""

from __future__ import annotations

import io
from pathlib import Path

from PIL import Image, ImageDraw

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


def test_photo_upscale_without_enhance(fixtures_dir: Path) -> None:
    data = (fixtures_dir / "photo_sample.png").read_bytes()
    normalized = validate_and_normalize(data, "photo_sample.png")
    result = apply_preprocess(
        normalized.png_bytes,
        preset="photo",
        detail="low",
        denoise=True,
        pillow_enhance=False,
    )
    assert result.denoise is True
    assert result.upscaled is True
    assert result.pillow_enhance is False
    assert result.quantized is False
    assert result.max_colors == PHOTO_MAX_COLORS["low"]


def test_pillow_enhance_photo_quantizes(fixtures_dir: Path) -> None:
    data = (fixtures_dir / "photo_sample.png").read_bytes()
    result = apply_preprocess(
        data,
        preset="photo",
        detail="low",
        pillow_enhance=True,
    )
    assert result.pillow_enhance is True
    assert result.quantized is True
    assert result.max_colors == 12


def test_pillow_enhance_logo_fringe() -> None:
    img = Image.new("RGB", (64, 64), (255, 255, 255))
    d = ImageDraw.Draw(img)
    d.rectangle([8, 8, 55, 55], fill=(20, 80, 200))
    px = img.load()
    assert px is not None
    for i in range(8, 56):
        px[i, 8] = (120, 160, 220)
        px[8, i] = (90, 140, 210)
    buf = io.BytesIO()
    img.save(buf, format="PNG")

    off = apply_preprocess(buf.getvalue(), preset="logo", pillow_enhance=False)
    on = apply_preprocess(buf.getvalue(), preset="logo", pillow_enhance=True)
    assert off.fringe_cleaned is False
    assert on.fringe_cleaned is True


def test_pillow_enhance_softens_at_high_smooth(fixtures_dir: Path) -> None:
    data = (fixtures_dir / "logo.png").read_bytes()
    soft = apply_preprocess(
        data, preset="illustration", smooth_level=5, pillow_enhance=True
    )
    plain = apply_preprocess(
        data, preset="illustration", smooth_level=2, pillow_enhance=True
    )
    assert soft.edge_softened is True
    assert plain.edge_softened is False


def test_flatten_transparency(fixtures_dir: Path) -> None:
    data = (fixtures_dir / "transparent.png").read_bytes()
    result = apply_preprocess(
        data, preset="logo", flatten_transparency=True
    )
    assert result.flattened is True


def test_presets_use_vtracer_1x_features() -> None:
    photo = resolve("photo", 3, "medium", max_colors=24, compression_level=2)
    assert photo.kwargs["clustering"] == "watershed"
    assert photo.kwargs["max_colors"] == 24
    assert photo.kwargs["simplify"] == 1.2

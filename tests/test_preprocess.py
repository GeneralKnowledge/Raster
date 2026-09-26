"""Preprocess + optional Pillow enhance tests."""

from __future__ import annotations

from pathlib import Path

from app.services.image import validate_and_normalize
from app.services.preprocess import (
    PHOTO_MAX_COLORS,
    apply_preprocess,
    resolve_denoise,
    resolve_max_colors,
    resolve_pillow_enhance,
)
from app.services.presets import PHOTO_WATERSHED_DETAIL, resolve


def test_photo_default_max_colors() -> None:
    assert resolve_max_colors("photo", "low", None) == 16
    assert resolve_max_colors("photo", "medium", None) == 36
    assert resolve_max_colors("photo", "high", None) == 48
    assert resolve_max_colors("logo", "medium", None) is None
    assert resolve_max_colors("logo", "medium", 8) == 8


def test_photo_watershed_defaults() -> None:
    assert PHOTO_WATERSHED_DETAIL["low"] == 112
    assert PHOTO_WATERSHED_DETAIL["medium"] == 168
    assert PHOTO_WATERSHED_DETAIL["high"] == 220
    photo = resolve("photo", 3, "medium")
    assert photo.kwargs["max_colors"] == 36
    assert photo.kwargs["watershed_detail"] == 168


def test_denoise_defaults() -> None:
    assert resolve_denoise("photo", None) is True
    assert resolve_denoise("logo", None) is False


def test_pillow_enhance_auto_for_photo_only() -> None:
    assert resolve_pillow_enhance("photo", None, mode="auto") is True
    assert resolve_pillow_enhance("logo", None, mode="auto") is False
    assert resolve_pillow_enhance("illustration", None, mode="auto") is False
    assert resolve_pillow_enhance("logo", None, mode="always") is True
    assert resolve_pillow_enhance("photo", None, mode="never") is False
    assert resolve_pillow_enhance("photo", False, mode="auto") is False
    assert resolve_pillow_enhance("logo", True, mode="never") is True


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
    assert result.max_colors == 16


def test_pillow_enhance_noop_for_non_photo(fixtures_dir: Path) -> None:
    """Fringe/soften removed for non-photo — enhance is a no-op there."""
    data = (fixtures_dir / "logo.png").read_bytes()
    result = apply_preprocess(
        data,
        preset="logo",
        smooth_level=5,
        pillow_enhance=True,
    )
    assert result.pillow_enhance is True
    assert result.quantized is False
    assert result.fringe_cleaned is False
    assert result.edge_softened is False


def test_pillow_enhance_softens_photo_at_high_smooth(fixtures_dir: Path) -> None:
    data = (fixtures_dir / "photo_sample.png").read_bytes()
    soft = apply_preprocess(
        data, preset="photo", detail="low", smooth_level=5, pillow_enhance=True
    )
    plain = apply_preprocess(
        data, preset="photo", detail="low", smooth_level=2, pillow_enhance=True
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
    photo = resolve("photo", 3, "medium", max_colors=36, compression_level=2)
    assert photo.kwargs["clustering"] == "watershed"
    assert photo.kwargs["max_colors"] == 36
    assert photo.kwargs["simplify"] == 1.2
    assert photo.kwargs["watershed_detail"] == 168

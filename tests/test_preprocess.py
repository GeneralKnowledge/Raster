"""Preprocess pipeline tests."""

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


def test_photo_quantize_and_lanczos_upscale(fixtures_dir: Path) -> None:
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
    assert result.upscaled is True
    assert result.width == normalized.width * 2

    with Image.open(io.BytesIO(result.png_bytes)) as img:
        colors = img.convert("RGB").getcolors(maxcolors=256)
        assert colors is not None
        # After quantize + merge, should be well under the budget
        assert len(colors) <= 12 + 4


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
    with Image.open(io.BytesIO(result.png_bytes)) as img:
        corner = img.convert("RGBA").getpixel((0, 0))
        assert corner is not None
        assert corner[3] == 255


def test_aa_fringe_snap_for_logo() -> None:
    """Rare fringe colors near a flat logo should be snapped away."""
    img = Image.new("RGB", (64, 64), (255, 255, 255))
    d = ImageDraw.Draw(img)
    d.rectangle([8, 8, 55, 55], fill=(20, 80, 200))
    # Sprinkle AA-like fringe pixels
    px = img.load()
    assert px is not None
    for i in range(8, 56):
        px[i, 8] = (120, 160, 220)  # rare edge blend
        px[8, i] = (90, 140, 210)

    buf = io.BytesIO()
    img.save(buf, format="PNG")
    result = apply_preprocess(buf.getvalue(), preset="logo", detail="medium")
    assert result.fringe_cleaned is True

    with Image.open(io.BytesIO(result.png_bytes)) as out:
        colors = out.convert("RGB").getcolors(maxcolors=256)
        assert colors is not None
        assert len(colors) <= 4


def test_high_smooth_softens_edges(fixtures_dir: Path) -> None:
    data = (fixtures_dir / "logo.png").read_bytes()
    soft = apply_preprocess(
        data, preset="illustration", detail="medium", smooth_level=5
    )
    plain = apply_preprocess(
        data, preset="illustration", detail="medium", smooth_level=2
    )
    assert soft.edge_softened is True
    assert plain.edge_softened is False


def test_pixelart_skips_edge_soften(fixtures_dir: Path) -> None:
    data = (fixtures_dir / "pixel.png").read_bytes()
    result = apply_preprocess(
        data, preset="pixelart", detail="medium", smooth_level=5
    )
    assert result.edge_softened is False

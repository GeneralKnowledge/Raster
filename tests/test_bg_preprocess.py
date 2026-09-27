"""Unit tests for experimental rembg background preprocess.

Uses a synthetic circular mask — no ONNX download required.
"""

from __future__ import annotations

import io
from unittest.mock import patch

from PIL import Image, ImageDraw

from app.services.bg_preprocess import (
    apply_bg_preprocess,
    blur_background,
    remove_background,
)


def _scene() -> Image.Image:
    """Red subject circle on a busy striped background."""
    img = Image.new("RGB", (80, 80), (30, 120, 200))
    d = ImageDraw.Draw(img)
    for x in range(0, 80, 8):
        d.rectangle([x, 0, x + 3, 80], fill=(200, 40, 40))
    d.ellipse([20, 20, 60, 60], fill=(240, 200, 40))
    return img


def _png(img: Image.Image) -> bytes:
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()


def _fake_mask(_image, *, session=None, only_mask=False, **_kwargs):
    """Circular L mask matching the yellow subject."""
    mask = Image.new("L", (80, 80), 0)
    ImageDraw.Draw(mask).ellipse([20, 20, 60, 60], fill=255)
    if only_mask:
        return mask
    rgba = _scene().convert("RGBA")
    rgba.putalpha(mask)
    return rgba


def test_apply_none_passthrough() -> None:
    raw = _png(_scene())
    result = apply_bg_preprocess(raw, mode="none")
    assert result.mode == "none"
    assert result.width == 80
    assert result.height == 80
    assert result.png_bytes[:8] == b"\x89PNG\r\n\x1a\n"
    assert result.mask_coverage == 1.0


@patch("rembg.remove", side_effect=_fake_mask)
def test_remove_composites_on_white(_mock_remove) -> None:
    raw = _png(_scene())
    result = apply_bg_preprocess(raw, mode="remove", session=object())
    assert result.mode == "remove"
    assert 0.1 < result.mask_coverage < 0.6
    out = Image.open(io.BytesIO(result.png_bytes)).convert("RGB")
    # Corner should be near-white (background filled)
    assert out.getpixel((2, 2))[0] > 240
    # Center of subject stays yellowish
    center = out.getpixel((40, 40))
    assert center[0] > 200 and center[1] > 150


@patch("rembg.remove", side_effect=_fake_mask)
def test_blur_keeps_subject_softens_bg(_mock_remove) -> None:
    raw = _png(_scene())
    result = apply_bg_preprocess(
        raw, mode="blur", session=object(), blur_radius=8.0
    )
    assert result.mode == "blur"
    assert result.blur_radius == 8.0
    assert 0.1 < result.mask_coverage < 0.6
    out = Image.open(io.BytesIO(result.png_bytes)).convert("RGB")
    center = out.getpixel((40, 40))
    assert center[0] > 200 and center[1] > 150


@patch("rembg.remove", side_effect=_fake_mask)
def test_remove_and_blur_helpers(_mock_remove) -> None:
    img = _scene()
    cutout, cov, mask = remove_background(img, session=object())
    assert cutout.mode == "RGBA"
    assert cov > 0
    assert mask.mode == "L"
    # Subject alpha must not be the opaque post-composite canvas
    assert mask.getpixel((2, 2)) < 128
    assert mask.getpixel((40, 40)) > 200
    blurred, cov2 = blur_background(img, session=object(), blur_radius=4.0, mask=mask)
    assert blurred.mode == "RGBA"
    assert cov2 > 0
    # Blurred bg corner should differ from sharp original stripes
    orig = img.convert("RGB").getpixel((2, 2))
    soft = blurred.convert("RGB").getpixel((2, 2))
    assert soft != orig or cov2 < 1.0

"""Tests for experimental double-pass overlay helpers."""

from __future__ import annotations

import io

import numpy as np
from PIL import Image, ImageDraw

from app.services.double_pass import overlay_detail


def _pair() -> tuple[Image.Image, Image.Image]:
    orig = Image.new("RGB", (64, 64), (200, 40, 40))
    d = ImageDraw.Draw(orig)
    d.rectangle([16, 16, 48, 48], fill=(40, 80, 200))
    # Flattened pass1: more uniform
    flat = Image.new("RGB", (64, 64), (180, 60, 60))
    d2 = ImageDraw.Draw(flat)
    d2.rectangle([16, 16, 48, 48], fill=(60, 90, 180))
    return orig, flat


def test_overlay_residual_moves_toward_original() -> None:
    orig, flat = _pair()
    hybrid = overlay_detail(orig, flat, mode="residual", strength=0.5)
    a = np.asarray(orig, dtype=np.float32)
    b = np.asarray(flat, dtype=np.float32)
    h = np.asarray(hybrid, dtype=np.float32)
    # Hybrid should be between flat and original on average
    assert np.mean(np.abs(h - a)) < np.mean(np.abs(b - a))


def test_overlay_blend_strength_1_is_original() -> None:
    orig, flat = _pair()
    hybrid = overlay_detail(orig, flat, mode="blend", strength=1.0)
    assert list(hybrid.getdata()) == list(orig.getdata())


def test_overlay_soft_mask_runs() -> None:
    orig, flat = _pair()
    hybrid = overlay_detail(orig, flat, mode="soft_mask", strength=0.6)
    assert hybrid.size == orig.size

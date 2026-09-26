"""Optimizer (Scour) tests."""

from __future__ import annotations

from app.services.optimizer import optimize_safe

SAMPLE_SVG = """<?xml version="1.0" encoding="UTF-8"?>
<!-- Generator: test -->
<svg version="1.1" xmlns="http://www.w3.org/2000/svg" width="32" height="32">
  <metadata>secret</metadata>
  <path d="M0.0000 0.0000 L32.0000 0.0000 L32.0000 32.0000 L0.0000 32.0000 Z" fill="#ff0000"/>
</svg>
"""


def test_level_0_passthrough() -> None:
    out, optimized = optimize_safe(SAMPLE_SVG, 0)
    assert out == SAMPLE_SVG
    assert optimized is False


def test_level_2_strips_and_keeps_svg() -> None:
    out, optimized = optimize_safe(SAMPLE_SVG, 2)
    assert optimized is True
    assert "<svg" in out.lower()
    assert "path" in out.lower()
    assert "<!-- Generator" not in out


def test_level_3_valid() -> None:
    out, optimized = optimize_safe(SAMPLE_SVG, 3)
    assert optimized is True
    assert "<svg" in out.lower()


def test_fail_soft_on_garbage() -> None:
    # Scour may throw or return odd results; we must not raise
    out, optimized = optimize_safe("not svg at all {{{", 2)
    assert out == "not svg at all {{{"
    assert optimized is False

"""Paint-by-numbers spike tests."""

from __future__ import annotations

import io
from pathlib import Path

from PIL import Image, ImageDraw

from app.services.paint_by_numbers import (
    generate_paint_by_numbers,
    write_paint_by_numbers_kit,
)


def _simple_scene() -> bytes:
    img = Image.new("RGB", (120, 80), (240, 240, 240))
    d = ImageDraw.Draw(img)
    d.rectangle([10, 10, 55, 70], fill=(200, 40, 40))
    d.rectangle([65, 10, 110, 70], fill=(40, 80, 200))
    d.ellipse([40, 25, 80, 55], fill=(240, 200, 40))
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()


def test_generate_paint_by_numbers_basic() -> None:
    result = generate_paint_by_numbers(
        _simple_scene(),
        max_colors=6,
        min_region_area=20,
        merge_distance=10.0,
        max_edge=120,
    )
    assert result.width == 120
    assert result.height == 80
    assert 2 <= result.max_colors <= 6
    assert len(result.steps) == result.max_colors
    assert "<svg" in result.outline_svg.lower()
    assert "<svg" in result.numbered_svg.lower()
    assert "<text" in result.numbered_svg
    assert result.quantized_png[:8] == b"\x89PNG\r\n\x1a\n"
    assert "projector_hint" in result.manifest


def test_write_kit(tmp_path: Path) -> None:
    result = generate_paint_by_numbers(
        _simple_scene(),
        max_colors=4,
        min_region_area=20,
        max_edge=120,
    )
    out = write_paint_by_numbers_kit(result, tmp_path / "kit")
    assert (out / "outline.svg").is_file()
    assert (out / "numbered.svg").is_file()
    assert (out / "quantized.png").is_file()
    assert (out / "manifest.json").is_file()
    assert (out / "projector.html").is_file()
    step_svgs = list((out / "steps").glob("step_*.svg"))
    assert len(step_svgs) == len(result.steps)

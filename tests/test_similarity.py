"""Round-trip similarity tests: raster → SVG → raster.

Uses cairosvg only inside tests. Production optimizer never rasterizes.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from app.eval.similarity import (
    SSIM_FLOORS,
    assert_similarity_acceptable,
    format_report,
    vectorize_and_score,
)

pytest.importorskip("cairosvg")
pytest.importorskip("skimage")


FIXTURES = Path(__file__).parent / "fixtures"


@pytest.mark.parametrize(
    ("fixture", "preset"),
    [
        ("logo.png", "logo"),
        ("tiny.png", "logo"),
        ("pixel.png", "pixelart"),
        ("shape.jpg", "illustration"),
        ("photo_sample.png", "photo"),
        ("transparent.png", "logo"),
    ],
)
def test_roundtrip_similarity_meets_floor(
    fixture: str, preset: str
) -> None:
    data = (FIXTURES / fixture).read_bytes()
    report = vectorize_and_score(
        data,
        fixture,
        preset=preset,
        detail="medium",
        smooth_level=3,
        pillow_enhance=False,
        flatten_transparency=(fixture == "transparent.png"),
    )
    print("\n" + format_report(report))
    assert_similarity_acceptable(report)


@pytest.mark.parametrize("pillow_enhance", [False, True])
def test_logo_similarity_with_and_without_pillow(pillow_enhance: bool) -> None:
    data = (FIXTURES / "logo.png").read_bytes()
    report = vectorize_and_score(
        data,
        "logo.png",
        preset="logo",
        smooth_level=4,
        pillow_enhance=pillow_enhance,
    )
    print("\n" + format_report(report))
    assert_similarity_acceptable(report)


def test_pillow_enhance_ab_report(capsys: pytest.CaptureFixture[str]) -> None:
    """Informational A/B: both paths must clear floors; print side-by-side scores."""
    cases = [
        ("logo.png", "logo", 4),
        ("photo_sample.png", "photo", 3),
        ("shape.jpg", "illustration", 3),
    ]
    rows: list[str] = []
    for fixture, preset, smooth in cases:
        data = (FIXTURES / fixture).read_bytes()
        off = vectorize_and_score(
            data, fixture, preset=preset, smooth_level=smooth, pillow_enhance=False
        )
        on = vectorize_and_score(
            data, fixture, preset=preset, smooth_level=smooth, pillow_enhance=True
        )
        assert_similarity_acceptable(off)
        assert_similarity_acceptable(on)
        delta = on.ssim - off.ssim
        rows.append(
            f"{fixture:<18} {preset:<12} "
            f"off={off.ssim:.3f} on={on.ssim:.3f} Δ={delta:+.3f} "
            f"(floor={SSIM_FLOORS[preset]:.2f})"
        )
    print("\nPillow enhance A/B (SSIM vs preprocessed source):")
    for row in rows:
        print("  " + row)


def test_smooth_level_still_resembles_source() -> None:
    data = (FIXTURES / "logo.png").read_bytes()
    for level in (0, 3, 5):
        report = vectorize_and_score(
            data,
            "logo.png",
            preset="logo",
            smooth_level=level,
            pillow_enhance=False,
        )
        print("\n" + format_report(report))
        # Polygon (0) can be slightly less similar than splines on curves
        floor = 0.75 if level == 0 else SSIM_FLOORS["logo"]
        assert report.ssim >= floor, (
            f"smooth_level={level} SSIM {report.ssim:.3f} < {floor}"
        )


def test_side_by_side_comparison_written(tmp_path: Path) -> None:
    data = (FIXTURES / "logo.png").read_bytes()
    from app.eval.similarity import vectorize_and_compare

    bundle = vectorize_and_compare(
        data,
        "logo.png",
        preset="logo",
        smooth_level=3,
        pillow_enhance=False,
        out_dir=tmp_path,
    )
    assert bundle.report.comparison_path is not None
    assert bundle.report.svg_path is not None
    path = Path(bundle.report.comparison_path)
    svg_path = Path(bundle.report.svg_path)
    assert path.is_file()
    assert svg_path.is_file()
    assert path.stat().st_size > 100
    svg_text = svg_path.read_text(encoding="utf-8")
    assert "<svg" in svg_text.lower()
    assert "<path" in svg_text.lower()
    assert bundle.svg.startswith("<?xml") or "<svg" in bundle.svg.lower()
    # Strip is wider than a single panel
    assert bundle.side_by_side.width > bundle.source.width * 2
    assert_similarity_acceptable(bundle.report)


def test_vector_output_is_not_embedded_raster() -> None:
    """Guard: SVG must be path geometry, not a base64 PNG dump."""
    data = (FIXTURES / "logo.png").read_bytes()
    report = vectorize_and_score(data, "logo.png", preset="logo")
    # Re-run just to inspect SVG would need return — use pipeline pieces
    from app.services import preprocess, presets, vectorizer
    from app.services.image import validate_and_normalize

    norm = validate_and_normalize(data, "logo.png")
    pre = preprocess.apply_preprocess(norm.png_bytes, preset="logo")
    svg = vectorizer.vectorize(
        pre.png_bytes, **presets.resolve("logo", 3, "medium").kwargs
    )
    lower = svg.lower()
    assert "image/png" not in lower
    assert "base64" not in lower
    assert "<path" in lower
    assert report.processing_ok

"""Test-only SVG↔raster similarity helpers.

Production code must never rasterize SVG (optimizer stays vector-only).
These utilities exist solely to score how closely a vectorized result
resembles the source after a round-trip: raster → SVG → raster.
"""

from __future__ import annotations

import io
import re
from dataclasses import dataclass

import numpy as np
from PIL import Image
from skimage.metrics import structural_similarity as ssim

from app.services import optimizer, preprocess, presets, vectorizer
from app.services.image import validate_and_normalize


@dataclass(frozen=True)
class SimilarityReport:
    filename: str
    preset: str
    detail: str
    smooth_level: int
    pillow_enhance: bool
    width: int
    height: int
    ssim: float
    mae: float
    psnr: float
    path_count: int
    svg_bytes: int
    processing_ok: bool
    notes: str = ""


def rasterize_svg(
    svg: str,
    *,
    width: int,
    height: int,
    background: tuple[int, int, int] = (255, 255, 255),
) -> Image.Image:
    """Render SVG to an RGB Pillow image (test/eval only)."""
    import cairosvg

    png_bytes = cairosvg.svg2png(
        bytestring=svg.encode("utf-8"),
        output_width=max(1, width),
        output_height=max(1, height),
        background_color="rgb({},{},{})".format(*background),
    )
    img = Image.open(io.BytesIO(png_bytes)).convert("RGBA")
    # Flatten onto background for stable metrics
    canvas = Image.new("RGBA", img.size, (*background, 255))
    canvas.alpha_composite(img)
    return canvas.convert("RGB")


def _to_float_array(img: Image.Image) -> np.ndarray:
    return np.asarray(img.convert("RGB"), dtype=np.float64) / 255.0


def compute_metrics(
    original: Image.Image,
    rendered: Image.Image,
) -> tuple[float, float, float]:
    """Return (ssim, mae, psnr) comparing two RGB images of equal size."""
    if original.size != rendered.size:
        rendered = rendered.resize(original.size, Image.Resampling.LANCZOS)

    a = _to_float_array(original)
    b = _to_float_array(rendered)

    # channel_axis=2 for RGB; data_range=1.0 since we normalized
    score = float(
        ssim(a, b, channel_axis=2, data_range=1.0)
    )
    mae = float(np.mean(np.abs(a - b)))
    mse = float(np.mean((a - b) ** 2))
    if mse <= 1e-12:
        psnr = 99.0
    else:
        psnr = float(10.0 * np.log10(1.0 / mse))
    return score, mae, psnr


def count_paths(svg: str) -> int:
    return len(re.findall(r"<path\b", svg, flags=re.IGNORECASE))


def vectorize_and_score(
    data: bytes,
    filename: str,
    *,
    preset: str = "logo",
    detail: str = "medium",
    smooth_level: int = 3,
    compression_level: int = 2,
    max_colors: int | None = None,
    pillow_enhance: bool = False,
    denoise: bool | None = None,
    flatten_transparency: bool = False,
) -> SimilarityReport:
    """Full pipeline + round-trip similarity against the normalized source."""
    normalized = validate_and_normalize(data, filename)
    pre = preprocess.apply_preprocess(
        normalized.png_bytes,
        preset=preset,  # type: ignore[arg-type]
        detail=detail,  # type: ignore[arg-type]
        max_colors=max_colors,
        denoise=denoise,
        flatten_transparency=flatten_transparency,
        smooth_level=smooth_level,
        pillow_enhance=pillow_enhance,
    )
    resolved = presets.resolve(
        preset,  # type: ignore[arg-type]
        smooth_level,
        detail,  # type: ignore[arg-type]
        max_colors=max_colors,
        compression_level=compression_level,
    )
    vkwargs = dict(resolved.kwargs)
    if pre.quantized and "max_colors" in vkwargs:
        del vkwargs["max_colors"]

    svg = vectorizer.vectorize(pre.png_bytes, **vkwargs)
    scour_level = compression_level if compression_level >= 3 else 0
    svg, _ = optimizer.optimize_safe(svg, scour_level)

    # Compare against the preprocessed working buffer (what VTracer actually saw),
    # composited on white — fairest for alpha / flatten cases.
    source = Image.open(io.BytesIO(pre.png_bytes)).convert("RGBA")
    bg = Image.new("RGBA", source.size, (255, 255, 255, 255))
    bg.alpha_composite(source)
    source_rgb = bg.convert("RGB")

    rendered = rasterize_svg(svg, width=pre.width, height=pre.height)
    score, mae, psnr = compute_metrics(source_rgb, rendered)

    notes = ""
    if preset == "photo":
        notes = "photo is stylized; lower SSIM expected vs logos"

    return SimilarityReport(
        filename=filename,
        preset=preset,
        detail=detail,
        smooth_level=smooth_level,
        pillow_enhance=pillow_enhance,
        width=pre.width,
        height=pre.height,
        ssim=score,
        mae=mae,
        psnr=psnr,
        path_count=count_paths(svg),
        svg_bytes=len(svg.encode("utf-8")),
        processing_ok="<svg" in svg.lower() and count_paths(svg) >= 1,
        notes=notes,
    )


def format_report(report: SimilarityReport) -> str:
    return (
        f"{report.filename:<20} preset={report.preset:<12} "
        f"enh={'on' if report.pillow_enhance else 'off':<3} "
        f"SSIM={report.ssim:.3f} MAE={report.mae:.3f} PSNR={report.psnr:5.1f} "
        f"paths={report.path_count:<4} svg_B={report.svg_bytes}"
    )


# Soft floors by content class — not brittle exact matches.
# Photo is intentionally posterized so the bar is lower.
SSIM_FLOORS: dict[str, float] = {
    "logo": 0.82,
    "illustration": 0.75,
    "pixelart": 0.70,
    "lineart": 0.55,
    "photo": 0.35,
}

MAE_CEILINGS: dict[str, float] = {
    "logo": 0.08,
    "illustration": 0.12,
    "pixelart": 0.15,
    "lineart": 0.25,
    "photo": 0.35,
}


def assert_similarity_acceptable(report: SimilarityReport) -> None:
    assert report.processing_ok, f"vectorization failed for {report.filename}"
    floor = SSIM_FLOORS.get(report.preset, 0.5)
    ceil = MAE_CEILINGS.get(report.preset, 0.3)
    assert report.ssim >= floor, (
        f"SSIM {report.ssim:.3f} < floor {floor} for preset={report.preset} "
        f"file={report.filename} pillow_enhance={report.pillow_enhance}"
    )
    assert report.mae <= ceil, (
        f"MAE {report.mae:.3f} > ceiling {ceil} for preset={report.preset} "
        f"file={report.filename}"
    )

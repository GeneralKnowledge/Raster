"""Test-only SVG↔raster similarity helpers.

Production code must never rasterize SVG (optimizer stays vector-only).
These utilities exist solely to score how closely a vectorized result
resembles the source after a round-trip: raster → SVG → raster.
"""

from __future__ import annotations

import io
import re
from dataclasses import dataclass
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw, ImageFont
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
    comparison_path: str | None = None
    svg_path: str | None = None


@dataclass(frozen=True)
class ComparisonBundle:
    """In-memory panels + metrics for a single vectorization run."""

    report: SimilarityReport
    source: Image.Image
    rendered: Image.Image
    diff: Image.Image
    side_by_side: Image.Image
    svg: str = ""


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

    score = float(ssim(a, b, channel_axis=2, data_range=1.0))
    mae = float(np.mean(np.abs(a - b)))
    mse = float(np.mean((a - b) ** 2))
    if mse <= 1e-12:
        psnr = 99.0
    else:
        psnr = float(10.0 * np.log10(1.0 / mse))
    return score, mae, psnr


def absolute_diff_image(original: Image.Image, rendered: Image.Image) -> Image.Image:
    """Per-pixel abs diff, amplified for visibility."""
    if original.size != rendered.size:
        rendered = rendered.resize(original.size, Image.Resampling.LANCZOS)
    a = np.asarray(original.convert("RGB"), dtype=np.float32)
    b = np.asarray(rendered.convert("RGB"), dtype=np.float32)
    diff = np.abs(a - b)
    amplified = np.clip(diff * 4.0, 0, 255).astype(np.uint8)
    return Image.fromarray(amplified)


def _label_panel(img: Image.Image, title: str, *, min_height: int = 28) -> Image.Image:
    """Stack a text label above an image panel."""
    pad = 8
    label_h = max(min_height, 28)
    canvas = Image.new("RGB", (img.width, img.height + label_h), (245, 245, 245))
    canvas.paste(img, (0, label_h))
    draw = ImageDraw.Draw(canvas)
    try:
        font = ImageFont.load_default()
    except Exception:  # noqa: BLE001
        font = None
    draw.rectangle([0, 0, img.width, label_h], fill=(32, 32, 32))
    draw.text((pad, 8), title, fill=(255, 255, 255), font=font)
    return canvas


def build_side_by_side(
    source: Image.Image,
    rendered: Image.Image,
    *,
    ssim_score: float,
    mae: float,
    preset: str,
    pillow_enhance: bool,
    gap: int = 8,
    min_panel_width: int = 240,
) -> tuple[Image.Image, Image.Image]:
    """Return (side_by_side RGB, diff RGB). Panels: source | vector | |diff|."""
    if source.size != rendered.size:
        rendered = rendered.resize(source.size, Image.Resampling.LANCZOS)
    diff = absolute_diff_image(source, rendered)

    # Upscale tiny fixtures so comparison strips are readable
    if source.width < min_panel_width:
        scale = max(2, (min_panel_width + source.width - 1) // source.width)
        new_size = (source.width * scale, source.height * scale)
        source = source.resize(new_size, Image.Resampling.NEAREST)
        rendered = rendered.resize(new_size, Image.Resampling.NEAREST)
        diff = diff.resize(new_size, Image.Resampling.NEAREST)

    enh = "pillow on" if pillow_enhance else "pillow off"
    left = _label_panel(source, f"Source  ({preset})")
    mid = _label_panel(rendered, f"SVG re-raster  SSIM={ssim_score:.3f}")
    right = _label_panel(diff, f"|diff|x4  MAE={mae:.3f}  {enh}")

    w = left.width + gap + mid.width + gap + right.width
    h = max(left.height, mid.height, right.height)
    out = Image.new("RGB", (w, h), (220, 220, 220))
    x = 0
    for panel in (left, mid, right):
        out.paste(panel, (x, 0))
        x += panel.width + gap
    return out, diff


def count_paths(svg: str) -> int:
    return len(re.findall(r"<path\b", svg, flags=re.IGNORECASE))


def _run_pipeline(
    data: bytes,
    filename: str,
    *,
    preset: str,
    detail: str,
    smooth_level: int,
    compression_level: int,
    max_colors: int | None,
    pillow_enhance: bool,
    denoise: bool | None,
    flatten_transparency: bool,
) -> tuple[SimilarityReport, Image.Image, Image.Image, str]:
    """Shared vectorize path returning report pieces + source/rendered RGB."""
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

    source = Image.open(io.BytesIO(pre.png_bytes)).convert("RGBA")
    bg = Image.new("RGBA", source.size, (255, 255, 255, 255))
    bg.alpha_composite(source)
    source_rgb = bg.convert("RGB")

    rendered = rasterize_svg(svg, width=pre.width, height=pre.height)
    score, mae, psnr = compute_metrics(source_rgb, rendered)

    notes = ""
    if preset == "photo":
        notes = "photo is stylized; lower SSIM expected vs logos"

    report = SimilarityReport(
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
    return report, source_rgb, rendered, svg


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
    report, _, _, _ = _run_pipeline(
        data,
        filename,
        preset=preset,
        detail=detail,
        smooth_level=smooth_level,
        compression_level=compression_level,
        max_colors=max_colors,
        pillow_enhance=pillow_enhance,
        denoise=denoise,
        flatten_transparency=flatten_transparency,
    )
    return report


def vectorize_and_compare(
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
    out_dir: Path | str | None = None,
) -> ComparisonBundle:
    """Vectorize, score, and build a labeled source | SVG | diff strip.

    When ``out_dir`` is set, writes both the comparison PNG and the raw SVG.
    """
    report, source, rendered, svg = _run_pipeline(
        data,
        filename,
        preset=preset,
        detail=detail,
        smooth_level=smooth_level,
        compression_level=compression_level,
        max_colors=max_colors,
        pillow_enhance=pillow_enhance,
        denoise=denoise,
        flatten_transparency=flatten_transparency,
    )
    side, diff = build_side_by_side(
        source,
        rendered,
        ssim_score=report.ssim,
        mae=report.mae,
        preset=preset,
        pillow_enhance=pillow_enhance,
    )

    comparison_path: str | None = None
    svg_path: str | None = None
    if out_dir is not None:
        out = Path(out_dir)
        out.mkdir(parents=True, exist_ok=True)
        stem = Path(filename).stem
        enh = "pillow-on" if pillow_enhance else "pillow-off"
        base = f"{stem}__{preset}__{enh}__ssim-{report.ssim:.3f}"
        png_path = out / f"{base}.png"
        svg_out = out / f"{base}.svg"
        side.save(png_path, format="PNG")
        svg_out.write_text(svg, encoding="utf-8")
        comparison_path = str(png_path)
        svg_path = str(svg_out)
        report = SimilarityReport(
            **{
                **report.__dict__,
                "comparison_path": comparison_path,
                "svg_path": svg_path,
            }
        )

    return ComparisonBundle(
        report=report,
        source=source,
        rendered=rendered,
        diff=diff,
        side_by_side=side,
        svg=svg,
    )


def format_report(report: SimilarityReport) -> str:
    base = (
        f"{report.filename:<20} preset={report.preset:<12} "
        f"enh={'on' if report.pillow_enhance else 'off':<3} "
        f"SSIM={report.ssim:.3f} MAE={report.mae:.3f} PSNR={report.psnr:5.1f} "
        f"paths={report.path_count:<4} svg_B={report.svg_bytes}"
    )
    extras: list[str] = []
    if report.comparison_path:
        extras.append(report.comparison_path)
    if report.svg_path:
        extras.append(report.svg_path)
    if extras:
        base += "  → " + ", ".join(extras)
    return base


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

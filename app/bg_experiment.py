"""CLI A/B: baseline vs background-remove vs background-blur → vectorize.

    python -m app.bg_experiment user_tests4/input/portrait_a.jpg \\
        --out-dir artifacts/bg_experiment --preset photo --detail medium

Writes per-mode preprocessed PNG, SVG, side-by-side comparison, plus
``FINDINGS.md`` summarizing SSIM / size / path counts.

Requires optional ``rembg``: ``pip install 'rembg[cpu]'``.
"""

from __future__ import annotations

import argparse
import io
import json
import sys
import time
from dataclasses import asdict, dataclass
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

from app.eval.similarity import (
    absolute_diff_image,
    compute_metrics,
    count_paths,
    rasterize_svg,
)
from app.services import optimizer, preprocess, presets, vectorizer
from app.services.bg_preprocess import (
    DEFAULT_BLUR_RADIUS,
    DEFAULT_FILL_RGBA,
    BgMode,
    BgPreprocessResult,
    apply_bg_preprocess,
    blur_background,
    get_rembg_session,
    png_bytes as image_to_png_bytes,
    remove_background,
    subject_mask,
)
from app.services.image import validate_and_normalize


@dataclass(frozen=True)
class ModeResult:
    mode: str
    ssim: float
    mae: float
    psnr: float
    path_count: int
    svg_bytes: int
    mask_coverage: float
    preprocess_ms: float
    vectorize_ms: float
    width: int
    height: int


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="python -m app.bg_experiment",
        description=(
            "A/B photo vectorization with rembg background remove / blur "
            "(experimental, not wired into the API)."
        ),
    )
    p.add_argument("inputs", nargs="+", type=Path, help="Input raster paths")
    p.add_argument(
        "--out-dir",
        type=Path,
        default=Path("artifacts/bg_experiment"),
        help="Directory for preprocessed PNGs, SVGs, comparisons, FINDINGS",
    )
    p.add_argument(
        "--preset",
        default="photo",
        choices=["logo", "illustration", "photo", "lineart", "pixelart"],
    )
    p.add_argument("--detail", default="medium", choices=["low", "medium", "high"])
    p.add_argument("--smooth-level", type=int, default=3, choices=range(0, 6))
    p.add_argument("--compression-level", type=int, default=2, choices=range(0, 4))
    p.add_argument(
        "--modes",
        nargs="+",
        default=["none", "remove", "blur"],
        choices=["none", "remove", "blur"],
        help="Background modes to compare",
    )
    p.add_argument(
        "--blur-radius",
        type=float,
        default=DEFAULT_BLUR_RADIUS,
        help=f"Gaussian blur radius for blur mode (default {DEFAULT_BLUR_RADIUS})",
    )
    p.add_argument(
        "--pillow-enhance",
        action=argparse.BooleanOptionalAction,
        default=None,
        help="Override Pillow enhance (default: auto for preset)",
    )
    p.add_argument(
        "--also-illustration-high",
        action="store_true",
        help="Also run illustration/high (best prior portrait preset) per mode",
    )
    return p


def _label_panel(img: Image.Image, title: str) -> Image.Image:
    label_h = 28
    canvas = Image.new("RGB", (img.width, img.height + label_h), (245, 245, 245))
    canvas.paste(img.convert("RGB"), (0, label_h))
    draw = ImageDraw.Draw(canvas)
    draw.rectangle([0, 0, img.width, label_h], fill=(32, 32, 32))
    try:
        font = ImageFont.load_default()
    except Exception:  # noqa: BLE001
        font = None
    draw.text((8, 8), title, fill=(255, 255, 255), font=font)
    return canvas


def _side_by_side(
    source: Image.Image,
    rendered: Image.Image,
    *,
    mode: str,
    ssim_score: float,
    mae: float,
    gap: int = 8,
) -> Image.Image:
    if source.size != rendered.size:
        rendered = rendered.resize(source.size, Image.Resampling.LANCZOS)
    diff = absolute_diff_image(source, rendered)
    left = _label_panel(source, f"Preprocess ({mode})")
    mid = _label_panel(rendered, f"SVG re-raster  SSIM={ssim_score:.3f}")
    right = _label_panel(diff, f"|diff|x4  MAE={mae:.3f}")
    w = left.width + gap + mid.width + gap + right.width
    h = max(left.height, mid.height, right.height)
    out = Image.new("RGB", (w, h), (220, 220, 220))
    x = 0
    for panel in (left, mid, right):
        out.paste(panel, (x, 0))
        x += panel.width + gap
    return out


def _bg_stage(
    image_png: bytes,
    *,
    mode: BgMode,
    session: object | None,
    blur_radius: float,
    cached_mask: Image.Image | None,
) -> tuple[BgPreprocessResult, Image.Image | None]:
    """Apply bg mode, reusing a rembg mask across remove/blur when possible."""
    if mode == "none":
        return apply_bg_preprocess(image_png, mode="none"), cached_mask

    mask = cached_mask
    if mode == "remove":
        # Full rembg cutout once; reuse true subject alpha as mask for blur.
        if cached_mask is None and session is not None:
            out, coverage, mask = remove_background(image_png, session=session)
        else:
            assert mask is not None
            rgba = Image.open(io.BytesIO(image_png)).convert("RGBA")
            m = mask.resize(rgba.size, Image.Resampling.BILINEAR)
            cut = rgba.copy()
            cut.putalpha(m)
            canvas = Image.new("RGBA", rgba.size, DEFAULT_FILL_RGBA)
            canvas.alpha_composite(cut)
            out = canvas
            hist = m.convert("L").histogram()
            coverage = sum(hist[128:]) / (sum(hist) or 1)
        result = BgPreprocessResult(
            png_bytes=image_to_png_bytes(out),
            width=out.width,
            height=out.height,
            mode="remove",
            mask_coverage=coverage,
            blur_radius=None,
        )
        return result, mask

    # blur — obtain mask once if needed
    if mask is None and session is not None:
        mask = subject_mask(image_png, session=session)
    out, coverage = blur_background(
        image_png, session=session, blur_radius=blur_radius, mask=mask
    )
    result = BgPreprocessResult(
        png_bytes=image_to_png_bytes(out),
        width=out.width,
        height=out.height,
        mode="blur",
        mask_coverage=coverage,
        blur_radius=blur_radius,
    )
    return result, mask


def _run_one(
    data: bytes,
    filename: str,
    *,
    mode: BgMode,
    session: object | None,
    blur_radius: float,
    preset: str,
    detail: str,
    smooth_level: int,
    compression_level: int,
    pillow_enhance: bool | None,
    out_dir: Path,
    cached_mask: Image.Image | None = None,
) -> tuple[ModeResult, Image.Image | None]:
    stem = Path(filename).stem
    tag = f"{stem}__{preset}__{detail}__bg-{mode}"

    normalized = validate_and_normalize(data, filename)

    t0 = time.perf_counter()
    bg, mask = _bg_stage(
        normalized.png_bytes,
        mode=mode,
        session=session,
        blur_radius=blur_radius,
        cached_mask=cached_mask,
    )
    preprocess_ms = (time.perf_counter() - t0) * 1000.0

    enhance = preprocess.resolve_pillow_enhance(preset, pillow_enhance)  # type: ignore[arg-type]
    pre = preprocess.apply_preprocess(
        bg.png_bytes,
        preset=preset,  # type: ignore[arg-type]
        detail=detail,  # type: ignore[arg-type]
        smooth_level=smooth_level,
        pillow_enhance=enhance,
    )

    resolved = presets.resolve(
        preset,  # type: ignore[arg-type]
        smooth_level,
        detail,  # type: ignore[arg-type]
        compression_level=compression_level,
    )
    vkwargs = dict(resolved.kwargs)
    if pre.quantized and "max_colors" in vkwargs:
        del vkwargs["max_colors"]

    t1 = time.perf_counter()
    svg = vectorizer.vectorize(pre.png_bytes, **vkwargs)
    svg, _ = optimizer.optimize_safe(svg, compression_level)
    vectorize_ms = (time.perf_counter() - t1) * 1000.0

    source = Image.open(io.BytesIO(pre.png_bytes)).convert("RGBA")
    canvas = Image.new("RGBA", source.size, (255, 255, 255, 255))
    canvas.alpha_composite(source)
    source_rgb = canvas.convert("RGB")
    rendered = rasterize_svg(svg, width=pre.width, height=pre.height)
    score, mae, psnr = compute_metrics(source_rgb, rendered)

    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / f"{tag}__pre.png").write_bytes(pre.png_bytes)
    (out_dir / f"{tag}.svg").write_text(svg, encoding="utf-8")
    (out_dir / f"{tag}__bg.png").write_bytes(bg.png_bytes)

    strip = _side_by_side(
        source_rgb, rendered, mode=mode, ssim_score=score, mae=mae
    )
    strip.save(out_dir / f"{tag}__ab.jpg", quality=88, optimize=True)

    result = ModeResult(
        mode=mode,
        ssim=score,
        mae=mae,
        psnr=psnr,
        path_count=count_paths(svg),
        svg_bytes=len(svg.encode("utf-8")),
        mask_coverage=bg.mask_coverage,
        preprocess_ms=preprocess_ms,
        vectorize_ms=vectorize_ms,
        width=pre.width,
        height=pre.height,
    )
    return result, mask


def _write_findings(out_dir: Path, rows: list[dict]) -> Path:
    path = out_dir / "FINDINGS.md"
    lines = [
        "# Background remove / blur experiment",
        "",
        "Isolated rembg preprocess A/B (not wired into `/v1/vectorize`).",
        "",
        "SSIM is measured against the **post-preprocess** image fed to VTracer "
        "(fair vectorization fidelity), not the raw camera original.",
        "",
        "| Sample | Preset | Detail | Mode | SSIM | MAE | Paths | SVG | Mask | bg ms | vec ms |",
        "|--------|--------|--------|------|------|-----|-------|-----|------|-------|--------|",
    ]
    for r in rows:
        lines.append(
            f"| `{r['sample']}` | {r['preset']} | {r['detail']} | `{r['mode']}` | "
            f"{r['ssim']:.3f} | {r['mae']:.3f} | {r['path_count']} | "
            f"{r['svg_bytes'] // 1024} KB | {r['mask_coverage']:.2f} | "
            f"{r['preprocess_ms']:.0f} | {r['vectorize_ms']:.0f} |"
        )
    lines.extend(
        [
            "",
            "## How to read this",
            "",
            "- **`none`**: current pipeline (Pillow enhance auto for photo).",
            "- **`remove`**: rembg cutout on white — subject-only vectorization.",
            "- **`blur`**: rembg mask + Gaussian blur on background — keeps "
            "context but softens competing detail.",
            "",
            "Open `*__ab.jpg` strips (preprocess | SVG re-raster | |diff|) and "
            "`*__bg.png` for the rembg stage alone.",
            "",
        ]
    )
    path.write_text("\n".join(lines), encoding="utf-8")
    (out_dir / "findings.json").write_text(
        json.dumps(rows, indent=2), encoding="utf-8"
    )
    return path


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    missing = [p for p in args.inputs if not p.is_file()]
    if missing:
        for p in missing:
            print(f"Input not found: {p}", file=sys.stderr)
        return 1

    modes: list[BgMode] = list(args.modes)  # type: ignore[assignment]
    needs_rembg = any(m != "none" for m in modes)
    session = None
    if needs_rembg:
        print("Loading rembg session…", flush=True)
        session = get_rembg_session()

    configs: list[tuple[str, str]] = [(args.preset, args.detail)]
    if args.also_illustration_high:
        configs.append(("illustration", "high"))

    # Prefer remove before blur so the cutout alpha can be reused as the mask.
    ordered_modes = sorted(modes, key=lambda m: {"none": 0, "remove": 1, "blur": 2}[m])

    rows: list[dict] = []
    for path in args.inputs:
        data = path.read_bytes()
        # One rembg inference per input image (shared across presets/modes)
        shared_mask: Image.Image | None = None
        for preset, detail in configs:
            print(f"\n=== {path.name}  preset={preset} detail={detail} ===", flush=True)
            for mode in ordered_modes:
                print(f"  mode={mode} …", end=" ", flush=True)
                result, shared_mask = _run_one(
                    data,
                    path.name,
                    mode=mode,
                    session=session,
                    blur_radius=args.blur_radius,
                    preset=preset,
                    detail=detail,
                    smooth_level=args.smooth_level,
                    compression_level=args.compression_level,
                    pillow_enhance=args.pillow_enhance,
                    out_dir=args.out_dir,
                    cached_mask=shared_mask,
                )
                print(
                    f"SSIM={result.ssim:.3f} paths={result.path_count} "
                    f"svg={result.svg_bytes // 1024}KB "
                    f"(bg {result.preprocess_ms:.0f}ms + vec {result.vectorize_ms:.0f}ms)",
                    flush=True,
                )
                rows.append(
                    {
                        "sample": path.stem,
                        "preset": preset,
                        "detail": detail,
                        **asdict(result),
                    }
                )

    findings = _write_findings(args.out_dir, rows)
    print(f"\nWrote findings → {findings}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

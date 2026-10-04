"""CLI A/B: single vs double vectorize.

  python -m app.double_pass image.jpg --preset illustration --out-dir /tmp/dp
"""

from __future__ import annotations

import argparse
import io
import sys
import time
from pathlib import Path

from PIL import Image

from app.core.config import get_settings
from app.core.logging import setup_logging
from app.eval.similarity import (
    compute_metrics,
    count_paths,
    rasterize_svg,
)
from app.services import optimizer, preprocess, presets, vectorizer
from app.services.double_pass import double_vectorize
from app.services.image import validate_and_normalize
from app.services.preprocess import resolve_pillow_enhance


def _label(img: Image.Image, title: str) -> Image.Image:
    from PIL import ImageDraw

    label_h = 28
    canvas = Image.new("RGB", (img.width, img.height + label_h), (245, 245, 245))
    canvas.paste(img, (0, label_h))
    ImageDraw.Draw(canvas).text((8, 6), title, fill=(20, 20, 20))
    return canvas


def _strip(panels: list[tuple[Image.Image, str]], gap: int = 8) -> Image.Image:
    labeled = [_label(img, title) for img, title in panels]
    h = max(p.height for p in labeled)
    w = sum(p.width for p in labeled) + gap * (len(labeled) - 1)
    out = Image.new("RGB", (w, h), (230, 230, 230))
    x = 0
    for panel in labeled:
        out.paste(panel, (x, 0))
        x += panel.width + gap
    return out


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="python -m app.double_pass",
        description="A/B single-pass vs experimental double-vectorize.",
    )
    p.add_argument("input", type=Path)
    p.add_argument(
        "--out-dir",
        type=Path,
        default=Path("artifacts/double_pass"),
    )
    p.add_argument(
        "--preset",
        default="illustration",
        choices=["logo", "illustration", "photo", "lineart", "pixelart"],
    )
    p.add_argument("--detail", default="medium", choices=["low", "medium", "high"])
    p.add_argument("--smooth-level", type=int, default=3, choices=range(0, 6))
    p.add_argument("--max-colors", type=int, default=None)
    p.add_argument(
        "--strength",
        type=float,
        default=0.45,
        help="Detail reinjection strength 0–1",
    )
    p.add_argument(
        "--mode",
        default="residual",
        choices=["residual", "blend", "soft_mask"],
    )
    p.add_argument(
        "--pass1-detail",
        default=None,
        choices=["low", "medium", "high"],
        help="Optional coarser first pass",
    )
    p.add_argument("--max-edge", type=int, default=900)
    return p


def _single_pass(
    png_bytes: bytes,
    *,
    preset: str,
    detail: str,
    smooth_level: int,
    max_colors: int | None,
    pillow_enhance: bool,
) -> str:
    pre = preprocess.apply_preprocess(
        png_bytes,
        preset=preset,  # type: ignore[arg-type]
        detail=detail,  # type: ignore[arg-type]
        max_colors=max_colors,
        smooth_level=smooth_level,
        pillow_enhance=pillow_enhance,
    )
    resolved = presets.resolve(
        preset,  # type: ignore[arg-type]
        smooth_level,
        detail,  # type: ignore[arg-type]
        max_colors=max_colors,
    )
    kwargs = dict(resolved.kwargs)
    if pre.quantized and "max_colors" in kwargs:
        del kwargs["max_colors"]
    svg = vectorizer.vectorize(pre.png_bytes, **kwargs)
    svg, _ = optimizer.optimize_safe(svg, 0)
    return svg


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    setup_logging(get_settings().log_level)

    try:
        import cairosvg  # noqa: F401
    except ImportError:
        print("Need cairosvg: pip install cairosvg", file=sys.stderr)
        return 2

    if not args.input.is_file():
        print(f"Not found: {args.input}", file=sys.stderr)
        return 1

    raw = args.input.read_bytes()
    # Downscale for fair speed
    im = Image.open(io.BytesIO(raw)).convert("RGB")
    w, h = im.size
    if max(w, h) > args.max_edge:
        scale = args.max_edge / max(w, h)
        im = im.resize(
            (max(1, int(w * scale)), max(1, int(h * scale))),
            Image.Resampling.LANCZOS,
        )
    buf = io.BytesIO()
    im.save(buf, format="PNG")
    data = buf.getvalue()

    norm = validate_and_normalize(data, args.input.name)
    enhance = resolve_pillow_enhance(args.preset, None, mode="auto")

    source = Image.open(io.BytesIO(norm.png_bytes)).convert("RGB")

    t0 = time.perf_counter()
    single_svg = _single_pass(
        norm.png_bytes,
        preset=args.preset,
        detail=args.detail,
        smooth_level=args.smooth_level,
        max_colors=args.max_colors,
        pillow_enhance=enhance,
    )
    t_single = (time.perf_counter() - t0) * 1000

    t0 = time.perf_counter()
    double = double_vectorize(
        norm.png_bytes,
        preset=args.preset,
        detail=args.detail,
        smooth_level=args.smooth_level,
        max_colors=args.max_colors,
        pillow_enhance=enhance,
        overlay_mode=args.mode,  # type: ignore[arg-type]
        strength=args.strength,
        pass1_detail=args.pass1_detail,
    )
    t_double = (time.perf_counter() - t0) * 1000

    single_r = rasterize_svg(single_svg, width=source.width, height=source.height)
    double_r = rasterize_svg(double.svg, width=source.width, height=source.height)
    s_ssim, s_mae, s_psnr = compute_metrics(source, single_r)
    d_ssim, d_mae, d_psnr = compute_metrics(source, double_r)

    out = args.out_dir
    out.mkdir(parents=True, exist_ok=True)
    stem = args.input.stem
    (out / f"{stem}__single.svg").write_text(single_svg, encoding="utf-8")
    (out / f"{stem}__double.svg").write_text(double.svg, encoding="utf-8")
    (out / f"{stem}__pass1.svg").write_text(double.pass1_svg, encoding="utf-8")
    (out / f"{stem}__hybrid.png").write_bytes(double.hybrid_png)

    # 4-panel: source | single | double | |diff double-single|*4
    import numpy as np

    a = np.asarray(single_r, dtype=np.float32)
    b = np.asarray(double_r, dtype=np.float32)
    delta = np.clip(np.abs(a - b) * 4.0, 0, 255).astype(np.uint8)
    delta_img = Image.fromarray(delta)
    strip = _strip(
        [
            (source, "Source"),
            (single_r, f"Single SSIM={s_ssim:.3f}"),
            (double_r, f"Double SSIM={d_ssim:.3f}"),
            (delta_img, f"|Δ|×4  mode={args.mode} s={args.strength}"),
        ]
    )
    strip.save(out / f"{stem}__ab.png")

    delta_ssim = d_ssim - s_ssim
    print(
        f"{args.input.name}  preset={args.preset} mode={args.mode} "
        f"strength={args.strength}"
    )
    print(
        f"  single: SSIM={s_ssim:.3f} MAE={s_mae:.3f} PSNR={s_psnr:.1f} "
        f"paths={count_paths(single_svg)}  {t_single:.0f}ms"
    )
    print(
        f"  double: SSIM={d_ssim:.3f} MAE={d_mae:.3f} PSNR={d_psnr:.1f} "
        f"paths={count_paths(double.svg)}  {t_double:.0f}ms"
    )
    print(f"  ΔSSIM={delta_ssim:+.3f}  ({'better' if delta_ssim > 0.01 else 'similar/worse'})")
    print(f"  wrote {out.resolve()}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

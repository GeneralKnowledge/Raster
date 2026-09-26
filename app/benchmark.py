"""Benchmark: python -m app.benchmark examples/ --preset photo --detail low."""

from __future__ import annotations

import argparse
import re
import sys
import time
from pathlib import Path

from app.core.config import get_settings
from app.core.errors import AppError
from app.core.logging import setup_logging
from app.services import optimizer, preprocess, presets, vectorizer
from app.services.image import validate_and_normalize

IMAGE_SUFFIXES = {".png", ".jpg", ".jpeg", ".webp", ".bmp"}


def count_paths(svg: str) -> int:
    return len(re.findall(r"<path\b", svg, flags=re.IGNORECASE))


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="python -m app.benchmark",
        description="Benchmark raster→SVG conversion over a folder of images.",
    )
    p.add_argument("folder", type=Path, help="Directory of sample images")
    p.add_argument(
        "--preset",
        default="logo",
        choices=["logo", "illustration", "photo", "lineart", "pixelart"],
    )
    p.add_argument("--detail", default="medium", choices=["low", "medium", "high"])
    p.add_argument("--smooth-level", type=int, default=3, choices=range(0, 6))
    p.add_argument("--compression-level", type=int, default=2, choices=range(0, 4))
    p.add_argument("--max-colors", type=int, default=None)
    p.add_argument(
        "--pillow-enhance",
        action=argparse.BooleanOptionalAction,
        default=None,
        help="A/B optional Pillow enhance (default from PILLOW_ENHANCE env).",
    )
    return p


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    settings = get_settings()
    setup_logging(settings.log_level)
    enhance = (
        settings.pillow_enhance
        if args.pillow_enhance is None
        else args.pillow_enhance
    )

    if not args.folder.is_dir():
        print(f"Not a directory: {args.folder}", file=sys.stderr)
        return 1

    files = sorted(
        f
        for f in args.folder.iterdir()
        if f.is_file() and f.suffix.lower() in IMAGE_SUFFIXES
    )
    if not files:
        print(f"No images found in {args.folder}", file=sys.stderr)
        return 1

    header = (
        f"{'file':<24} {'dims':>11} {'in_B':>8} {'ms':>8} "
        f"{'preset':<12} {'detail':<6} {'enh':>3} {'svg_B':>8} {'ratio':>7} {'paths':>6}"
    )
    print(header)
    print("-" * len(header))

    for path in files:
        data = path.read_bytes()
        try:
            started = time.perf_counter()
            normalized = validate_and_normalize(
                data, path.name, settings=settings
            )
            pre = preprocess.apply_preprocess(
                normalized.png_bytes,
                preset=args.preset,
                detail=args.detail,
                max_colors=args.max_colors,
                smooth_level=args.smooth_level,
                pillow_enhance=enhance,
            )
            resolved = presets.resolve(
                args.preset,
                args.smooth_level,
                args.detail,
                max_colors=args.max_colors,
                compression_level=args.compression_level,
            )
            vkwargs = dict(resolved.kwargs)
            if pre.quantized and "max_colors" in vprops:
                del vprops["max_colors"]
            svg = vectorizer.vectorize(pre.png_bytes, **vprops)
            scour_level = (
                args.compression_level if args.compression_level >= 3 else 0
            )
            svg, _ = optimizer.optimize_safe(svg, scour_level)
            elapsed_ms = (time.perf_counter() - started) * 1000.0
        except AppError as exc:
            print(f"{path.name:<24} ERROR {exc.code}: {exc.message}")
            continue

        in_size = len(data)
        out_size = len(svg.encode("utf-8"))
        ratio = (out_size / in_size) if in_size else 0.0
        dims = f"{pre.width}x{pre.height}"
        enh = "on" if enhance else "off"
        print(
            f"{path.name:<24} {dims:>11} {in_size:8d} {elapsed_ms:8.1f} "
            f"{args.preset:<12} {args.detail:<6} {enh:>3} {out_size:8d} {ratio:7.2f} "
            f"{count_paths(svg):6d}"
        )

    return 0


if __name__ == "__main__":
    raise SystemExit(main())

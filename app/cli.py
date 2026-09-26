"""CLI: python -m app.cli input.png output.svg [options]."""

from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

from app.core.config import get_settings
from app.core.errors import AppError
from app.core.logging import setup_logging
from app.services import optimizer, preprocess, presets, vectorizer
from app.services.image import validate_and_normalize


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="python -m app.cli",
        description="Convert a raster image to SVG (VTracer 1.x).",
    )
    p.add_argument("input", type=Path, help="Input raster image path")
    p.add_argument("output", type=Path, help="Output SVG path")
    p.add_argument(
        "--preset",
        default="logo",
        choices=["logo", "illustration", "photo", "lineart", "pixelart"],
    )
    p.add_argument("--detail", default="medium", choices=["low", "medium", "high"])
    p.add_argument("--smooth-level", type=int, default=3, choices=range(0, 6))
    p.add_argument("--compression-level", type=int, default=2, choices=range(0, 4))
    p.add_argument("--max-colors", type=int, default=None)
    p.add_argument("--denoise", action=argparse.BooleanOptionalAction, default=None)
    p.add_argument(
        "--flatten-transparency",
        action=argparse.BooleanOptionalAction,
        default=False,
    )
    p.add_argument(
        "--pillow-enhance",
        action=argparse.BooleanOptionalAction,
        default=None,
        help=(
            "Pillow enhance override. Default auto: on for photo, off otherwise "
            "(env PILLOW_ENHANCE=auto|always|never)."
        ),
    )
    return p


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    settings = get_settings()
    setup_logging(settings.log_level)
    enhance = preprocess.resolve_pillow_enhance(
        args.preset,
        args.pillow_enhance,
        mode=settings.pillow_enhance,
    )

    if not args.input.is_file():
        print(f"Input not found: {args.input}", file=sys.stderr)
        return 1

    data = args.input.read_bytes()
    started = time.perf_counter()

    try:
        normalized = validate_and_normalize(
            data, args.input.name, settings=settings
        )
        pre = preprocess.apply_preprocess(
            normalized.png_bytes,
            preset=args.preset,
            detail=args.detail,
            max_colors=args.max_colors,
            denoise=args.denoise,
            flatten_transparency=args.flatten_transparency,
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
        if pre.quantized and "max_colors" in vkwargs:
            del vkwargs["max_colors"]
        svg = vectorizer.vectorize(pre.png_bytes, **vkwargs)
        scour_level = args.compression_level if args.compression_level >= 3 else 0
        svg, _ = optimizer.optimize_safe(svg, scour_level)
    except AppError as exc:
        print(f"Error ({exc.code}): {exc.message}", file=sys.stderr)
        return 1

    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(svg, encoding="utf-8")
    elapsed = (time.perf_counter() - started) * 1000.0
    print(
        f"Wrote {args.output} ({len(svg)} bytes) in {elapsed:.1f} ms "
        f"[preset={args.preset} detail={args.detail} pillow_enhance={enhance}]"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

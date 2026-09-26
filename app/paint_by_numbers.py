"""CLI: python -m app.paint_by_numbers input.jpg out_dir/ [options]."""

from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

from app.services.paint_by_numbers import (
    DEFAULT_MAX_COLORS,
    DEFAULT_MERGE_DISTANCE,
    DEFAULT_MIN_REGION_AREA,
    generate_paint_by_numbers,
    write_paint_by_numbers_kit,
)


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="python -m app.paint_by_numbers",
        description=(
            "Paint-by-numbers spike: quantized regions → outline + numbered "
            "SVG + per-color projector steps."
        ),
    )
    p.add_argument("input", type=Path, help="Input raster image")
    p.add_argument("out_dir", type=Path, help="Output directory for the PBN kit")
    p.add_argument(
        "--max-colors",
        type=int,
        default=DEFAULT_MAX_COLORS,
        help=f"Palette size (default {DEFAULT_MAX_COLORS})",
    )
    p.add_argument(
        "--min-region-area",
        type=int,
        default=DEFAULT_MIN_REGION_AREA,
        help=f"Drop/absorb regions smaller than this (default {DEFAULT_MIN_REGION_AREA})",
    )
    p.add_argument(
        "--merge-distance",
        type=float,
        default=DEFAULT_MERGE_DISTANCE,
        help="Near-color merge distance after quantize",
    )
    p.add_argument(
        "--max-edge",
        type=int,
        default=1000,
        help="Downscale so longest edge ≤ this (0 = no resize)",
    )
    return p


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if not args.input.is_file():
        print(f"Input not found: {args.input}", file=sys.stderr)
        return 1

    max_edge = None if args.max_edge <= 0 else args.max_edge
    data = args.input.read_bytes()
    started = time.perf_counter()
    result = generate_paint_by_numbers(
        data,
        max_colors=args.max_colors,
        min_region_area=args.min_region_area,
        merge_distance=args.merge_distance,
        max_edge=max_edge,
    )
    write_paint_by_numbers_kit(result, args.out_dir)
    elapsed = (time.perf_counter() - started) * 1000.0
    print(
        f"Wrote PBN kit → {args.out_dir}/ ({result.width}x{result.height}, "
        f"{result.max_colors} colors, {len(result.regions)} regions, "
        f"{len(result.steps)} steps) in {elapsed:.0f} ms"
    )
    print(f"  Open {args.out_dir / 'projector.html'} and use ←/→ or Next")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

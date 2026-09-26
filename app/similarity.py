"""CLI: python -m app.similarity path/or/dir --preset logo [--pillow-enhance].

Test/eval only: scores round-trip similarity (raster→SVG→raster).
Does not change the production API and never runs inside the optimizer.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from app.core.config import get_settings
from app.core.logging import setup_logging
from app.eval.similarity import (
    SSIM_FLOORS,
    format_report,
    vectorize_and_score,
)

IMAGE_SUFFIXES = {".png", ".jpg", ".jpeg", ".webp", ".bmp"}


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="python -m app.similarity",
        description="Score SVG round-trip similarity (eval only; rasterizes SVG).",
    )
    p.add_argument("path", type=Path, help="Image file or directory")
    p.add_argument(
        "--preset",
        default="logo",
        choices=["logo", "illustration", "photo", "lineart", "pixelart"],
    )
    p.add_argument("--detail", default="medium", choices=["low", "medium", "high"])
    p.add_argument("--smooth-level", type=int, default=3, choices=range(0, 6))
    p.add_argument("--max-colors", type=int, default=None)
    p.add_argument(
        "--pillow-enhance",
        action=argparse.BooleanOptionalAction,
        default=False,
    )
    p.add_argument(
        "--ab",
        action="store_true",
        help="Run both pillow_enhance off and on for each file",
    )
    return p


def _iter_files(path: Path) -> list[Path]:
    if path.is_file():
        return [path]
    return sorted(
        f
        for f in path.iterdir()
        if f.is_file() and f.suffix.lower() in IMAGE_SUFFIXES
    )


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    setup_logging(get_settings().log_level)

    try:
        import cairosvg  # noqa: F401
        import skimage  # noqa: F401
    except ImportError:
        print(
            "Install quality deps: pip install cairosvg scikit-image numpy",
            file=sys.stderr,
        )
        return 2

    files = _iter_files(args.path)
    if not files:
        print(f"No images found at {args.path}", file=sys.stderr)
        return 1

    enhance_modes = [False, True] if args.ab else [args.pillow_enhance]
    worst_ok = True

    for path in files:
        data = path.read_bytes()
        for enhance in enhance_modes:
            report = vectorize_and_score(
                data,
                path.name,
                preset=args.preset,
                detail=args.detail,
                smooth_level=args.smooth_level,
                max_colors=args.max_colors,
                pillow_enhance=enhance,
            )
            floor = SSIM_FLOORS.get(args.preset, 0.5)
            flag = "OK" if report.ssim >= floor else "LOW"
            if flag == "LOW":
                worst_ok = False
            print(f"[{flag}] {format_report(report)}  floor={floor:.2f}")

    return 0 if worst_ok else 1


if __name__ == "__main__":
    raise SystemExit(main())

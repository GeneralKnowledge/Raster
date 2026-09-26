"""Optional Pillow enhance path for photo presets.

Isolated so it is easy to remove if experiments show no benefit:

1. Set ``PILLOW_ENHANCE=never`` (or pass ``pillow_enhance=false``)
2. Delete this file: ``app/services/preprocess_pillow.py``
3. Remove the ``pillow_enhance`` import/branch in ``preprocess.py``
4. Drop the form/CLI/env wiring (search for ``pillow_enhance`` / ``PILLOW_ENHANCE``)

Tuned from A/B: non-photo presets gained ~0 SSIM from fringe/soften, while
photos gained ~+0.09 SSIM from median-cut + color merge. This module is
therefore photo-only (quantize + merge; light soften at high smooth_level).
"""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass

from PIL import Image, ImageFilter

from app.models import DetailLevel, PresetName

COLOR_MERGE_DISTANCE: dict[DetailLevel, float] = {
    "low": 42.0,
    "medium": 28.0,
    "high": 18.0,
}


@dataclass(frozen=True)
class PillowEnhanceResult:
    image: Image.Image
    quantized: bool
    color_merged: bool
    fringe_cleaned: bool
    edge_softened: bool


def _color_distance(a: tuple[int, int, int], b: tuple[int, int, int]) -> float:
    return float(
        (a[0] - b[0]) ** 2 + (a[1] - b[1]) ** 2 + (a[2] - b[2]) ** 2
    ) ** 0.5


def merge_palette_colors(
    img: Image.Image,
    *,
    max_distance: float,
) -> tuple[Image.Image, bool]:
    """Collapse similar RGB colors (Vectorizer.io colormerge-style analogue)."""
    rgba = img.convert("RGBA")
    rgb = rgba.convert("RGB")
    pixels = list(rgb.getdata())
    if not pixels:
        return img, False

    counts = Counter(pixels)
    ordered = [c for c, _ in counts.most_common()]
    mapping: dict[tuple[int, int, int], tuple[int, int, int]] = {}
    representatives: list[tuple[int, int, int]] = []

    for color in ordered:
        matched: tuple[int, int, int] | None = None
        for rep in representatives:
            if _color_distance(color, rep) <= max_distance:
                matched = rep
                break
        if matched is None:
            representatives.append(color)
            mapping[color] = color
        else:
            mapping[color] = matched

    if len(representatives) == len(ordered):
        return img, False

    merged = [mapping[p] for p in pixels]
    out_rgb = Image.new("RGB", rgb.size)
    out_rgb.putdata(merged)
    out = out_rgb.convert("RGBA")
    out.putalpha(rgba.getchannel("A"))
    return out, True


def apply_pillow_enhance(
    img: Image.Image,
    *,
    preset: PresetName,
    detail: DetailLevel,
    max_colors: int | None,
    smooth_level: int,
) -> PillowEnhanceResult:
    """Run photo-only Pillow enhance (quantize + merge + optional soften)."""
    if preset != "photo":
        return PillowEnhanceResult(
            image=img,
            quantized=False,
            color_merged=False,
            fringe_cleaned=False,
            edge_softened=False,
        )

    quantized = False
    color_merged = False
    edge_softened = False

    if max_colors is not None:
        rgba = img.convert("RGBA")
        rgb = rgba.convert("RGB")
        quantized_img = rgb.quantize(
            colors=max_colors,
            method=Image.Quantize.MEDIANCUT,
            dither=Image.Dither.NONE,
        )
        rgb_out = quantized_img.convert("RGB")
        out_img = rgb_out.convert("RGBA")
        out_img.putalpha(rgba.getchannel("A"))
        img = out_img
        quantized = True

        img, color_merged = merge_palette_colors(
            img,
            max_distance=COLOR_MERGE_DISTANCE[detail],
        )

    if smooth_level >= 4:
        radius = 0.45 if smooth_level == 4 else 0.7
        rgb = img.convert("RGB").filter(ImageFilter.GaussianBlur(radius=radius))
        alpha = img.getchannel("A")
        img = rgb.convert("RGBA")
        img.putalpha(alpha)
        edge_softened = True

    return PillowEnhanceResult(
        image=img,
        quantized=quantized,
        color_merged=color_merged,
        fringe_cleaned=False,
        edge_softened=edge_softened,
    )

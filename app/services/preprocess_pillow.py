"""Optional Pillow enhance path for A/B vs native VTracer 1.x.

This module is deliberately isolated so it is easy to remove if experiments
show no benefit:

1. Set ``PILLOW_ENHANCE=false`` (default) and stop sending ``pillow_enhance=true``
2. Delete this file: ``app/services/preprocess_pillow.py``
3. Remove the ``pillow_enhance`` import/branch in ``preprocess.py``
4. Drop the form/CLI/env wiring (search for ``pillow_enhance`` / ``PILLOW_ENHANCE``)

Steps applied when enabled:
- median-cut quantize (photo or explicit max_colors)
- color merge (near-duplicate palette collapse)
- AA fringe snap (logo / illustration / lineart)
- light Gaussian soften at smooth_level >= 4 (not pixelart)
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

FRINGE_MIN_FREQ = 0.004
FRINGE_DOMINANT_FREQ = 0.02
FRINGE_MAX_COLORS_FOR_SNAP = 48


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
    """Collapse similar RGB colors (Vectorizer.io colormergefactor analogue)."""
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


def snap_aa_fringe(img: Image.Image) -> tuple[Image.Image, bool]:
    """Snap rare fringe colors to nearest dominant color (logo AA cleanup)."""
    rgba = img.convert("RGBA")
    rgb = rgba.convert("RGB")
    pixels = list(rgb.getdata())
    n = len(pixels)
    if n == 0:
        return img, False

    counts = Counter(pixels)
    unique = len(counts)
    if unique <= 2 or unique > FRINGE_MAX_COLORS_FOR_SNAP:
        return img, False

    dominant = {
        c for c, cnt in counts.items() if (cnt / n) >= FRINGE_DOMINANT_FREQ
    }
    if len(dominant) < 2:
        dominant = {c for c, _ in counts.most_common(8)}

    fringe = {
        c
        for c, cnt in counts.items()
        if c not in dominant
        and ((cnt / n) < FRINGE_MIN_FREQ or unique <= 16)
    }
    if not fringe:
        return img, False

    dom_list = list(dominant)
    mapping: dict[tuple[int, int, int], tuple[int, int, int]] = {
        c: c for c in counts
    }
    for color in fringe:
        mapping[color] = min(dom_list, key=lambda d: _color_distance(color, d))

    remapped = [mapping[p] for p in pixels]
    out_rgb = Image.new("RGB", rgb.size)
    out_rgb.putdata(remapped)
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
    """Run optional Pillow enhance steps on an RGBA image."""
    quantized = False
    color_merged = False
    fringe_cleaned = False
    edge_softened = False

    user_set_colors = max_colors is not None
    needs_quant = preset == "photo" or user_set_colors

    if needs_quant and max_colors is not None:
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

    if preset in {"logo", "illustration", "lineart"}:
        img, fringe_cleaned = snap_aa_fringe(img)

    if (
        preset != "pixelart"
        and smooth_level >= 4
        and not (preset == "lineart" and smooth_level < 5)
    ):
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
        fringe_cleaned=fringe_cleaned,
        edge_softened=edge_softened,
    )

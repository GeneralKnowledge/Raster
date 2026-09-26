"""Preprocessing inspired by Vectorizer.io / Vector Magic *controls*.

Commercial tools win on smoothness mainly via:
1. Clean segmentation / limited palettes (color merge, not noisy clusters)
2. Using anti-aliasing as a cue — or removing fringe when clustering can't
3. Upscaling small inputs with a good filter before tracing
4. Noise reduction before region growth
5. Curve fitting / roundness (handled in presets → VTracer spline params)

We approximate (1)–(4) here with Pillow. Photo mode remains a stylized
poster / illustration — not continuous-tone photographic fidelity.
"""

from __future__ import annotations

import io
from collections import Counter
from dataclasses import dataclass

from PIL import Image, ImageFilter

from app.models import DetailLevel, PresetName

# Photo defaults for max_colors by detail (Vectorizer.io-style palette budgets)
PHOTO_MAX_COLORS: dict[DetailLevel, int] = {
    "low": 12,
    "medium": 24,
    "high": 40,
}

PHOTO_UPSCALE_MIN_EDGE = 800

# Merge distances roughly analogous to Vectorizer.io colormergefactor
# (Euclidean RGB 0–255). Higher = more aggressive palette collapse.
COLOR_MERGE_DISTANCE: dict[DetailLevel, float] = {
    "low": 42.0,
    "medium": 28.0,
    "high": 18.0,
}

# Logo / illustration: snap rare AA fringe colors to nearest dominant color
FRINGE_MIN_FREQ = 0.004  # colors below this fraction are fringe candidates
FRINGE_DOMINANT_FREQ = 0.02  # anchors must be at least this common
FRINGE_MAX_COLORS_FOR_SNAP = 48  # skip if already highly multicolored


@dataclass(frozen=True)
class PreprocessResult:
    png_bytes: bytes
    width: int
    height: int
    max_colors: int | None
    denoise: bool
    flattened: bool
    upscaled: bool
    quantized: bool
    color_merged: bool
    fringe_cleaned: bool
    edge_softened: bool


def resolve_max_colors(
    preset: PresetName,
    detail: DetailLevel,
    max_colors: int | None,
) -> int | None:
    if max_colors is not None:
        return max(2, min(64, max_colors))
    if preset == "photo":
        return PHOTO_MAX_COLORS[detail]
    return None


def resolve_denoise(
    preset: PresetName,
    denoise: bool | None,
) -> bool:
    if denoise is not None:
        return denoise
    return preset == "photo"


def _image_to_png_bytes(img: Image.Image) -> bytes:
    out = io.BytesIO()
    img.save(out, format="PNG")
    return out.getvalue()


def _color_distance(a: tuple[int, int, int], b: tuple[int, int, int]) -> float:
    return float(
        (a[0] - b[0]) ** 2 + (a[1] - b[1]) ** 2 + (a[2] - b[2]) ** 2
    ) ** 0.5


def _merge_palette_colors(
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
    # Process frequent colors first so they become merge targets
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


def _snap_aa_fringe(img: Image.Image) -> tuple[Image.Image, bool]:
    """Snap rare fringe colors to nearest dominant color (logo AA cleanup).

    Vector Magic uses blending to place sub-pixel edges; VTracer 0.6 cannot.
    Removing rare AA fringe colors before clustering yields cleaner flats and
    smoother outlines instead of speckled halo paths.
    """
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
        c
        for c, cnt in counts.items()
        if (cnt / n) >= FRINGE_DOMINANT_FREQ
    }
    if len(dominant) < 2:
        # Fall back to top-K colors
        dominant = {c for c, _ in counts.most_common(8)}

    fringe = {
        c
        for c, cnt in counts.items()
        if c not in dominant
        and (
            (cnt / n) < FRINGE_MIN_FREQ
            # Limited-palette logos: any non-dominant color is likely AA fringe
            or unique <= 16
        )
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


def apply_preprocess(
    png_bytes: bytes,
    *,
    preset: PresetName,
    detail: DetailLevel = "medium",
    max_colors: int | None = None,
    denoise: bool | None = None,
    flatten_transparency: bool = False,
    smooth_level: int = 3,
) -> PreprocessResult:
    """Apply flatten / upscale / denoise / quantize / merge / fringe cleanup.

    Always runs when ``preset=photo``, ``max_colors`` is set, flatten is on,
    or logo/illustration fringe cleanup is useful. Pixelart skips softening.
    """
    effective_colors = resolve_max_colors(preset, detail, max_colors)
    do_denoise = resolve_denoise(preset, denoise)
    user_set_colors = max_colors is not None
    needs_quant = preset == "photo" or user_set_colors
    # Logo/illustration benefit from fringe snap even without explicit palette
    needs_fringe = preset in {"logo", "illustration", "lineart"}
    needs_work = (
        needs_quant
        or flatten_transparency
        or needs_fringe
        or do_denoise
    )

    with Image.open(io.BytesIO(png_bytes)) as img:
        img = img.convert("RGBA")
        width, height = img.size
        flattened = False
        upscaled = False
        quantized = False
        color_merged = False
        fringe_cleaned = False
        edge_softened = False

        if not needs_work:
            return PreprocessResult(
                png_bytes=png_bytes,
                width=width,
                height=height,
                max_colors=None,
                denoise=False,
                flattened=False,
                upscaled=False,
                quantized=False,
                color_merged=False,
                fringe_cleaned=False,
                edge_softened=False,
            )

        if flatten_transparency:
            background = Image.new("RGBA", img.size, (255, 255, 255, 255))
            background.alpha_composite(img)
            img = background.convert("RGBA")
            flattened = True

        # Photo: 2× upscale small inputs with LANCZOS (not NEAREST).
        # Soft upscaling preserves edge ramps that spline fitting can follow;
        # nearest-neighbor invents jagged stairs that fight smoothness.
        if preset == "photo":
            long_edge = max(width, height)
            if long_edge < PHOTO_UPSCALE_MIN_EDGE:
                img = img.resize(
                    (width * 2, height * 2),
                    Image.Resampling.LANCZOS,
                )
                width, height = img.size
                upscaled = True

        if do_denoise and (preset == "photo" or user_set_colors):
            # Light median: Vectorizer.io-style noise reduction for JPEG/photo
            rgb = img.convert("RGB").filter(ImageFilter.MedianFilter(size=3))
            alpha = img.getchannel("A")
            img = rgb.convert("RGBA")
            img.putalpha(alpha)

        if effective_colors is not None and needs_quant:
            rgba = img.convert("RGBA")
            rgb = rgba.convert("RGB")
            quantized_img = rgb.quantize(
                colors=effective_colors,
                method=Image.Quantize.MEDIANCUT,
                dither=Image.Dither.NONE,
            )
            rgb_out = quantized_img.convert("RGB")
            out_img = rgb_out.convert("RGBA")
            out_img.putalpha(rgba.getchannel("A"))
            img = out_img
            quantized = True

            # Color merge after quantize (colormergefactor analogue)
            img, color_merged = _merge_palette_colors(
                img,
                max_distance=COLOR_MERGE_DISTANCE[detail],
            )

        if needs_fringe and preset != "pixelart":
            img, fringe_cleaned = _snap_aa_fringe(img)

        # High smooth_level: slight blur reduces staircasing before clustering
        # (Vectorizer.io "roundness" / mild antialias cue). Skip pixelart.
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

        return PreprocessResult(
            png_bytes=_image_to_png_bytes(img),
            width=width,
            height=height,
            max_colors=effective_colors,
            denoise=bool(do_denoise and (preset == "photo" or user_set_colors)),
            flattened=flattened,
            upscaled=upscaled,
            quantized=quantized,
            color_merged=color_merged,
            fringe_cleaned=fringe_cleaned,
            edge_softened=edge_softened,
        )

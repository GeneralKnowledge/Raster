"""Preprocess pipeline: light hygiene + optional Pillow enhance.

Default path trusts VTracer 1.x (max_colors / simplify / watershed).
Optional enhance lives in ``preprocess_pillow.py`` for easy A/B and removal.
"""

from __future__ import annotations

import io
from dataclasses import dataclass

from PIL import Image, ImageFilter

from app.models import DetailLevel, PresetName
from app.services.presets import PHOTO_MAX_COLORS, resolve_max_colors

PHOTO_UPSCALE_MIN_EDGE = 800


@dataclass(frozen=True)
class PreprocessResult:
    png_bytes: bytes
    width: int
    height: int
    max_colors: int | None
    denoise: bool
    flattened: bool
    upscaled: bool
    # Optional Pillow enhance telemetry (always present; false when disabled)
    pillow_enhance: bool = False
    quantized: bool = False
    color_merged: bool = False
    fringe_cleaned: bool = False
    edge_softened: bool = False


def resolve_denoise(
    preset: PresetName,
    denoise: bool | None,
) -> bool:
    if denoise is not None:
        return denoise
    return preset == "photo"


def apply_preprocess(
    png_bytes: bytes,
    *,
    preset: PresetName,
    detail: DetailLevel = "medium",
    max_colors: int | None = None,
    denoise: bool | None = None,
    flatten_transparency: bool = False,
    smooth_level: int = 3,
    pillow_enhance: bool = False,
) -> PreprocessResult:
    """Validate-ready PNG hygiene, optionally followed by Pillow enhance."""
    effective_colors = resolve_max_colors(preset, detail, max_colors)
    do_denoise = resolve_denoise(preset, denoise)
    needs_work = (
        flatten_transparency
        or do_denoise
        or preset == "photo"
        or pillow_enhance
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
            out = io.BytesIO()
            img.save(out, format="PNG")
            return PreprocessResult(
                png_bytes=out.getvalue(),
                width=width,
                height=height,
                max_colors=effective_colors,
                denoise=False,
                flattened=False,
                upscaled=False,
            )

        if flatten_transparency:
            background = Image.new("RGBA", img.size, (255, 255, 255, 255))
            background.alpha_composite(img)
            img = background.convert("RGBA")
            flattened = True

        if preset == "photo":
            long_edge = max(width, height)
            if long_edge < PHOTO_UPSCALE_MIN_EDGE:
                img = img.resize(
                    (width * 2, height * 2),
                    Image.Resampling.LANCZOS,
                )
                width, height = img.size
                upscaled = True

        if do_denoise:
            rgb = img.convert("RGB").filter(ImageFilter.MedianFilter(size=3))
            alpha = img.getchannel("A")
            img = rgb.convert("RGBA")
            img.putalpha(alpha)

        if pillow_enhance:
            # Isolated import so deleting preprocess_pillow.py is obvious at call site
            from app.services.preprocess_pillow import apply_pillow_enhance

            enhanced = apply_pillow_enhance(
                img,
                preset=preset,
                detail=detail,
                max_colors=effective_colors,
                smooth_level=smooth_level,
            )
            img = enhanced.image
            quantized = enhanced.quantized
            color_merged = enhanced.color_merged
            fringe_cleaned = enhanced.fringe_cleaned
            edge_softened = enhanced.edge_softened
            width, height = img.size

        out = io.BytesIO()
        img.save(out, format="PNG")
        return PreprocessResult(
            png_bytes=out.getvalue(),
            width=width,
            height=height,
            max_colors=effective_colors,
            denoise=do_denoise,
            flattened=flattened,
            upscaled=upscaled,
            pillow_enhance=pillow_enhance,
            quantized=quantized,
            color_merged=color_merged,
            fringe_cleaned=fringe_cleaned,
            edge_softened=edge_softened,
        )


__all__ = [
    "PHOTO_MAX_COLORS",
    "PHOTO_UPSCALE_MIN_EDGE",
    "PreprocessResult",
    "apply_preprocess",
    "resolve_denoise",
    "resolve_max_colors",
]

"""Light preprocess — prefer VTracer 1.x native max_colors / simplify / optimize.

Kept minimal on purpose: flatten transparency, optional denoise, and photo
upscale for tiny inputs. Heavy Pillow posterize / fringe / soften logic was
removed in favor of Config.max_colors, watershed, and simplify.
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
    smooth_level: int = 3,  # kept for API compat; unused in slim pipeline
) -> PreprocessResult:
    """Light hygiene only; color budget is handled by VTracer ``max_colors``."""
    del smooth_level  # reserved / API-compat
    effective_colors = resolve_max_colors(preset, detail, max_colors)
    do_denoise = resolve_denoise(preset, denoise)
    needs_work = flatten_transparency or do_denoise or preset == "photo"

    with Image.open(io.BytesIO(png_bytes)) as img:
        img = img.convert("RGBA")
        width, height = img.size
        flattened = False
        upscaled = False

        if not needs_work:
            # Always re-encode so callers can safely pass format="png" to VTracer
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
        )


# Re-export for tests that import from preprocess historically
__all__ = [
    "PHOTO_MAX_COLORS",
    "PHOTO_UPSCALE_MIN_EDGE",
    "PreprocessResult",
    "apply_preprocess",
    "resolve_denoise",
    "resolve_max_colors",
]

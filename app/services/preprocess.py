"""Preprocessing inspired by Vectorizer.io / Vector Magic controls.

Produces cleaner flats for VTracer. Photo mode yields a stylized
poster / illustration — not continuous-tone photographic fidelity.
"""

from __future__ import annotations

import io
from dataclasses import dataclass

from PIL import Image, ImageFilter

from app.models import DetailLevel, PresetName

# Photo defaults for max_colors by detail
PHOTO_MAX_COLORS: dict[DetailLevel, int] = {
    "low": 12,
    "medium": 24,
    "high": 40,
}

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
    quantized: bool


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


def apply_preprocess(
    png_bytes: bytes,
    *,
    preset: PresetName,
    detail: DetailLevel = "medium",
    max_colors: int | None = None,
    denoise: bool | None = None,
    flatten_transparency: bool = False,
) -> PreprocessResult:
    """Apply optional flatten / upscale / denoise / quantize pipeline.

    Runs for ``preset=photo`` and whenever ``max_colors`` is explicitly set.
    Otherwise returns the input bytes unchanged (still may flatten if asked).
    """
    effective_colors = resolve_max_colors(preset, detail, max_colors)
    do_denoise = resolve_denoise(preset, denoise)
    # Explicit max_colors from caller: max_colors is not None when user set it
    user_set_colors = max_colors is not None
    run_pipeline = preset == "photo" or user_set_colors or flatten_transparency

    with Image.open(io.BytesIO(png_bytes)) as img:
        img = img.convert("RGBA")
        width, height = img.size
        flattened = False
        upscaled = False
        quantized = False

        if flatten_transparency:
            background = Image.new("RGBA", img.size, (255, 255, 255, 255))
            background.alpha_composite(img)
            img = background.convert("RGBA")
            flattened = True

        if not run_pipeline and not flatten_transparency:
            out = io.BytesIO()
            img.save(out, format="PNG")
            return PreprocessResult(
                png_bytes=out.getvalue(),
                width=width,
                height=height,
                max_colors=None,
                denoise=False,
                flattened=False,
                upscaled=False,
                quantized=False,
            )

        # Photo-only 2× upscale when long edge is small
        if preset == "photo":
            long_edge = max(width, height)
            if long_edge < PHOTO_UPSCALE_MIN_EDGE:
                img = img.resize(
                    (width * 2, height * 2),
                    Image.Resampling.NEAREST,
                )
                width, height = img.size
                upscaled = True

        if do_denoise and (preset == "photo" or user_set_colors):
            # Light median filter; re-attach alpha
            rgb = img.convert("RGB").filter(ImageFilter.MedianFilter(size=3))
            alpha = img.getchannel("A")
            img = rgb.convert("RGBA")
            img.putalpha(alpha)

        if effective_colors is not None and (
            preset == "photo" or user_set_colors
        ):
            # Median-cut quantize without dithering for flatter regions
            rgba = img.convert("RGBA")
            # Quantize on RGB then restore alpha via nearest from original
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

        out = io.BytesIO()
        img.save(out, format="PNG")
        return PreprocessResult(
            png_bytes=out.getvalue(),
            width=width,
            height=height,
            max_colors=effective_colors if quantized else effective_colors,
            denoise=do_denoise if (preset == "photo" or user_set_colors) else False,
            flattened=flattened,
            upscaled=upscaled,
            quantized=quantized,
        )

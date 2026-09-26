"""Experimental double-vectorize pass.

Idea: vectorize once, re-rasterize the SVG, reinject lost detail from the
original raster, then vectorize again. May improve structure retention on
busy images — or just add cost. Kept isolated for easy A/B and removal.

Requires ``cairosvg`` (quality extra) for the intermediate SVG→raster step.

Overlay modes
-------------
- ``residual`` (default): ``pass1 + strength * (original - pass1)``
  Pulls back detail the first pass flattened.
- ``blend``: linear mix ``(1 - strength) * pass1 + strength * original``
- ``soft_mask``: residual weighted by local |original - pass1| so only
  high-error areas get detail back.
"""

from __future__ import annotations

import io
from dataclasses import dataclass
from typing import Any, Literal

import numpy as np
from PIL import Image

from app.services import optimizer, preprocess, presets, vectorizer

OverlayMode = Literal["residual", "blend", "soft_mask"]


@dataclass(frozen=True)
class DoublePassResult:
    svg: str
    pass1_svg: str
    hybrid_png: bytes
    width: int
    height: int
    overlay_mode: OverlayMode
    strength: float
    pass1_kwargs: dict[str, Any]
    pass2_kwargs: dict[str, Any]


def _rasterize_svg(svg: str, *, width: int, height: int) -> Image.Image:
    import cairosvg

    png_bytes = cairosvg.svg2png(
        bytestring=svg.encode("utf-8"),
        output_width=max(1, width),
        output_height=max(1, height),
        background_color="rgb(255,255,255)",
    )
    img = Image.open(io.BytesIO(png_bytes)).convert("RGBA")
    canvas = Image.new("RGBA", img.size, (255, 255, 255, 255))
    canvas.alpha_composite(img)
    return canvas.convert("RGB")


def _png_bytes(img: Image.Image) -> bytes:
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()


def overlay_detail(
    original: Image.Image,
    pass1_raster: Image.Image,
    *,
    mode: OverlayMode = "residual",
    strength: float = 0.45,
) -> Image.Image:
    """Rebuild a hybrid raster for the second vectorize pass."""
    if original.size != pass1_raster.size:
        pass1_raster = pass1_raster.resize(
            original.size, Image.Resampling.LANCZOS
        )
    strength = float(max(0.0, min(1.0, strength)))
    a = np.asarray(original.convert("RGB"), dtype=np.float32)
    b = np.asarray(pass1_raster.convert("RGB"), dtype=np.float32)

    if mode == "blend":
        out = (1.0 - strength) * b + strength * a
    elif mode == "soft_mask":
        # Emphasize detail where pass1 drifted most
        err = np.abs(a - b) / 255.0
        weight = np.clip(err.mean(axis=2, keepdims=True) * 3.0, 0.0, 1.0)
        out = b + (strength * weight) * (a - b)
    else:  # residual
        out = b + strength * (a - b)

    out = np.clip(out, 0, 255).astype(np.uint8)
    return Image.fromarray(out)


def _resolve_kwargs(
    *,
    preset: str,
    smooth_level: int,
    detail: str,
    max_colors: int | None,
    compression_level: int,
    pillow_enhance: bool,
    png_bytes: bytes,
) -> tuple[bytes, dict[str, Any], preprocess.PreprocessResult]:
    pre = preprocess.apply_preprocess(
        png_bytes,
        preset=preset,  # type: ignore[arg-type]
        detail=detail,  # type: ignore[arg-type]
        max_colors=max_colors,
        smooth_level=smooth_level,
        pillow_enhance=pillow_enhance,
    )
    resolved = presets.resolve(
        preset,  # type: ignore[arg-type]
        smooth_level,
        detail,  # type: ignore[arg-type]
        max_colors=max_colors,
        compression_level=compression_level,
    )
    kwargs = dict(resolved.kwargs)
    if pre.quantized and "max_colors" in kwargs:
        del kwargs["max_colors"]
    return pre.png_bytes, kwargs, pre


def double_vectorize(
    png_bytes: bytes,
    *,
    preset: str = "illustration",
    detail: str = "medium",
    smooth_level: int = 3,
    compression_level: int = 2,
    max_colors: int | None = None,
    pillow_enhance: bool = False,
    overlay_mode: OverlayMode = "residual",
    strength: float = 0.45,
    # Optional: first pass more aggressive (fewer colors / lower detail)
    pass1_detail: str | None = None,
    pass1_max_colors: int | None = None,
    pass2_detail: str | None = None,
    pass2_max_colors: int | None = None,
) -> DoublePassResult:
    """Run pass1 → overlay original detail → pass2. Returns final SVG + hybrid."""
    p1_detail = pass1_detail or detail
    p1_colors = pass1_max_colors if pass1_max_colors is not None else max_colors
    p2_detail = pass2_detail or detail
    p2_colors = pass2_max_colors if pass2_max_colors is not None else max_colors

    work_png, p1_kwargs, pre = _resolve_kwargs(
        preset=preset,
        smooth_level=smooth_level,
        detail=p1_detail,
        max_colors=p1_colors,
        compression_level=compression_level,
        pillow_enhance=pillow_enhance,
        png_bytes=png_bytes,
    )
    pass1_svg = vectorizer.vectorize(work_png, **p1_kwargs)
    pass1_svg, _ = optimizer.optimize_safe(
        pass1_svg, compression_level if compression_level >= 3 else 0
    )

    # Original for overlay = preprocessed working image (same space as pass1)
    original = Image.open(io.BytesIO(work_png)).convert("RGB")
    pass1_raster = _rasterize_svg(
        pass1_svg, width=pre.width, height=pre.height
    )
    hybrid = overlay_detail(
        original, pass1_raster, mode=overlay_mode, strength=strength
    )
    hybrid_png = _png_bytes(hybrid)

    # Second pass: usually skip pillow (already structured); use hybrid bytes
    work2, p2_kwargs, pre2 = _resolve_kwargs(
        preset=preset,
        smooth_level=smooth_level,
        detail=p2_detail,
        max_colors=p2_colors,
        compression_level=compression_level,
        pillow_enhance=False,
        png_bytes=hybrid_png,
    )
    pass2_svg = vectorizer.vectorize(work2, **p2_kwargs)
    pass2_svg, _ = optimizer.optimize_safe(
        pass2_svg, compression_level if compression_level >= 3 else 0
    )

    return DoublePassResult(
        svg=pass2_svg,
        pass1_svg=pass1_svg,
        hybrid_png=hybrid_png,
        width=pre2.width,
        height=pre2.height,
        overlay_mode=overlay_mode,
        strength=strength,
        pass1_kwargs=p1_kwargs,
        pass2_kwargs=p2_kwargs,
    )

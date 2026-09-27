"""Experimental photo background remove / blur via rembg.

Isolated spike (same spirit as ``preprocess_pillow`` / paint-by-numbers):

1. Keep ``rembg`` as an *optional* extra — API does not depend on it
2. Call from the A/B CLI (``python -m app.bg_experiment``) only
3. Delete this file + CLI + optional deps if the experiment does not help

Modes
-----
- ``none``: passthrough
- ``remove``: subject cutout on a solid fill (default white) so VTracer
  does not spend paths on busy backgrounds
- ``blur``: Gaussian-blur background while keeping the subject sharp —
  softens noise without a hard cutout edge
"""

from __future__ import annotations

import io
from dataclasses import dataclass
from typing import Any, Literal

from PIL import Image, ImageFilter

BgMode = Literal["none", "remove", "blur"]

DEFAULT_BLUR_RADIUS = 18.0
DEFAULT_FILL_RGBA = (255, 255, 255, 255)


@dataclass(frozen=True)
class BgPreprocessResult:
    png_bytes: bytes
    width: int
    height: int
    mode: BgMode
    mask_coverage: float  # fraction of pixels with alpha/mask > 127
    blur_radius: float | None


def _to_rgba(image: Image.Image | bytes) -> Image.Image:
    if isinstance(image, bytes):
        with Image.open(io.BytesIO(image)) as img:
            return img.convert("RGBA")
    return image.convert("RGBA")


def png_bytes(img: Image.Image) -> bytes:
    out = io.BytesIO()
    img.convert("RGBA").save(out, format="PNG")
    return out.getvalue()


def _png_bytes(img: Image.Image) -> bytes:
    """Backward-compatible alias."""
    return png_bytes(img)


def _mask_coverage(mask: Image.Image) -> float:
    """Fraction of pixels where the subject mask is mostly opaque."""
    gray = mask.convert("L")
    hist = gray.histogram()
    total = sum(hist) or 1
    subject = sum(hist[128:])
    return subject / total


def get_rembg_session(model_name: str = "bria-rmbg") -> Any:
    """Lazy-create a rembg session (downloads model on first use)."""
    try:
        from rembg import new_session
    except ImportError as exc:  # pragma: no cover - optional dep
        raise ImportError(
            "rembg is required for background preprocess. "
            "Install with: pip install 'rembg[cpu]'"
        ) from exc
    return new_session(model_name)


def subject_mask(
    image: Image.Image | bytes,
    *,
    session: Any | None = None,
) -> Image.Image:
    """Return an L-mode subject mask (255 = foreground)."""
    try:
        from rembg import remove
    except ImportError as exc:  # pragma: no cover
        raise ImportError(
            "rembg is required for background preprocess. "
            "Install with: pip install 'rembg[cpu]'"
        ) from exc

    rgba = _to_rgba(image)
    sess = session or get_rembg_session()
    mask = remove(rgba, session=sess, only_mask=True)
    if not isinstance(mask, Image.Image):
        mask = Image.open(io.BytesIO(mask))
    return mask.convert("L")


def remove_background(
    image: Image.Image | bytes,
    *,
    session: Any | None = None,
    fill_rgba: tuple[int, int, int, int] = DEFAULT_FILL_RGBA,
) -> tuple[Image.Image, float, Image.Image]:
    """Cut out the subject and composite onto ``fill_rgba`` (opaque).

    Returns ``(composited_rgba, mask_coverage, subject_mask_L)``.
    The mask is the pre-composite cutout alpha — do not use the opaque
    canvas alpha after fill (that is always 255).
    """
    try:
        from rembg import remove
    except ImportError as exc:  # pragma: no cover
        raise ImportError(
            "rembg is required for background preprocess. "
            "Install with: pip install 'rembg[cpu]'"
        ) from exc

    rgba = _to_rgba(image)
    sess = session or get_rembg_session()
    cutout = remove(rgba, session=sess)
    if not isinstance(cutout, Image.Image):
        cutout = Image.open(io.BytesIO(cutout))
    cutout = cutout.convert("RGBA")
    subject = cutout.getchannel("A").convert("L")

    canvas = Image.new("RGBA", cutout.size, fill_rgba)
    canvas.alpha_composite(cutout)
    coverage = _mask_coverage(subject)
    return canvas, coverage, subject


def blur_background(
    image: Image.Image | bytes,
    *,
    session: Any | None = None,
    blur_radius: float = DEFAULT_BLUR_RADIUS,
    mask: Image.Image | None = None,
) -> tuple[Image.Image, float]:
    """Keep subject sharp; Gaussian-blur everything else."""
    rgba = _to_rgba(image)
    subject = mask if mask is not None else subject_mask(rgba, session=session)
    subject = subject.resize(rgba.size, Image.Resampling.BILINEAR).convert("L")

    radius = max(0.0, float(blur_radius))
    if radius <= 0:
        return rgba, _mask_coverage(subject)

    blurred = rgba.filter(ImageFilter.GaussianBlur(radius=radius))
    # Soft composite: high mask → original subject, low → blurred bg
    out = Image.composite(rgba, blurred, subject)
    return out.convert("RGBA"), _mask_coverage(subject)


def apply_bg_preprocess(
    png_bytes: bytes,
    *,
    mode: BgMode = "none",
    session: Any | None = None,
    blur_radius: float = DEFAULT_BLUR_RADIUS,
    fill_rgba: tuple[int, int, int, int] = DEFAULT_FILL_RGBA,
) -> BgPreprocessResult:
    """Apply experimental background mode; returns PNG bytes + telemetry."""
    if mode == "none":
        with Image.open(io.BytesIO(png_bytes)) as img:
            rgba = img.convert("RGBA")
            w, h = rgba.size
            return BgPreprocessResult(
                png_bytes=_png_bytes(rgba),
                width=w,
                height=h,
                mode="none",
                mask_coverage=1.0,
                blur_radius=None,
            )

    if mode == "remove":
        out, coverage, _subject = remove_background(
            png_bytes, session=session, fill_rgba=fill_rgba
        )
        return BgPreprocessResult(
            png_bytes=_png_bytes(out),
            width=out.width,
            height=out.height,
            mode="remove",
            mask_coverage=coverage,
            blur_radius=None,
        )

    if mode == "blur":
        out, coverage = blur_background(
            png_bytes, session=session, blur_radius=blur_radius
        )
        return BgPreprocessResult(
            png_bytes=_png_bytes(out),
            width=out.width,
            height=out.height,
            mode="blur",
            mask_coverage=coverage,
            blur_radius=blur_radius,
        )

    raise ValueError(f"Unknown bg mode: {mode!r}")


__all__ = [
    "DEFAULT_BLUR_RADIUS",
    "DEFAULT_FILL_RGBA",
    "BgMode",
    "BgPreprocessResult",
    "apply_bg_preprocess",
    "blur_background",
    "get_rembg_session",
    "png_bytes",
    "remove_background",
    "subject_mask",
]

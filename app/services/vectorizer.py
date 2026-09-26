"""VTracer 0.6.x vectorization (stable API only)."""

from __future__ import annotations

from typing import Any

import vtracer

from app.core.errors import vectorization_failed
from app.core.logging import get_logger

logger = get_logger(__name__)


def vectorize(png_bytes: bytes, **kwargs: Any) -> str:
    """Convert RGBA PNG bytes to SVG via VTracer 0.6 ``convert_raw_image_to_svg``.

    Queue-ready: pure sync function, no FastAPI coupling. Callers that need
    async should wrap with ``asyncio.to_thread``.
    """
    if not png_bytes:
        raise vectorization_failed("No image data to vectorize")

    try:
        svg = vtracer.convert_raw_image_to_svg(
            png_bytes,
            "png",
            **kwargs,
        )
    except Exception as exc:  # noqa: BLE001 — surface as typed AppError
        logger.exception("VTracer convert_raw_image_to_svg failed")
        raise vectorization_failed(
            f"Vectorization failed: {exc}"
        ) from exc

    if not isinstance(svg, str) or "<svg" not in svg.lower():
        raise vectorization_failed("VTracer returned empty or invalid SVG")

    return svg


def get_vtracer_version() -> str:
    """Resolve installed VTracer version via importlib.metadata."""
    try:
        from importlib.metadata import version

        return version("vtracer")
    except Exception:  # noqa: BLE001
        return getattr(vtracer, "__version__", "0.6.15") or "0.6.15"

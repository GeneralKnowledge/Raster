"""VTracer 1.x vectorization via Config.convert_bytes."""

from __future__ import annotations

from typing import Any

import vtracer

from app.core.errors import vectorization_failed
from app.core.logging import get_logger

logger = get_logger(__name__)


def vectorize(png_bytes: bytes, **kwargs: Any) -> str:
    """Convert image bytes to SVG using VTracer 1.x ``Config.convert_bytes``.

    Queue-ready: pure sync function, no FastAPI coupling. Callers that need
    async should wrap with ``asyncio.to_thread``.
    """
    if not png_bytes:
        raise vectorization_failed("No image data to vectorize")

    try:
        cfg = vtracer.Config(**kwargs)
        svg = cfg.convert_bytes(png_bytes, format="png")
    except TypeError as exc:
        # Surface bad kwargs clearly during development
        logger.exception("Invalid VTracer Config kwargs: %s", kwargs)
        raise vectorization_failed(f"Invalid vectorizer settings: {exc}") from exc
    except Exception as exc:  # noqa: BLE001
        logger.exception("VTracer Config.convert_bytes failed")
        raise vectorization_failed(f"Vectorization failed: {exc}") from exc

    if not isinstance(svg, str) or "<svg" not in svg.lower():
        raise vectorization_failed("VTracer returned empty or invalid SVG")

    return svg


def get_vtracer_version() -> str:
    """Resolve installed VTracer version."""
    try:
        from importlib.metadata import version

        return version("vtracer")
    except Exception:  # noqa: BLE001
        return getattr(vtracer, "__version__", "1.0.0a4") or "1.0.0a4"

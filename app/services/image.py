"""Image validation, normalization, and safety resizing with Pillow."""

from __future__ import annotations

import io
import re
from dataclasses import dataclass

from PIL import Image, UnidentifiedImageError

from app.core.config import Settings, get_settings
from app.core.errors import (
    AppError,
    file_too_large,
    image_too_large,
    invalid_image,
    unsupported_format,
)

ALLOWED_FORMATS = frozenset({"PNG", "JPEG", "WEBP", "BMP"})
FORMAT_ALIASES = {
    "JPG": "JPEG",
}


@dataclass(frozen=True)
class NormalizedImage:
    """Validated image ready for preprocessing / vectorization."""

    png_bytes: bytes
    width: int
    height: int
    input_format: str
    original_size_bytes: int
    filename: str
    has_transparency: bool


def sanitize_filename(name: str | None, fallback: str = "image") -> str:
    """Return a safe basename without path traversal."""
    if not name:
        return fallback
    base = name.replace("\\", "/").split("/")[-1].strip()
    if not base or base in {".", ".."}:
        return fallback
    cleaned = re.sub(r"[^\w.\- +()]", "_", base, flags=re.UNICODE)
    cleaned = cleaned.strip(" .")
    if not cleaned:
        return fallback
    while cleaned.startswith("."):
        cleaned = cleaned[1:]
    return cleaned or fallback


def svg_output_filename(input_name: str | None) -> str:
    safe = sanitize_filename(input_name, "image")
    if "." in safe:
        stem = safe.rsplit(".", 1)[0] or "image"
    else:
        stem = safe
    stem = sanitize_filename(stem, "image")
    return f"{stem}.svg"


def validate_and_normalize(
    data: bytes,
    filename: str | None = None,
    *,
    settings: Settings | None = None,
) -> NormalizedImage:
    """Validate upload bytes and return RGBA PNG working buffer."""
    cfg = settings or get_settings()
    if not data:
        raise invalid_image("Empty file")
    if len(data) > cfg.max_file_size_bytes:
        raise file_too_large(
            f"File exceeds maximum size of {cfg.max_file_size_mb:g} MB"
        )

    Image.MAX_IMAGE_PIXELS = cfg.max_image_pixels

    try:
        with Image.open(io.BytesIO(data)) as img:
            img.load()
            fmt = (img.format or "").upper()
            fmt = FORMAT_ALIASES.get(fmt, fmt)
            if fmt not in ALLOWED_FORMATS:
                raise unsupported_format(
                    f"Unsupported image format: {fmt or 'unknown'}. "
                    "Allowed: PNG, JPEG, WebP, BMP"
                )

            width, height = img.size
            if width <= 0 or height <= 0:
                raise invalid_image("Image has invalid dimensions")

            pixels = width * height
            if pixels > cfg.max_image_pixels:
                raise image_too_large(
                    f"Image has {pixels} pixels; maximum is {cfg.max_image_pixels}"
                )

            # Only resize when exceeding max dimensions
            if width > cfg.max_image_width or height > cfg.max_image_height:
                scale = min(
                    cfg.max_image_width / width,
                    cfg.max_image_height / height,
                )
                new_w = max(1, int(width * scale))
                new_h = max(1, int(height * scale))
                img = img.resize((new_w, new_h), Image.Resampling.LANCZOS)
                width, height = img.size

            has_alpha = img.mode in ("RGBA", "LA", "PA") or (
                "transparency" in img.info
            )
            rgba = img.convert("RGBA")
            out = io.BytesIO()
            rgba.save(out, format="PNG")
            png_bytes = out.getvalue()
    except AppError:
        raise
    except UnidentifiedImageError as exc:
        raise invalid_image("Corrupt or unrecognizable image data") from exc
    except Image.DecompressionBombError as exc:
        raise image_too_large(
            f"Image exceeds pixel limit of {cfg.max_image_pixels}"
        ) from exc
    except OSError as exc:
        raise invalid_image(f"Failed to read image: {exc}") from exc

    return NormalizedImage(
        png_bytes=png_bytes,
        width=width,
        height=height,
        input_format=fmt.lower() if fmt != "JPEG" else "jpeg",
        original_size_bytes=len(data),
        filename=sanitize_filename(filename),
        has_transparency=bool(has_alpha),
    )

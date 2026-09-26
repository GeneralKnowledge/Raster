"""HTTP routes: /health, /version, /vectorize, /v1/vectorize."""

from __future__ import annotations

import asyncio
import time
from typing import Annotated, Any
from urllib.parse import quote

from fastapi import APIRouter, Depends, File, Form, Request, UploadFile
from fastapi.responses import JSONResponse, Response

from app.api.deps import JobSemaphore, get_settings, require_capacity, verify_api_key
from app.core.config import Settings
from app.core.errors import file_too_large, invalid_parameter
from app.core.logging import get_logger, request_id_var
from app.models import (
    COMPRESSION_LEVEL_DESC,
    DETAIL_DESC,
    PRESET_DESC,
    SMOOTH_LEVEL_DESC,
    DetailLevel,
    HealthResponse,
    PresetName,
    ResponseFormat,
    VersionResponse,
)
from app.services import optimizer, preprocess, presets, vectorizer
from app.services.image import svg_output_filename, validate_and_normalize

logger = get_logger(__name__)

router = APIRouter(dependencies=[Depends(verify_api_key)])


def _parse_bool(value: str | bool | None, field: str) -> bool | None:
    if value is None or value == "":
        return None
    if isinstance(value, bool):
        return value
    lowered = str(value).strip().lower()
    if lowered in {"1", "true", "yes", "on"}:
        return True
    if lowered in {"0", "false", "no", "off"}:
        return False
    raise invalid_parameter(f"Invalid boolean for {field}: {value}")


def _parse_optional_int(value: str | int | None, field: str) -> int | None:
    if value is None or value == "":
        return None
    try:
        return int(value)
    except (TypeError, ValueError) as exc:
        raise invalid_parameter(f"Invalid integer for {field}: {value}") from exc


def _content_disposition(filename: str) -> str:
    # Safe ASCII fallback + RFC 5987 filename*
    ascii_name = filename.encode("ascii", "ignore").decode("ascii") or "image.svg"
    ascii_name = ascii_name.replace('"', "")
    encoded = quote(filename)
    return f'attachment; filename="{ascii_name}"; filename*=UTF-8\'\'{encoded}'


def _common_headers(
    *,
    request_id: str,
    processing_ms: float,
    input_format: str,
    input_size: int,
    preset: str,
    smooth_level: int,
    compression_level: int,
    detail: str,
    denoise: bool,
    max_colors: int | None,
) -> dict[str, str]:
    headers = {
        "X-Request-Id": request_id,
        "X-Processing-Ms": f"{processing_ms:.2f}",
        "X-Input-Format": input_format,
        "X-Input-Size": str(input_size),
        "X-Preset": preset,
        "X-Smooth-Level": str(smooth_level),
        "X-Compression-Level": str(compression_level),
        "X-Detail": detail,
        "X-Denoise": "true" if denoise else "false",
    }
    if max_colors is not None:
        headers["X-Max-Colors"] = str(max_colors)
    return headers


async def _run_vectorize_pipeline(
    *,
    data: bytes,
    filename: str | None,
    preset: PresetName,
    smooth_level: int,
    compression_level: int,
    detail: DetailLevel,
    max_colors: int | None,
    denoise: bool | None,
    flatten_transparency: bool,
    settings: Settings,
) -> dict[str, Any]:
    started = time.perf_counter()

    normalized = await asyncio.to_thread(
        validate_and_normalize,
        data,
        filename,
        settings=settings,
    )

    pre = await asyncio.to_thread(
        preprocess.apply_preprocess,
        normalized.png_bytes,
        preset=preset,
        detail=detail,
        max_colors=max_colors,
        denoise=denoise,
        flatten_transparency=flatten_transparency,
    )

    resolved = presets.resolve(preset, smooth_level, detail)

    svg = await asyncio.to_thread(
        vectorizer.vectorize,
        pre.png_bytes,
        **resolved.kwargs,
    )

    optimized_svg, was_optimized = await asyncio.to_thread(
        optimizer.optimize_safe,
        svg,
        compression_level,
    )

    elapsed_ms = (time.perf_counter() - started) * 1000.0
    out_name = svg_output_filename(normalized.filename)

    return {
        "svg": optimized_svg,
        "filename": out_name,
        "input_format": normalized.input_format,
        "input_size": normalized.original_size_bytes,
        "width": pre.width,
        "height": pre.height,
        "original_filename": normalized.filename,
        "optimized": was_optimized,
        "processing_ms": elapsed_ms,
        "denoise": pre.denoise,
        "max_colors": pre.max_colors,
        "preset": preset,
        "smooth_level": smooth_level,
        "compression_level": compression_level,
        "detail": detail,
        "flatten_transparency": flatten_transparency,
    }


@router.get("/health", response_model=HealthResponse, tags=["meta"])
async def health() -> HealthResponse:
    return HealthResponse(status="ok", service="raster-to-svg")


@router.get("/version", response_model=VersionResponse, tags=["meta"])
async def version(
    settings: Annotated[Settings, Depends(get_settings)],
) -> VersionResponse:
    return VersionResponse(
        api_version=settings.app_version,
        vtracer_version=vectorizer.get_vtracer_version(),
    )


async def vectorize_endpoint(
    request: Request,
    settings: Annotated[Settings, Depends(get_settings)],
    sem: Annotated[JobSemaphore, Depends(require_capacity)],
    file: UploadFile = File(..., description="Raster image: PNG, JPEG, WebP, or BMP"),
    preset: str = Form("logo", description=PRESET_DESC),
    smooth_level: int = Form(3, ge=0, le=5, description=SMOOTH_LEVEL_DESC),
    compression_level: int = Form(2, ge=0, le=3, description=COMPRESSION_LEVEL_DESC),
    detail: str = Form("medium", description=DETAIL_DESC),
    max_colors: str | None = Form(
        None,
        description="Optional color limit 2–64. Photo defaults: 12/24/40 by detail.",
    ),
    denoise: str | None = Form(
        None,
        description="Denoise override (true/false). Default on for photo, off otherwise.",
    ),
    flatten_transparency: str = Form(
        "false",
        description="Flatten soft alpha onto white before vectorizing.",
    ),
    response_format: str = Form(
        "svg",
        description="Response body: svg (image/svg+xml) or json.",
    ),
    smooth: str | None = Form(
        None,
        description="Alias: false → smooth_level=0.",
    ),
    compress: str | None = Form(
        None,
        description="Alias: false → compression_level=0.",
    ),
) -> Response:
    try:
        return await _handle_vectorize(
            request=request,
            settings=settings,
            file=file,
            preset=preset,
            smooth_level=smooth_level,
            compression_level=compression_level,
            detail=detail,
            max_colors=max_colors,
            denoise=denoise,
            flatten_transparency=flatten_transparency,
            response_format=response_format,
            smooth=smooth,
            compress=compress,
        )
    finally:
        await sem.release()


async def _handle_vectorize(
    *,
    request: Request,
    settings: Settings,
    file: UploadFile,
    preset: str,
    smooth_level: int,
    compression_level: int,
    detail: str,
    max_colors: str | None,
    denoise: str | None,
    flatten_transparency: str,
    response_format: str,
    smooth: str | None,
    compress: str | None,
) -> Response:
    request_id = request_id_var.get("-")

    # Aliases
    smooth_alias = _parse_bool(smooth, "smooth")
    if smooth_alias is False:
        smooth_level = 0

    compress_alias = _parse_bool(compress, "compress")
    if compress_alias is False:
        compression_level = 0

    # Validate enums
    valid_presets = {"logo", "illustration", "photo", "lineart", "pixelart"}
    if preset not in valid_presets:
        raise invalid_parameter(
            f"Invalid preset '{preset}'. Expected one of: {', '.join(sorted(valid_presets))}"
        )
    valid_details = {"low", "medium", "high"}
    if detail not in valid_details:
        raise invalid_parameter(
            f"Invalid detail '{detail}'. Expected one of: {', '.join(sorted(valid_details))}"
        )
    valid_formats = {"svg", "json"}
    if response_format not in valid_formats:
        raise invalid_parameter(
            f"Invalid response_format '{response_format}'. Expected svg or json"
        )

    colors = _parse_optional_int(max_colors, "max_colors")
    if colors is not None and not (2 <= colors <= 64):
        raise invalid_parameter("max_colors must be between 2 and 64")

    denoise_flag = _parse_bool(denoise, "denoise")
    flatten = _parse_bool(flatten_transparency, "flatten_transparency")
    if flatten is None:
        flatten = False

    # Bounded read
    max_bytes = settings.max_file_size_bytes
    chunks: list[bytes] = []
    total = 0
    while True:
        chunk = await file.read(1024 * 1024)
        if not chunk:
            break
        total += len(chunk)
        if total > max_bytes:
            raise file_too_large(
                f"File exceeds maximum size of {settings.max_file_size_mb:g} MB"
            )
        chunks.append(chunk)
    data = b"".join(chunks)

    result = await _run_vectorize_pipeline(
        data=data,
        filename=file.filename,
        preset=preset,  # type: ignore[arg-type]
        smooth_level=smooth_level,
        compression_level=compression_level,
        detail=detail,  # type: ignore[arg-type]
        max_colors=colors,
        denoise=denoise_flag,
        flatten_transparency=flatten,
        settings=settings,
    )

    headers = _common_headers(
        request_id=request_id,
        processing_ms=result["processing_ms"],
        input_format=result["input_format"],
        input_size=result["input_size"],
        preset=result["preset"],
        smooth_level=result["smooth_level"],
        compression_level=result["compression_level"],
        detail=result["detail"],
        denoise=result["denoise"],
        max_colors=result["max_colors"],
    )
    headers["Content-Disposition"] = _content_disposition(result["filename"])

    if response_format == "json":
        body = {
            "success": True,
            "filename": result["filename"],
            "svg": result["svg"],
            "input": {
                "format": result["input_format"],
                "width": result["width"],
                "height": result["height"],
                "size_bytes": result["input_size"],
                "filename": result["original_filename"],
            },
            "output": {
                "format": "svg",
                "size_bytes": len(result["svg"].encode("utf-8")),
                "optimized": result["optimized"],
            },
            "settings": {
                "preset": result["preset"],
                "smooth_level": result["smooth_level"],
                "compression_level": result["compression_level"],
                "detail": result["detail"],
                "max_colors": result["max_colors"],
                "denoise": result["denoise"],
                "flatten_transparency": result["flatten_transparency"],
            },
            "meta": {
                "request_id": request_id,
                "processing_ms": round(result["processing_ms"], 2),
            },
        }
        return JSONResponse(content=body, headers=headers)

    return Response(
        content=result["svg"],
        media_type="image/svg+xml",
        headers=headers,
    )


# Register both paths
router.add_api_route(
    "/v1/vectorize",
    vectorize_endpoint,
    methods=["POST"],
    tags=["vectorize"],
    summary="Convert a raster image to SVG",
    response_class=Response,
)
router.add_api_route(
    "/vectorize",
    vectorize_endpoint,
    methods=["POST"],
    tags=["vectorize"],
    summary="Convert a raster image to SVG (legacy alias)",
    response_class=Response,
    include_in_schema=True,
)

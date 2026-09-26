"""Pydantic models for API requests and responses."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel

PresetName = Literal["logo", "illustration", "photo", "lineart", "pixelart"]
DetailLevel = Literal["low", "medium", "high"]
ResponseFormat = Literal["svg", "json"]


class HealthResponse(BaseModel):
    status: str = "ok"
    service: str = "raster-to-svg"


class VersionResponse(BaseModel):
    api_version: str
    vtracer_version: str


class ErrorResponse(BaseModel):
    error: str
    message: str
    request_id: str


class InputMeta(BaseModel):
    format: str
    width: int
    height: int
    size_bytes: int
    filename: str


class OutputMeta(BaseModel):
    format: str = "svg"
    size_bytes: int
    optimized: bool


class SettingsMeta(BaseModel):
    preset: PresetName
    smooth_level: int
    compression_level: int
    detail: DetailLevel
    max_colors: int | None = None
    denoise: bool
    flatten_transparency: bool


class MetaInfo(BaseModel):
    request_id: str
    processing_ms: float


class VectorizeJsonResponse(BaseModel):
    success: bool = True
    filename: str
    svg: str
    input: InputMeta
    output: OutputMeta
    settings: SettingsMeta
    meta: MetaInfo


class VectorizeFormDefaults:
    """Documented defaults for multipart form fields."""

    preset: PresetName = "logo"
    smooth_level: int = 3
    compression_level: int = 2
    detail: DetailLevel = "medium"
    response_format: ResponseFormat = "svg"
    flatten_transparency: bool = False


SMOOTH_LEVEL_DESC = (
    "Smoothing level 0–5. 0 = polygon / minimal smoothing; "
    "higher values produce smoother splines."
)
COMPRESSION_LEVEL_DESC = (
    "Compression: 0=off, 1–2=VTracer native optimize, "
    "3=native optimize + aggressive Scour minify."
)
DETAIL_DESC = "Detail overlay: low (fewer shapes), medium, high (more detail)."
PRESET_DESC = (
    "Vectorization preset: logo | illustration | photo | lineart | pixelart. "
    "Photo mode produces a stylized poster, not photographic fidelity."
)

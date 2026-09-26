"""Preset + smooth_level + detail → VTracer 0.6 kwargs."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from app.models import DetailLevel, PresetName

# VTracer sensible clamps (from package docs / .pyi)
FILTER_SPECKLE_RANGE = (0, 128)
COLOR_PRECISION_RANGE = (1, 8)
LAYER_DIFFERENCE_RANGE = (1, 64)
CORNER_THRESHOLD_RANGE = (0, 180)
LENGTH_THRESHOLD_RANGE = (3.5, 10.0)
SPLICE_THRESHOLD_RANGE = (0, 180)
PATH_PRECISION_RANGE = (0, 10)

# Single preset table
PRESETS: dict[PresetName, dict[str, Any]] = {
    "logo": {
        "colormode": "color",
        "hierarchical": "stacked",
        "filter_speckle": 8,
        "color_precision": 7,
        "layer_difference": 24,
    },
    "illustration": {
        "colormode": "color",
        "hierarchical": "stacked",
        "filter_speckle": 4,
        "color_precision": 6,
        "layer_difference": 16,
    },
    "photo": {
        "colormode": "color",
        "hierarchical": "stacked",
        "filter_speckle": 16,
        "color_precision": 5,
        "layer_difference": 28,
    },
    "lineart": {
        "colormode": "binary",
        "hierarchical": "stacked",
        "filter_speckle": 4,
        "color_precision": 6,
        "layer_difference": 16,
    },
    "pixelart": {
        "colormode": "color",
        "hierarchical": "cutout",
        "filter_speckle": 0,
        "color_precision": 8,
        "layer_difference": 8,
    },
}

SMOOTH_LEVELS: dict[int, dict[str, Any]] = {
    0: {
        "mode": "polygon",
        "corner_threshold": 60,
        "length_threshold": 4.0,
        "splice_threshold": 45,
        "path_precision": 8,
    },
    1: {
        "mode": "spline",
        "corner_threshold": 80,
        "length_threshold": 3.5,
        "splice_threshold": 30,
        "path_precision": 6,
    },
    2: {
        "mode": "spline",
        "corner_threshold": 70,
        "length_threshold": 3.8,
        "splice_threshold": 35,
        "path_precision": 5,
    },
    3: {
        "mode": "spline",
        "corner_threshold": 60,
        "length_threshold": 4.0,
        "splice_threshold": 45,
        "path_precision": 3,
    },
    4: {
        "mode": "spline",
        "corner_threshold": 50,
        "length_threshold": 5.0,
        "splice_threshold": 55,
        "path_precision": 2,
    },
    5: {
        "mode": "spline",
        "corner_threshold": 40,
        "length_threshold": 6.0,
        "splice_threshold": 60,
        "path_precision": 2,
    },
}

DETAIL_OVERLAYS: dict[DetailLevel, dict[str, int]] = {
    "low": {"filter_speckle": 8, "color_precision": -1, "layer_difference": 12},
    "medium": {"filter_speckle": 0, "color_precision": 0, "layer_difference": 0},
    "high": {"filter_speckle": -6, "color_precision": 1, "layer_difference": -8},
}


def _clamp(value: float | int, lo: float, hi: float) -> float | int:
    return type(value)(max(lo, min(hi, value)))


@dataclass(frozen=True)
class ResolvedPresets:
    kwargs: dict[str, Any]
    preset: PresetName
    smooth_level: int
    detail: DetailLevel


def resolve(
    preset: PresetName = "logo",
    smooth_level: int = 3,
    detail: DetailLevel = "medium",
) -> ResolvedPresets:
    """Merge preset, smooth_level, and detail into VTracer kwargs."""
    if preset not in PRESETS:
        raise ValueError(f"Unknown preset: {preset}")
    if smooth_level not in SMOOTH_LEVELS:
        raise ValueError(f"smooth_level must be 0–5, got {smooth_level}")
    if detail not in DETAIL_OVERLAYS:
        raise ValueError(f"Unknown detail: {detail}")

    base = dict(PRESETS[preset])
    smooth = dict(SMOOTH_LEVELS[smooth_level])
    overlay = DETAIL_OVERLAYS[detail]

    filter_speckle = int(
        _clamp(
            base["filter_speckle"] + overlay["filter_speckle"],
            *FILTER_SPECKLE_RANGE,
        )
    )
    color_precision = int(
        _clamp(
            base["color_precision"] + overlay["color_precision"],
            *COLOR_PRECISION_RANGE,
        )
    )
    layer_difference = int(
        _clamp(
            base["layer_difference"] + overlay["layer_difference"],
            *LAYER_DIFFERENCE_RANGE,
        )
    )

    mode = smooth["mode"]
    # Pixel art: force polygon when smooth_level <= 2
    if preset == "pixelart" and smooth_level <= 2:
        mode = "polygon"

    kwargs: dict[str, Any] = {
        "colormode": base["colormode"],
        "hierarchical": base["hierarchical"],
        "mode": mode,
        "filter_speckle": filter_speckle,
        "color_precision": color_precision,
        "layer_difference": layer_difference,
        "corner_threshold": int(
            _clamp(smooth["corner_threshold"], *CORNER_THRESHOLD_RANGE)
        ),
        "length_threshold": float(
            _clamp(smooth["length_threshold"], *LENGTH_THRESHOLD_RANGE)
        ),
        "splice_threshold": int(
            _clamp(smooth["splice_threshold"], *SPLICE_THRESHOLD_RANGE)
        ),
        "path_precision": int(
            _clamp(smooth["path_precision"], *PATH_PRECISION_RANGE)
        ),
    }

    return ResolvedPresets(
        kwargs=kwargs,
        preset=preset,
        smooth_level=smooth_level,
        detail=detail,
    )

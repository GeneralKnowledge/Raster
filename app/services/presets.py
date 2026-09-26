"""Preset + smooth_level + detail → VTracer 1.x Config kwargs.

Leans on native 1.x features (clustering, max_colors, simplify, optimize,
watershed) instead of heavy Pillow pre-posterization.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from app.models import DetailLevel, PresetName

FILTER_SPECKLE_RANGE = (0, 128)
COLOR_PRECISION_RANGE = (1, 8)
LAYER_DIFFERENCE_RANGE = (1, 64)
CORNER_THRESHOLD_RANGE = (0, 180)
LENGTH_THRESHOLD_RANGE = (3.5, 10.0)
SPLICE_THRESHOLD_RANGE = (0, 180)
PATH_PRECISION_RANGE = (0, 10)
WATERSHED_DETAIL_RANGE = (1, 512)

# Photo max_colors defaults (native Config.max_colors)
PHOTO_MAX_COLORS: dict[DetailLevel, int] = {
    "low": 12,
    "medium": 24,
    "high": 40,
}

# Watershed cut levels by detail (higher = more regions)
PHOTO_WATERSHED_DETAIL: dict[DetailLevel, int] = {
    "low": 96,
    "medium": 140,
    "high": 200,
}

# Base presets — 1.x clustering replaces colormode
PRESETS: dict[PresetName, dict[str, Any]] = {
    "logo": {
        "clustering": "color-cluster",
        "hierarchical": "stacked",
        "filter_speckle": 8,
        "color_precision": 7,
        "layer_difference": 24,
        "corner_threshold": 60,
    },
    "illustration": {
        "clustering": "color-cluster",
        "hierarchical": "stacked",
        "filter_speckle": 4,
        "color_precision": 6,
        "layer_difference": 16,
        "corner_threshold": 60,
    },
    # Watershed + cutout + photo()-style corner_threshold for smooth regions
    "photo": {
        "clustering": "watershed",
        "hierarchical": "cutout",
        "filter_speckle": 10,
        "color_precision": 8,
        "layer_difference": 48,
        "corner_threshold": 180,
    },
    "lineart": {
        "clustering": "bw",
        "hierarchical": "stacked",
        "filter_speckle": 4,
        "color_precision": 6,
        "layer_difference": 16,
        "corner_threshold": 60,
        "adaptive": True,
    },
    "pixelart": {
        "clustering": "color-cluster",
        "hierarchical": "cutout",
        "filter_speckle": 0,
        "color_precision": 8,
        "layer_difference": 8,
        "corner_threshold": 60,
    },
}

# smooth_level → curve mode + simplify (1.x Schneider re-fit) + spline knobs
SMOOTH_LEVELS: dict[int, dict[str, Any]] = {
    0: {
        "mode": "polygon",
        "length_threshold": 4.0,
        "splice_threshold": 45,
        "path_precision": 8,
        "max_iterations": 10,
        "simplify": None,
    },
    1: {
        "mode": "spline",
        "length_threshold": 3.5,
        "splice_threshold": 30,
        "path_precision": 6,
        "max_iterations": 10,
        "simplify": 0.5,
    },
    2: {
        "mode": "spline",
        "length_threshold": 3.8,
        "splice_threshold": 35,
        "path_precision": 5,
        "max_iterations": 10,
        "simplify": 0.8,
    },
    3: {
        "mode": "spline",
        "length_threshold": 4.5,
        "splice_threshold": 50,
        "path_precision": 3,
        "max_iterations": 12,
        "simplify": 1.2,
    },
    4: {
        "mode": "spline",
        "length_threshold": 6.0,
        "splice_threshold": 60,
        "path_precision": 2,
        "max_iterations": 16,
        "simplify": 1.8,
    },
    5: {
        "mode": "spline",
        "length_threshold": 8.0,
        "splice_threshold": 70,
        "path_precision": 2,
        "max_iterations": 20,
        "simplify": 2.5,
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
    max_colors: int | None
    optimize: int


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


def resolve(
    preset: PresetName = "logo",
    smooth_level: int = 3,
    detail: DetailLevel = "medium",
    *,
    max_colors: int | None = None,
    compression_level: int = 2,
) -> ResolvedPresets:
    """Merge public options into VTracer 1.x ``Config`` kwargs."""
    if preset not in PRESETS:
        raise ValueError(f"Unknown preset: {preset}")
    if smooth_level not in SMOOTH_LEVELS:
        raise ValueError(f"smooth_level must be 0–5, got {smooth_level}")
    if detail not in DETAIL_OVERLAYS:
        raise ValueError(f"Unknown detail: {detail}")

    base = dict(PRESETS[preset])
    smooth = dict(SMOOTH_LEVELS[smooth_level])
    overlay = DETAIL_OVERLAYS[detail]
    effective_colors = resolve_max_colors(preset, detail, max_colors)

    # Native optimize: 0–2 from compression_level (3 still uses optimize=2 + Scour)
    optimize = max(0, min(2, int(compression_level)))

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
    simplify = smooth["simplify"]
    if preset == "pixelart" and smooth_level <= 2:
        mode = "polygon"
        simplify = None

    # Photo keeps high corner_threshold from Config.photo(); others follow smooth
    if preset == "photo":
        corner = int(base["corner_threshold"])
    else:
        # Map smooth level to corner: higher smooth → lower corner threshold
        corner_by_level = {0: 60, 1: 80, 2: 70, 3: 55, 4: 40, 5: 30}
        corner = corner_by_level[smooth_level]

    kwargs: dict[str, Any] = {
        "clustering": base["clustering"],
        "hierarchical": base["hierarchical"],
        "mode": mode,
        "filter_speckle": filter_speckle,
        "color_precision": color_precision,
        "layer_difference": layer_difference,
        "corner_threshold": int(_clamp(corner, *CORNER_THRESHOLD_RANGE)),
        "length_threshold": float(
            _clamp(smooth["length_threshold"], *LENGTH_THRESHOLD_RANGE)
        ),
        "splice_threshold": int(
            _clamp(smooth["splice_threshold"], *SPLICE_THRESHOLD_RANGE)
        ),
        "path_precision": int(
            _clamp(smooth["path_precision"], *PATH_PRECISION_RANGE)
        ),
        "max_iterations": int(smooth.get("max_iterations", 10)),
        "optimize": optimize,
    }

    if simplify is not None:
        kwargs["simplify"] = float(simplify)

    if effective_colors is not None and preset != "lineart":
        kwargs["max_colors"] = effective_colors

    if preset == "photo":
        kwargs["watershed_detail"] = int(
            _clamp(PHOTO_WATERSHED_DETAIL[detail], *WATERSHED_DETAIL_RANGE)
        )

    if preset == "lineart":
        kwargs["adaptive"] = bool(base.get("adaptive", True))

    return ResolvedPresets(
        kwargs=kwargs,
        preset=preset,
        smooth_level=smooth_level,
        detail=detail,
        max_colors=effective_colors if preset != "lineart" else None,
        optimize=optimize,
    )

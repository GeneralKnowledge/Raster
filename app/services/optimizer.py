"""Scour-based SVG optimizer — vector-only, fail-soft."""

from __future__ import annotations

from scour import scour

from app.core.logging import get_logger

logger = get_logger(__name__)


def _options_for_level(level: int):  # returns optparse.Values from Scour
    """Build Scour options for compression level 0–3."""
    opts = scour.sanitizeOptions(None)
    opts.quiet = True
    opts.error_on_flowtext = False
    # Never embed/rasterize
    opts.embed_rasters = False

    if level <= 0:
        return opts

    # Level 1+: strip metadata / comments / whitespace
    opts.remove_metadata = True
    opts.remove_titles = True
    opts.remove_descriptions = True
    opts.remove_descriptive_elements = True
    opts.strip_comments = True
    opts.strip_xml_prolog = True
    opts.newlines = False
    opts.indent_type = "none"
    opts.strip_xml_space_attribute = True

    if level >= 2:
        # Numeric precision + structural cleanup
        opts.digits = 3
        opts.cdigits = 2
        opts.group_collapse = True
        opts.simple_colors = True
        opts.style_to_xml = True
        opts.enable_viewboxing = True
        opts.keep_editor_data = False

    if level >= 3:
        # More aggressive path/group minify
        opts.digits = 2
        opts.cdigits = 1
        opts.shorten_ids = True
        opts.strip_ids = False  # keep ids that may be referenced
        opts.group_create = True
        opts.remove_descriptive_elements = True

    return opts


def optimize_safe(svg: str, level: int = 2) -> tuple[str, bool]:
    """Optimize SVG with Scour.

    Returns ``(svg, optimized)``. On failure, logs and returns the original.
    Never rasterizes output.
    """
    if level <= 0 or not svg:
        return svg, False

    level = max(0, min(3, int(level)))
    try:
        opts = _options_for_level(level)
        result = scour.scourString(svg, opts)
        if not result or "<svg" not in result.lower():
            logger.warning("Scour returned empty/invalid SVG; using original")
            return svg, False
        return result, True
    except Exception:  # noqa: BLE001 — fail-soft
        logger.exception("SVG optimization failed; returning unoptimized SVG")
        return svg, False

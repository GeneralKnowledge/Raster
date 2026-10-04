"""Paint-by-numbers spike: quantize → regions → outline / steps / numbers.

Shares color reduction ideas with the vectorize pipeline but emits a projector-
friendly kit instead of a single filled SVG.

Public entry: ``generate_paint_by_numbers``.
"""

from __future__ import annotations

import json
from collections import Counter
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

import numpy as np
from PIL import Image

from app.services.vectorizer import vectorize
# Defaults tuned for projector: few colors, no dust-speck regions
DEFAULT_MAX_COLORS = 16
DEFAULT_MIN_REGION_AREA = 80
DEFAULT_MERGE_DISTANCE = 28.0


@dataclass(frozen=True)
class PaletteColor:
    id: int
    rgb: tuple[int, int, int]
    hex: str
    pixel_count: int
    region_count: int


@dataclass(frozen=True)
class Region:
    id: int
    color_id: int
    area: int
    centroid: tuple[float, float]  # x, y


@dataclass(frozen=True)
class PaintStep:
    step: int
    color_id: int
    hex: str
    rgb: tuple[int, int, int]
    region_ids: list[int]
    area: int
    fill_svg: str


@dataclass(frozen=True)
class PaintByNumbersResult:
    width: int
    height: int
    max_colors: int
    palette: list[PaletteColor]
    regions: list[Region]
    steps: list[PaintStep]
    outline_svg: str
    numbered_svg: str
    quantized_png: bytes
    manifest: dict[str, Any]


def _rgb_to_hex(rgb: tuple[int, int, int]) -> str:
    return f"#{rgb[0]:02x}{rgb[1]:02x}{rgb[2]:02x}"


def _color_distance(a: tuple[int, int, int], b: tuple[int, int, int]) -> float:
    return float(
        (a[0] - b[0]) ** 2 + (a[1] - b[1]) ** 2 + (a[2] - b[2]) ** 2
    ) ** 0.5


def quantize_image(
    img: Image.Image,
    *,
    max_colors: int,
    merge_distance: float,
) -> tuple[Image.Image, list[tuple[int, int, int]]]:
    """Median-cut quantize + optional near-color merge. Returns RGB + palette."""
    rgb = img.convert("RGB")
    quantized = rgb.quantize(
        colors=max_colors,
        method=Image.Quantize.MEDIANCUT,
        dither=Image.Dither.NONE,
    )
    palette_raw = quantized.getpalette()
    if palette_raw is None:
        raise ValueError("Quantize returned no palette")
    n = len(quantized.getcolors() or [])
    colors = [
        (palette_raw[i * 3], palette_raw[i * 3 + 1], palette_raw[i * 3 + 2])
        for i in range(n)
    ]
    out = quantized.convert("RGB")

    # Merge near-duplicates (same idea as preprocess_pillow.merge_palette_colors)
    if merge_distance > 0 and len(colors) > 1:
        counts = Counter(out.getdata())
        ordered = [c for c, _ in counts.most_common()]
        mapping: dict[tuple[int, int, int], tuple[int, int, int]] = {}
        reps: list[tuple[int, int, int]] = []
        for color in ordered:
            matched = next(
                (r for r in reps if _color_distance(color, r) <= merge_distance),
                None,
            )
            if matched is None:
                reps.append(color)
                mapping[color] = color
            else:
                mapping[color] = matched
        if len(reps) < len(ordered):
            pixels = [mapping[p] for p in out.getdata()]
            out = Image.new("RGB", out.size)
            out.putdata(pixels)
            colors = reps

    # Rebuild compact palette in frequency order
    counts = Counter(out.getdata())
    palette = [c for c, _ in counts.most_common()]
    return out, palette


def index_map(
    rgb_img: Image.Image,
    palette: list[tuple[int, int, int]],
) -> np.ndarray:
    """Map each pixel to palette index 0..K-1."""
    arr = np.asarray(rgb_img, dtype=np.uint8)
    h, w, _ = arr.shape
    flat = arr.reshape(-1, 3)
    index = np.zeros(flat.shape[0], dtype=np.int32)
    for i, color in enumerate(palette):
        mask = np.all(flat == np.array(color, dtype=np.uint8), axis=1)
        index[mask] = i
    return index.reshape(h, w)


def connected_components(
    color_index: np.ndarray,
    *,
    min_area: int,
) -> tuple[np.ndarray, list[Region]]:
    """4-connected components; tiny regions absorbed into a neighbor color."""
    try:
        from skimage.measure import label as sk_label
    except ImportError as exc:  # pragma: no cover
        raise ImportError(
            "paint-by-numbers requires scikit-image (pip install scikit-image)"
        ) from exc

    h, w = color_index.shape
    labels = np.full((h, w), -1, dtype=np.int32)
    regions: list[Region] = []
    next_id = 0
    working = color_index

    # First pass: find small components and absorb them
    for color_id in np.unique(working):
        mask = working == int(color_id)
        labeled = sk_label(mask, connectivity=1)
        for comp_id in range(1, int(labeled.max()) + 1):
            comp = labeled == comp_id
            area = int(comp.sum())
            if area >= min_area:
                continue
            # 4-neighbor ring around the component
            dilated = np.zeros_like(comp)
            dilated[1:, :] |= comp[:-1, :]
            dilated[:-1, :] |= comp[1:, :]
            dilated[:, 1:] |= comp[:, :-1]
            dilated[:, :-1] |= comp[:, 1:]
            dilated &= ~comp
            if not dilated.any():
                continue
            votes = Counter(int(v) for v in working[dilated])
            votes.pop(int(color_id), None)
            if not votes:
                continue
            new_color = votes.most_common(1)[0][0]
            working[comp] = new_color
    # Second pass: stable regions after absorb
    for color_id in np.unique(working):
        mask = working == int(color_id)
        labeled = sk_label(mask, connectivity=1)
        for comp_id in range(1, int(labeled.max()) + 1):
            comp = labeled == comp_id
            area = int(comp.sum())
            if area < min_area:
                continue
            ys, xs = np.nonzero(comp)
            labels[comp] = next_id
            regions.append(
                Region(
                    id=next_id,
                    color_id=int(color_id),
                    area=area,
                    centroid=(float(xs.mean()), float(ys.mean())),
                )
            )
            next_id += 1

    return labels, regions


def _png_bytes(img: Image.Image) -> bytes:
    import io

    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()


def _vectorize_layer(png: bytes, *, for_outline: bool = False) -> str:
    """Run VTracer on a single-layer PNG."""
    if for_outline:
        kwargs: dict[str, Any] = {
            "clustering": "bw",
            "hierarchical": "stacked",
            "mode": "polygon",
            "filter_speckle": 4,
            "color_precision": 6,
            "layer_difference": 16,
            "corner_threshold": 60,
            "length_threshold": 3.5,
            "splice_threshold": 45,
            "path_precision": 3,
            "adaptive": True,
            "optimize": 1,
        }
    else:
        kwargs = {
            "clustering": "color-cluster",
            "hierarchical": "cutout",
            "mode": "spline",
            "filter_speckle": 4,
            "color_precision": 6,
            "layer_difference": 16,
            "corner_threshold": 55,
            "length_threshold": 4.5,
            "splice_threshold": 50,
            "path_precision": 3,
            "simplify": 1.2,
            "max_colors": 8,
            "optimize": 1,
        }
    return vectorize(png, **kwargs)


def build_outline_png(
    color_index: np.ndarray,
) -> Image.Image:
    """Black edges on white where palette index differs from a neighbor."""
    h, w = color_index.shape
    edge = np.zeros((h, w), dtype=bool)
    edge[:, 1:] |= color_index[:, 1:] != color_index[:, :-1]
    edge[1:, :] |= color_index[1:, :] != color_index[:-1, :]
    # Thicken slightly for projector visibility
    thick = edge.copy()
    thick[:, 1:] |= edge[:, :-1]
    thick[1:, :] |= edge[:-1, :]
    arr = np.full((h, w, 3), 255, dtype=np.uint8)
    arr[thick] = (0, 0, 0)
    return Image.fromarray(arr)


def build_color_layer_png(
    rgb_img: Image.Image,
    color_index: np.ndarray,
    color_id: int,
    rgb: tuple[int, int, int],
) -> Image.Image:
    """White background with one palette color painted in."""
    h, w = color_index.shape
    out = np.full((h, w, 3), 255, dtype=np.uint8)
    mask = color_index == color_id
    out[mask] = rgb
    return Image.fromarray(out)


def build_numbered_svg(
    width: int,
    height: int,
    outline_svg: str,
    regions: list[Region],
    *,
    font_size: int | None = None,
) -> str:
    """Composite outline + number labels at region centroids."""
    size = font_size or max(8, min(width, height) // 45)
    # Extract inner content of outline svg if possible; else nest via image note
    labels = []
    for region in regions:
        x, y = region.centroid
        # color_id is 1-based for humans
        num = region.color_id + 1
        labels.append(
            f'<text x="{x:.1f}" y="{y:.1f}" text-anchor="middle" '
            f'dominant-baseline="central" font-family="sans-serif" '
            f'font-size="{size}" fill="#111" stroke="#fff" stroke-width="0.6">'
            f"{num}</text>"
        )
    label_group = "\n".join(labels)
    # Place outline paths inside a wrapper; strip xml decl from nested svg
    inner = outline_svg
    if "<svg" in inner:
        start = inner.find(">", inner.find("<svg")) + 1
        end = inner.rfind("</svg>")
        if start > 0 and end > start:
            inner = inner[start:end]
    return (
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" '
        f'viewBox="0 0 {width} {height}">\n'
        f'<rect width="100%" height="100%" fill="#fff"/>\n'
        f"{inner}\n"
        f"{label_group}\n"
        f"</svg>\n"
    )


def generate_paint_by_numbers(
    image_bytes: bytes,
    *,
    max_colors: int = DEFAULT_MAX_COLORS,
    min_region_area: int = DEFAULT_MIN_REGION_AREA,
    merge_distance: float = DEFAULT_MERGE_DISTANCE,
    max_edge: int | None = 1000,
) -> PaintByNumbersResult:
    """Build a projector-oriented paint-by-numbers kit from a raster image."""
    from io import BytesIO

    img = Image.open(BytesIO(image_bytes)).convert("RGB")
    if max_edge is not None:
        w, h = img.size
        long_edge = max(w, h)
        if long_edge > max_edge:
            scale = max_edge / long_edge
            img = img.resize(
                (max(1, int(w * scale)), max(1, int(h * scale))),
                Image.Resampling.LANCZOS,
            )

    quantized, palette = quantize_image(
        img,
        max_colors=max_colors,
        merge_distance=merge_distance,
    )
    color_index = index_map(quantized, palette)
    # Work on a copy for absorb mutations
    working_index = color_index.copy()
    _labels, regions = connected_components(
        working_index, min_area=min_region_area
    )
    # Rebuild palette counts after absorb
    flat = working_index.ravel()
    counts = Counter(int(v) for v in flat)
    # Remap to dense ids by frequency
    ordered_old = [cid for cid, _ in counts.most_common()]
    remap = {old: new for new, old in enumerate(ordered_old)}
    dense = np.vectorize(lambda v: remap[int(v)])(working_index)
    new_palette = [palette[old] for old in ordered_old]
    regions = [
        Region(
            id=r.id,
            color_id=remap[r.color_id],
            area=r.area,
            centroid=r.centroid,
        )
        for r in regions
        if r.color_id in remap
    ]
    # Recompute region counts per color
    region_counts: Counter[int] = Counter(r.color_id for r in regions)
    pixel_counts = Counter(int(v) for v in dense.ravel())

    palette_colors = [
        PaletteColor(
            id=i + 1,
            rgb=new_palette[i],
            hex=_rgb_to_hex(new_palette[i]),
            pixel_count=pixel_counts[i],
            region_count=region_counts[i],
        )
        for i in range(len(new_palette))
    ]

    width, height = quantized.size
    outline_png = build_outline_png(dense)
    outline_svg = _vectorize_layer(_png_bytes(outline_png), for_outline=True)

    # Steps: largest color areas first (good for projector coverage)
    steps: list[PaintStep] = []
    for step_i, pc in enumerate(
        sorted(palette_colors, key=lambda c: c.pixel_count, reverse=True),
        start=1,
    ):
        color_id0 = pc.id - 1
        layer = build_color_layer_png(quantized, dense, color_id0, pc.rgb)
        fill_svg = _vectorize_layer(_png_bytes(layer), for_outline=False)
        region_ids = [r.id for r in regions if r.color_id == color_id0]
        steps.append(
            PaintStep(
                step=step_i,
                color_id=pc.id,
                hex=pc.hex,
                rgb=pc.rgb,
                region_ids=region_ids,
                area=pc.pixel_count,
                fill_svg=fill_svg,
            )
        )

    numbered = build_numbered_svg(width, height, outline_svg, regions)

    # Rebuild quantized preview from dense map
    preview = np.zeros((height, width, 3), dtype=np.uint8)
    for i, rgb in enumerate(new_palette):
        preview[dense == i] = rgb
    preview_img = Image.fromarray(preview)

    manifest = {
        "width": width,
        "height": height,
        "max_colors_requested": max_colors,
        "colors": len(palette_colors),
        "regions": len(regions),
        "min_region_area": min_region_area,
        "palette": [asdict(c) for c in palette_colors],
        "steps": [
            {
                "step": s.step,
                "color_id": s.color_id,
                "hex": s.hex,
                "rgb": list(s.rgb),
                "region_ids": s.region_ids,
                "area": s.area,
                "fill_svg": f"steps/step_{s.step:02d}_color_{s.color_id}.svg",
            }
            for s in steps
        ],
        "files": {
            "outline_svg": "outline.svg",
            "numbered_svg": "numbered.svg",
            "quantized_png": "quantized.png",
            "manifest": "manifest.json",
        },
        "projector_hint": (
            "Project outline.svg (or numbered.svg) as the base. "
            "Advance through steps/*.svg — each shows one color to paint."
        ),
    }

    return PaintByNumbersResult(
        width=width,
        height=height,
        max_colors=len(palette_colors),
        palette=palette_colors,
        regions=regions,
        steps=steps,
        outline_svg=outline_svg,
        numbered_svg=numbered,
        quantized_png=_png_bytes(preview_img),
        manifest=manifest,
    )


def write_paint_by_numbers_kit(
    result: PaintByNumbersResult,
    out_dir: Path,
) -> Path:
    """Write outline, numbered, quantized preview, steps, and manifest."""
    out_dir.mkdir(parents=True, exist_ok=True)
    steps_dir = out_dir / "steps"
    steps_dir.mkdir(exist_ok=True)

    (out_dir / "outline.svg").write_text(result.outline_svg, encoding="utf-8")
    (out_dir / "numbered.svg").write_text(result.numbered_svg, encoding="utf-8")
    (out_dir / "quantized.png").write_bytes(result.quantized_png)
    (out_dir / "manifest.json").write_text(
        json.dumps(result.manifest, indent=2),
        encoding="utf-8",
    )
    for step in result.steps:
        name = f"step_{step.step:02d}_color_{step.color_id}.svg"
        (steps_dir / name).write_text(step.fill_svg, encoding="utf-8")

    # Simple HTML projector helper
    step_files = [
        f"steps/step_{s.step:02d}_color_{s.color_id}.svg" for s in result.steps
    ]
    legend = "".join(
        f'<div class="swatch"><span style="background:{c.hex}"></span>'
        f"{c.id} {c.hex}</div>"
        for c in result.palette
    )
    html = f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8"/>
<title>Paint by numbers — projector</title>
<style>
  html, body {{ margin:0; height:100%; background:#111; color:#eee;
    font-family: system-ui, sans-serif; }}
  #stage {{ position:fixed; inset:0; display:flex; align-items:center;
    justify-content:center; }}
  #stage object, #stage img {{ max-width:96vw; max-height:85vh;
    background:#fff; }}
  #hud {{ position:fixed; left:0; right:0; bottom:0; padding:12px 16px;
    background:rgba(0,0,0,.75); display:flex; gap:16px; align-items:center;
    flex-wrap:wrap; }}
  button {{ font-size:1rem; padding:.4rem .9rem; cursor:pointer; }}
  .swatch {{ display:flex; align-items:center; gap:6px; margin:2px 8px 2px 0; }}
  .swatch span {{ width:18px; height:18px; border:1px solid #666; display:inline-block; }}
  #legend {{ display:flex; flex-wrap:wrap; max-width:50vw; }}
</style>
</head>
<body>
  <div id="stage"><object id="frame" type="image/svg+xml" data="outline.svg"></object></div>
  <div id="hud">
    <button id="prev" type="button">Prev</button>
    <button id="next" type="button">Next</button>
    <strong id="label">Outline</strong>
    <div id="legend">{legend}</div>
  </div>
  <script>
    const slides = ["outline.svg", "numbered.svg", {json.dumps(step_files)[1:-1]}];
    const names = ["Outline", "Numbered",
      {", ".join(f'"Step {s.step}: color {s.color_id} ({s.hex})"' for s in result.steps)}];
    let i = 0;
    const frame = document.getElementById("frame");
    const label = document.getElementById("label");
    function show(n) {{
      i = (n + slides.length) % slides.length;
      frame.data = slides[i];
      label.textContent = names[i];
    }}
    document.getElementById("prev").onclick = () => show(i - 1);
    document.getElementById("next").onclick = () => show(i + 1);
    window.addEventListener("keydown", (e) => {{
      if (e.key === "ArrowRight" || e.key === " ") show(i + 1);
      if (e.key === "ArrowLeft") show(i - 1);
    }});
  </script>
</body>
</html>
"""
    (out_dir / "projector.html").write_text(html, encoding="utf-8")
    return out_dir

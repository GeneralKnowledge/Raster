# Raster to SVG

Production-ready REST API that converts raster images (PNG, JPEG, WebP, BMP) into editable SVG using **VTracer 1.x** (`vtracer==1.0.0a4`).

> **Note:** 1.x is currently published as an alpha (`1.0.0a4`). It is the recommended upgrade path for quality (watershed clustering, native `max_colors`, `simplify`, mosaic `cutout`, built-in `optimize`). Pin exact version.

Photo mode produces a **stylized poster / illustration**, not continuous-tone photographic fidelity.

## Install & run

```bash
python3 -m venv .venv
source .venv/bin/activate   # Windows: .venv\Scripts\activate
pip install -r requirements.txt

cp .env.example .env   # optional

uvicorn app.main:app --reload
```

Open docs: [http://localhost:8000/docs](http://localhost:8000/docs)

## Paint-by-numbers (spike)

Sibling feature for **projector step-by-step** painting — shared quantize/VTracer
engine, separate output kit (not bolted onto `/v1/vectorize`):

```bash
python -m app.paint_by_numbers examples/shape.jpg /tmp/pbn --max-colors 12
# open /tmp/pbn/projector.html  →  Outline → Numbered → per-color steps
```

See [`examples/paint_by_numbers/`](examples/paint_by_numbers/).

## What it does

1. Validates & normalizes the upload with Pillow (RGBA PNG working buffer)
2. Light preprocess only: optional flatten alpha, photo upscale, median denoise
3. Resolves preset + smooth/detail/compression into a VTracer **`Config`**
4. Calls `Config.convert_bytes(png_bytes, format="png")`
5. Optional Scour pass only at `compression_level=3` (levels 0–2 use native `optimize`)

CPU work runs in `asyncio.to_thread`. Concurrency capped by `MAX_CONCURRENT_JOBS` (default 2); overflow → `503 busy`.

## Why 1.x (vs 0.6)

| Capability | 0.6.x | 1.x (`1.0.0a4`) |
|------------|-------|------------------|
| API | `convert_raw_image_to_svg` kwargs | `Config` + `convert_bytes` |
| Clustering | color / binary only | `color-cluster`, `bw`, **`watershed`** |
| Cutout | hierarchical re-trace | true mosaic `cutout` |
| Color budget | DIY Pillow quantize | native **`max_colors`** / palette |
| Curve cleanup | spline knobs only | native **`simplify`** (Schneider re-fit) |
| SVG minify | Scour only | native **`optimize`** 0–2 (+ optional Scour) |
| Built-in presets | — | `Config.photo()`, `poster()`, `bw()` |

## Endpoints

| Method | Path | Description |
|--------|------|-------------|
| `GET` | `/health` | Liveness |
| `GET` | `/version` | API + VTracer versions |
| `POST` | `/v1/vectorize` | Convert image → SVG |
| `POST` | `/vectorize` | Legacy alias |

Also: `/docs`, `/redoc`, `/openapi.json`.

### Vectorize multipart fields

| Field | Default | Notes |
|-------|---------|-------|
| `file` | required | PNG, JPEG, WebP, BMP |
| `preset` | `logo` | `logo` \| `illustration` \| `photo` \| `lineart` \| `pixelart` |
| `smooth_level` | `3` | `0`–`5` → mode + **`simplify`** tolerance |
| `compression_level` | `2` | `0`–`2` = native optimize; `3` = optimize + Scour |
| `detail` | `medium` | affects speckles / watershed_detail / photo colors |
| `max_colors` | auto | passed to Config; photo defaults **16/36/48** by detail |
| `denoise` | auto | light median; default on for photo |
| `flatten_transparency` | `false` | flatten soft alpha onto white |
| `pillow_enhance` | auto | on for `photo` (quantize/merge); override true/false |
| `response_format` | `svg` | `svg` \| `json` |
| `smooth` / `compress` | — | aliases to force level 0 |

### curl

```bash
curl -sS -X POST "http://localhost:8000/v1/vectorize" \
  -F "file=@examples/logo.png" \
  -F "preset=logo" \
  -F "smooth_level=4" \
  -o out.svg

curl -sS -X POST "http://localhost:8000/v1/vectorize" \
  -F "file=@examples/photo_sample.png" \
  -F "preset=photo" \
  -F "detail=medium" \
  -F "response_format=json" | jq '.meta, .settings'
```

## Presets (1.x)

| Preset | clustering | hierarchical | Notes |
|--------|------------|--------------|-------|
| `logo` | color-cluster | stacked | Clean flats + simplify |
| `illustration` | color-cluster | stacked | Balanced; prefer for detailed photos/ads when you want structure |
| `photo` | **watershed** | **cutout** | Stylized poster look; Pillow enhance on by default |
| `lineart` | **bw** | stacked | Adaptive threshold; use only for true B&W line work |
| `pixelart` | color-cluster | cutout | Polygon at low smooth |

### Smoothing

`smooth_level` drives spline/polygon mode and VTracer **`simplify`** (px tolerance). Higher = fewer cubics / rounder curves.

### Compression

| Level | Behavior |
|-------|----------|
| 0 | `optimize=0`, no Scour |
| 1 | `optimize=1` |
| 2 | `optimize=2` (default) |
| 3 | `optimize=2` + aggressive Scour (fail-soft) |

## Pillow enhance (photo-default)

Pillow enhance **auto-enables for `photo`** (median-cut quantize + color merge;
optional soften at `smooth_level` ≥ 4). Other presets stay native VTracer unless
you override. Non-photo A/B showed ~0 SSIM gain from the old fringe/soften path.

```bash
# env: auto | always | never  (aliases: true→always, false→never)
PILLOW_ENHANCE=auto

# per request overrides
curl -F "file=@examples/photo_sample.png" -F "preset=photo" \
  -F "pillow_enhance=false" http://localhost:8000/v1/vectorize -o native.svg

# CLI
python -m app.cli examples/photo_sample.png /tmp/auto.svg --preset photo
python -m app.cli examples/photo_sample.png /tmp/off.svg --preset photo --no-pillow-enhance
python -m app.benchmark examples/ --preset photo --no-pillow-enhance
```

When Pillow quantize runs, VTracer `max_colors` is skipped for that request to
avoid double posterizing. Response header: `X-Pillow-Enhance`.

### Removing Pillow enhance if unwanted

1. Set `PILLOW_ENHANCE=never` / always send `pillow_enhance=false`
2. Delete `app/services/preprocess_pillow.py`
3. Remove the `pillow_enhance` branch/import in `preprocess.py`
4. Grep for `pillow_enhance` / `PILLOW_ENHANCE` and drop form/CLI/env/docs

## Strengths & limits

**Strengths:** logos, icons, flat art, line art, pixel art, stylized photos (watershed).  
**Limits:** continuous-tone photography, antialiased text, soft gradients, soft alpha. Alpha is still a VTracer caveat — use `flatten_transparency=true` when needed.

## Config

See `.env.example` (`MAX_FILE_SIZE_MB`, `MAX_CONCURRENT_JOBS`, optional `API_KEY`, etc.).

## CLI & benchmark

```bash
python -m app.cli examples/logo.png /tmp/out.svg --preset logo --smooth-level 4
python -m app.cli examples/photo_sample.png /tmp/photo.svg --preset photo --detail medium --max-colors 24
python -m app.benchmark examples/ --preset photo --detail low
```

## Testing

```bash
pytest
```

### Similarity / quality (eval only)

Irony accepted: to score resemblance we rasterize the SVG **only in tests/eval**,
never in the production optimizer.

Metrics: **SSIM** (higher better), **MAE** (lower better), **PSNR**.

```bash
# automated floors by preset
pytest tests/test_similarity.py -s

# human-readable report + side-by-side PNGs + SVGs
python -m app.similarity examples/logo.png --preset logo --out-dir examples/vectorized
python -m app.similarity examples/photo_sample.png --preset photo --ab --out-dir examples/vectorized
```

Committed samples live in [`examples/vectorized/`](examples/vectorized/) (open the `.svg` files directly).

Writes paired files per run:
- `name__preset__pillow-off__ssim-0.966.png` — Source | SVG re-raster | |diff|×4
- `name__preset__pillow-off__ssim-0.966.svg` — editable vector output

Preset SSIM floors (vs preprocessed source): logo 0.82, illustration 0.75,
pixelart 0.70, lineart 0.55, photo 0.35 (stylized on purpose).

## Strengths & limits

`1.0.0a4` is a pre-release. APIs may change before a stable 1.0.0. This project pins the exact wheel and prefers the real installed API over assumptions.

## Future

Gateway → this service | other image APIs. Queue can wrap sync `vectorizer.vectorize()` unchanged.

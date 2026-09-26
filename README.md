# Raster to SVG

Production-ready REST API that converts raster images (PNG, JPEG, WebP, BMP) into editable SVG using **stable VTracer 0.6.x only** (`vtracer==0.6.15`).

Photo mode produces a **stylized poster / illustration**, not continuous-tone photographic fidelity.

## Install & run

```bash
python3 -m venv .venv
source .venv/bin/activate   # Windows: .venv\Scripts\activate
pip install -r requirements.txt

# optional: copy env defaults
cp .env.example .env

uvicorn app.main:app --reload
```

Open interactive docs: [http://localhost:8000/docs](http://localhost:8000/docs)

## What it does

1. Validates & normalizes the upload with Pillow (RGBA PNG working buffer)
2. Optional preprocess: flatten alpha, photo upscale, denoise, color quantize
3. Resolves a simple preset + smooth/detail overlay into VTracer kwargs
4. Calls `vtracer.convert_raw_image_to_svg(png_bytes, "png", **kwargs)`
5. Optionally compresses SVG with Scour (vector-only; fail-soft)

CPU work runs in `asyncio.to_thread`. Concurrent jobs are limited by `MAX_CONCURRENT_JOBS` (default 2); overflow returns `503 busy`.

## Endpoints

| Method | Path | Description |
|--------|------|-------------|
| `GET` | `/health` | Liveness |
| `GET` | `/version` | API + VTracer versions |
| `POST` | `/v1/vectorize` | Convert image → SVG |
| `POST` | `/vectorize` | Legacy alias |

Also: `/docs`, `/redoc`, `/openapi.json`.

### `GET /health`

```json
{ "status": "ok", "service": "raster-to-svg" }
```

### `GET /version`

```json
{ "api_version": "0.1.0", "vtracer_version": "0.6.15" }
```

### `POST /v1/vectorize`

Multipart form fields:

| Field | Default | Notes |
|-------|---------|-------|
| `file` | required | PNG, JPEG, WebP, BMP |
| `preset` | `logo` | `logo` \| `illustration` \| `photo` \| `lineart` \| `pixelart` |
| `smooth_level` | `3` | `0`–`5` (`0` = polygon / minimal) |
| `compression_level` | `2` | `0`–`3` (Scour) |
| `detail` | `medium` | `low` \| `medium` \| `high` |
| `max_colors` | auto | `2`–`64`; photo defaults 12/24/40 by detail |
| `denoise` | auto | default **on** for `photo` |
| `flatten_transparency` | `false` | flatten soft alpha onto white |
| `response_format` | `svg` | `svg` \| `json` |
| `smooth` | — | alias: `false` → `smooth_level=0` |
| `compress` | — | alias: `false` → `compression_level=0` |

**SVG mode:** `Content-Type: image/svg+xml`  
**JSON mode:** includes `success`, `filename`, `svg` (raw string), `input`, `output`, `settings`, `meta.request_id`, `meta.processing_ms`.

Common headers: `X-Request-Id`, `X-Processing-Ms`, `X-Input-Format`, `X-Input-Size`, `X-Preset`, `X-Smooth-Level`, `X-Compression-Level`, `X-Detail`, `X-Denoise`, `X-Max-Colors`.

### curl examples

```bash
# SVG response
curl -sS -X POST "http://localhost:8000/v1/vectorize" \
  -F "file=@examples/logo.png" \
  -F "preset=logo" \
  -F "smooth_level=3" \
  -o out.svg

# JSON response + photo preset
curl -sS -X POST "http://localhost:8000/v1/vectorize" \
  -F "file=@examples/photo_sample.png" \
  -F "preset=photo" \
  -F "detail=medium" \
  -F "max_colors=24" \
  -F "response_format=json" | jq '.meta, .settings'
```

## Presets

| Preset | Best for | Notes |
|--------|----------|-------|
| `logo` | Logos, icons, flat brand marks | Clean flats |
| `illustration` | Flat / semi-flat art | Balanced |
| `photo` | Stylized photos | Poster look, not photo fidelity |
| `lineart` | Sketches, B/W line drawings | Binary mode, fast |
| `pixelart` | Pixel / retro art | Cutout hierarchy; polygon at low smooth |

### Smoothing (`smooth_level`)

| Level | Mode | Feel |
|-------|------|------|
| 0 | polygon | Minimal / angular |
| 1–2 | spline | Mild |
| 3 | spline | Default balance |
| 4–5 | spline | Softest curves |

For `pixelart`, `mode=polygon` is forced when `smooth_level <= 2`.

### Compression (`compression_level`)

| Level | Behavior |
|-------|----------|
| 0 | Passthrough |
| 1 | Strip metadata / comments / whitespace |
| 2 | + numeric precision + structural cleanup (default) |
| 3 | More aggressive path/group minify |

Scour failures are fail-soft: the original SVG is returned. Output is **never rasterized**.

## Photo mode honesty

`preset=photo` (and any request with explicit `max_colors`) runs a preprocess inspired by Vectorizer.io / Vector Magic **controls** (not their tracers):

1. Optional flatten alpha → white
2. 2× upscale if long edge &lt; 800px (photo only)
3. Light median denoise (default on for photo)
4. Pillow median-cut quantize (photo defaults: low=12, medium=24, high=40; no dither)
5. VTracer color stacked tracing

Expect a **posterized / illustrated** look. Soft gradients, photographic detail, and soft alpha will not survive intact.

## Strengths & limits

**Strengths:** logos, icons, flat art, line art, pixel art, stylized photos.  
**Limits:** photographs, antialiased text, soft gradients, soft alpha / feathered edges.

## Configuration

See `.env.example`:

```env
APP_NAME=raster-to-svg
APP_VERSION=0.1.0
MAX_FILE_SIZE_MB=20
MAX_IMAGE_WIDTH=10000
MAX_IMAGE_HEIGHT=10000
MAX_IMAGE_PIXELS=50000000
MAX_CONCURRENT_JOBS=2
API_KEY_REQUIRED=false
API_KEY=
ALLOW_ORIGINS=*
LOG_LEVEL=INFO
```

When `API_KEY_REQUIRED=true`, send `Authorization: Bearer <key>` or `X-API-Key: <key>`.

## CLI & benchmark

```bash
python -m app.cli examples/logo.png /tmp/out.svg --preset logo --detail medium
python -m app.cli examples/photo_sample.png /tmp/photo.svg --preset photo --detail medium --max-colors 24

python -m app.benchmark examples/ --preset photo --detail low
```

## Testing

```bash
pytest
```

## Performance notes

- Default concurrency is intentionally low (`MAX_CONCURRENT_JOBS=2`) for CPU-bound tracing.
- Large photos with high detail / color counts are slower and produce larger SVGs.
- Prefer `lineart` / binary for B/W scans; prefer `logo` for flat graphics.

## Future architecture (not implemented)

This service is designed to sit behind a gateway later:

```text
gateway → raster-to-svg (this) | image-* | data-*
```

Do not expand this repo into empty sibling APIs until needed. Queueing can wrap the existing sync `vectorizer.vectorize()` without changing its signature.

## VTracer 0.6 notes

- Only `convert_raw_image_to_svg` is used (in-memory).
- Package version is resolved via `importlib.metadata` (`__version__` is absent on 0.6.15).
- SVG comments may still say `VTracer 0.6.12` even when the wheel is `0.6.15`.
- `length_threshold` must stay in `[3.5, 10]` per the binding docs.
- Soft transparency handling is limited; use `flatten_transparency=true` when alpha is decorative.

## License

Use freely in your own projects. VTracer and Scour retain their respective licenses.

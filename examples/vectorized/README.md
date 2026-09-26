# Sample vectorized outputs

Generated with:

```bash
python -m app.similarity examples/logo.png --preset logo --out-dir examples/vectorized
python -m app.similarity examples/photo_sample.png --preset photo --ab --out-dir examples/vectorized
python -m app.similarity examples/pixel.png --preset pixelart --out-dir examples/vectorized
python -m app.similarity examples/shape.jpg --preset illustration --out-dir examples/vectorized
```

Open the `.svg` files in a browser, Inkscape, or Illustrator.  
Paired `.png` strips are **Source | SVG re-raster | |diff|×4**.

| File stem | Notes |
|-----------|-------|
| `logo__logo__pillow-off__*` | logo preset |
| `photo_sample__photo__pillow-off__*` | photo, native VTracer 1.x |
| `photo_sample__photo__pillow-on__*` | photo + Pillow enhance |
| `pixel__pixelart__pillow-off__*` | pixelart preset |
| `shape__illustration__pillow-off__*` | illustration preset |

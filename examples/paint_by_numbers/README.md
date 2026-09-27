# Paint-by-numbers spike

Sibling feature to `/v1/vectorize`: same repo, shared quantize + VTracer outlining,
different product surface for **projector step-by-step** painting.

## Generate a kit

```bash
python -m app.paint_by_numbers path/to/image.jpg examples/paint_by_numbers/my_kit \
  --max-colors 12 --min-region-area 100
```

## Output layout

| File | Role |
|------|------|
| `quantized.png` | Flat-color preview (what you’ll paint toward) |
| `outline.svg` | Region edges — project as the base plate |
| `numbered.svg` | Outline + color numbers at centroids |
| `steps/step_XX_color_Y.svg` | One color’s fills — advance these on the projector |
| `manifest.json` | Palette, regions, step index |
| `projector.html` | Local step viewer (←/→ / Next) |

## Samples

- [`landscape/`](./landscape/) — stylized landscape, 12-color request
- [`mushroom_cloud/`](./mushroom_cloud/) — poster-like explosion (good PBN subject)

## Design notes

- Integrated **engine** (quantize / regions / VTracer), separate **API surface** (CLI for now; `/v1/paint-by-numbers` later).
- Defaults favor projectable cells (few colors, min region area) over photo fidelity.

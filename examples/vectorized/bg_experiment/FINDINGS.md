# Background remove / blur experiment

Isolated rembg preprocess A/B (not wired into `/v1/vectorize`).

SSIM is measured against the **post-preprocess** image fed to VTracer
(fair vectorization fidelity), not the raw camera original.

| Sample | Preset | Detail | Mode | SSIM | MAE | Paths | SVG | Mask | bg ms | vec ms |
|--------|--------|--------|------|------|-----|-------|-----|------|-------|--------|
| `portrait_a` | photo | medium | `none` | 0.838 | 0.016 | 95 | 136 KB | 1.00 | 38 | 258 |
| `portrait_a` | photo | medium | `remove` | 0.874 | 0.014 | 93 | 124 KB | 0.41 | 12622 | 301 |
| `portrait_a` | photo | medium | `blur` | 0.824 | 0.018 | 93 | 143 KB | 0.41 | 58 | 288 |
| `portrait_a` | illustration | high | `none` | 0.934 | 0.013 | 10815 | 650 KB | 1.00 | 41 | 1623 |
| `portrait_a` | illustration | high | `remove` | 0.946 | 0.012 | 10003 | 599 KB | 0.41 | 35 | 1442 |
| `portrait_a` | illustration | high | `blur` | 0.560 | 0.092 | 9718 | 589 KB | 0.41 | 56 | 1306 |
| `portrait_b` | photo | medium | `none` | 0.840 | 0.019 | 102 | 125 KB | 1.00 | 37 | 259 |
| `portrait_b` | photo | medium | `remove` | 0.894 | 0.015 | 87 | 106 KB | 0.37 | 10566 | 235 |
| `portrait_b` | photo | medium | `blur` | 0.853 | 0.014 | 103 | 118 KB | 0.37 | 48 | 237 |
| `portrait_b` | illustration | high | `none` | 0.936 | 0.017 | 13003 | 755 KB | 1.00 | 37 | 1665 |
| `portrait_b` | illustration | high | `remove` | 0.951 | 0.012 | 11172 | 638 KB | 0.37 | 29 | 1359 |
| `portrait_b` | illustration | high | `blur` | 0.533 | 0.122 | 10988 | 640 KB | 0.37 | 52 | 1387 |

## Verdict

**Background remove is worth keeping as an optional photo preprocess.**
Blur is not.

| Mode | Photo / medium | Illustration / high |
|------|----------------|---------------------|
| **remove** | +0.036 / +0.054 SSIM, ~9–15% smaller SVG | +0.012 / +0.015 SSIM, ~8–15% smaller, fewer paths |
| **blur** | mixed (−0.014 / +0.013 SSIM) | collapses (~0.55 SSIM) — soft grads vectorize poorly |

Remove frees path budget from busy backgrounds so VTracer spends it on the
subject. Blur replaces the bg with soft gradients that watershed /
color-cluster then shred into noisy paths.

Cost: rembg inference ~10–13 s/image on CPU (model download on first use).
Not enabled in the API yet — opt-in CLI only.

## How to read this

- **`none`**: current pipeline (Pillow enhance auto for photo).
- **`remove`**: rembg cutout on white — subject-only vectorization.
- **`blur`**: rembg mask + Gaussian blur on background.

Open `*__ab.jpg` strips (preprocess | SVG re-raster | |diff|) and
`*__bg.png` for the rembg stage alone.

```bash
pip install 'rembg[cpu]'
python -m app.bg_experiment path/to/portrait.jpg --out-dir /tmp/bg
```

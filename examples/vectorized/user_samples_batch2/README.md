# User samples batch 2

Stylized art / UI screenshots, run with tuned photo defaults (PR #5).

## Recommended (practical file size)

| Sample | Preset | Detail | SSIM | Notes |
|--------|--------|--------|------|-------|
| `landscape` | illustration | medium | 0.812 | Painted landscape — flat color blocks |
| `ig_reel` | illustration | medium | 0.820 | Instagram UI + B&W photo |
| `abstract_figure` | illustration | medium | 0.779 | Fluid abstract figure |
| `mushroom_cloud` | **photo** (auto Pillow) | medium | **0.858** | Best practical; tiny SVG |
| `lich_king` | illustration | medium | 0.792 | Ornate dark-fantasy portrait |

## High detail (`high_detail_previews/`)

`illustration` + `detail=high` pushes SSIM toward ~0.88–0.91 but can explode path count
(lich ~14 MB SVG). Preview strips are saved; only modest high SVGs are included.

| Sample | High SSIM | vs medium |
|--------|-----------|-----------|
| landscape | 0.897 | +0.085 |
| ig_reel | 0.912 | +0.092 |
| abstract_figure | 0.880 | +0.101 |
| mushroom_cloud | 0.893 | +0.035 vs photo |
| lich_king | 0.905 | +0.113 |

Open `.jpg` strips as **Source | SVG re-raster | |diff|×4**.

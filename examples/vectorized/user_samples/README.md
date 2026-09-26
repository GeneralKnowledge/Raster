# User sample vectorizations

Side-by-side strips (`Source | SVG re-raster | |diff|×4`) and matching SVGs from
real-world test images (downscaled to max edge 1000px for runtime).

| Sample | Preset | SSIM | MAE | Notes |
|--------|--------|------|-----|-------|
| `beard_photo` | photo + Pillow | 0.385 | 0.076 | Portrait; stylized / posterized |
| `silhouette` | illustration | 0.828 | 0.024 | High-contrast silhouette — strong |
| `chat_ui` | illustration | 0.969 | 0.007 | Flat UI — best of set |
| `yt_comment` | illustration | 0.949 | 0.016 | Looks close; text is paths not fonts |
| `vanta_ad` | illustration | 0.680 | 0.045 | Photo + neon + fine type |
| `orloj_clock` | illustration | 0.715 | 0.047 | Dial readable; stonework blobbed |

Open the `.svg` files directly, or the `.png` comparison strips in GitHub’s image viewer.

# Background remove / blur demos

Portrait A/B from the rembg experiment (`python -m app.bg_experiment`).

See [FINDINGS.md](FINDINGS.md) for the full table and verdict.

**Summary:** `remove` improves SSIM and shrinks SVG on both photo and
illustration/high; `blur` does not help (hurts illustration badly).

File naming: `{sample}__{preset}__{detail}__bg-{mode}__{ab|bg}.{ext}`

# Double-vectorize experiment

Hypothesis: vectorize → re-raster → reinject lost detail from the original →
vectorize again may recover structure a single pass misses.

```bash
# Naive (usually worse on illustrations)
python -m app.double_pass image.jpg --preset illustration --mode residual --strength 0.5

# Hierarchical (helps photos): coarse pass1, then medium pass2
python -m app.double_pass image.jpg --preset photo --mode residual --strength 0.5 \
  --pass1-detail low --out-dir artifacts/double_pass
```

## Findings (A/B vs single pass)

| Content | Config | ΔSSIM | Verdict |
|---------|--------|-------|---------|
| Illustration / detailed art | same settings + residual/blend/soft_mask | **−0.01 to −0.04** | Hurts — don't use |
| Photo / poster | same settings + residual | ~0 | Neutral, ~2× cost |
| Photo / poster | **`pass1-detail=low` → medium + residual ~0.5** | **+0.02 to +0.05** | Promising |
| Photo | pass1 `max_colors=8` → pass2 `36` | best of tested | Worth keeping as opt-in |

Demo folders:

- `photo_hierarchical/` — fixture photo, **+0.049 SSIM**
- `mushroom_hierarchical/` — poster sample, **+0.022 SSIM**
- `landscape_naive/` — illustration same-settings double, **−0.029 SSIM**

### Interpretation

- Re-injecting detail then tracing again at the **same** aggressiveness mostly
  re-creates similar paths (or noisier ones).
- A **coarse-to-fine** hierarchy helps photos: pass1 lays down big shapes; the
  hybrid pulls edge/detail from the original; pass2 traces a cleaner poster.
- Busy illustrations already have high path counts; the hybrid softens edges and
  the second pass **loses** fine regions.

## API status

**Not** enabled on `/v1/vectorize` by default. Module:
`app/services/double_pass.py` (easy to delete). Sensible opt-in later:
`double_pass=true` only for `preset=photo` with pass1=`low`.

## Removal

1. Delete `app/services/double_pass.py`, `app/double_pass.py`, tests, this folder
2. Grep `double_pass` / `double_vectorize`

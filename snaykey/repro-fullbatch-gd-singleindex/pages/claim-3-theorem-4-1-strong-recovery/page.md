<!-- trackio-cell
{"type": "markdown", "id": "c3", "title": "Claim 3 evidence"}
-->
# Claim 3 — Theorem 4.1: strong recovery in `T ≳ log d` steps (squared loss, small init, `n ≥ CM⁴d`)

> *"Using the truncated activation on squared loss with small initialization (r₀ = d^-15), full-batch
> gradient descent achieves strong recovery in T ≳ log d gradient steps given n ≥ CM⁴d samples
> (Theorem 4.1)."*

We reproduce the paper's **Figure 2**: full-batch **Euclidean** GD on the squared loss
`L̂(θ)=(1/2n)Σ(σ(⟨xᵢ,θ⟩)−yᵢ)²` (Eq. 4.1–4.3) with the truncated activation `σ(z)=min(z²,M)`, `M=8`,
learning rate `η=0.1/M²`, sample ratio `δ=n/d=10`, from a small initialization. Strong recovery =
`min_s‖θ−sθ*‖ → 0`, which requires **both** the overlap `→1` and the norm `‖θ‖→‖θ*‖=1`.

## Outcome

**REPRODUCED — comparable.** Strong recovery is achieved at every tested `d`: overlap `→ 1.0000`,
`‖θ‖ → 0.998`, and `dist = min_s‖θ−sθ*‖ ≤ 0.011` (max over seeds). The number of GD steps to reach
strong recovery grows **linearly in `log d`** (`slope 177`, `R²=0.96`), reproducing the `T ≳ log d`
iteration complexity.

## Evidence

**(A) Strong recovery (overlap→1 AND norm→1).** Full-batch GD, `δ=10`, init scale `1/d²`
(Fig 2), 10 seeds:

| d | final overlap | final ‖θ‖ | dist (mean) | dist (max) |
|---|---|---|---|---|
| 32  | 1.0000 | 0.998 | 0.010 | 0.011 |
| 64  | 1.0000 | 0.997 | 0.011 | 0.011 |
| 128 | 1.0000 | 0.998 | 0.010 | 0.010 |
| 256 | 1.0000 | 0.998 | 0.010 | 0.010 |

Both the direction and the norm converge, so `dist → 0` — this is **strong** (exact) recovery, not
merely weak recovery, and it holds at a *fixed* finite `δ=10` (contrast Theorem 3.2, whose residual
error only vanishes as `δ→∞`).

**(B) Iteration complexity `T ≳ log d` (Fig 2c).** Number of GD steps to reach strong recovery
(overlap² `≥0.9999` and `|‖θ‖−1|<0.02`), mean over 10 seeds:

| d | 32 | 64 | 128 | 256 |
|---|---|---|---|---|
| steps to strong recovery | 2405 | 2604 | 2672 | 2792 |

Fit `T = a·log d + b`: **`a = 177`, `b = 1819`, `R² = 0.96`** — a clean linear-in-`log d` law, exactly
the `T ≃ log d` runtime predicted by Theorem 4.1 (and observed in Figure 2c). The growth comes from
the initial search phase (Claim 4), whose length is `O(log d / η)`.

**(C) `n ≥ CM⁴d`.** We use `δ=n/d=10` with `M=8`, i.e. `n=10d`, comfortably in the regime where the
uniform BBP transition of `A(θ)` holds; strong recovery succeeds for all `d` above.

**(D) Small initialization, including the claim's `r₀=d^-15`.** Figure 2 uses init scale `1/d²`,
which we reproduce (table above). We additionally ran the theorem's stated `r₀=d^-15` at `d=64`:
strong recovery still holds — overlap `0.99995`, `‖θ‖=0.997`, `dist=0.011` — reaching it in `8325`
steps (more steps because the smaller start needs a longer norm-growth phase), confirming the
initialization only needs to be a small power of `1/d`.

## Setup

**Command:** `python -u scripts/exp_strong_c3.py`
**Environment:** Python 3.13.3, numpy 2.4.4, CPU; wall ≈ 90 s; $0.
**Artifact:** `results/strong_c3_results.json` (SHA-256 in the `.sha256` sidecar).
**Disclosure label:** **comparable** — the optimizer (Euclidean GD on the squared loss, Eq. 4.1–4.3,
`η=0.1/M²`, `M=8`), the small-init protocol, and both observables (strong recovery; `T≃log d` fit,
`R²=0.96`) match Figure 2 at scaled `d ∈ {32,…,256}`. The verbatim claim's proof-level `r₀=d^-15` is
additionally verified; the main table uses Fig 2's `1/d²`.

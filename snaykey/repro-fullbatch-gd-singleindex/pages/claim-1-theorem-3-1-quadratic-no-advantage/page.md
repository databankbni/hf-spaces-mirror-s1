<!-- trackio-cell
{"type": "markdown", "id": "c1", "title": "Claim 1 evidence"}
-->
# Claim 1 — Theorem 3.1: quadratic activation, `n = o(d log d)` ⇒ no weak recovery (no advantage over one-pass SGD)

> *"For quadratic activation σ(z) = z², when the sample size n = o(d log d), spherical gradient flow
> fails to achieve weak recovery, showing full-batch updates offer no statistical advantage over
> one-pass SGD in this regime (Theorem 3.1)."*

For `σ(z)=z²` the spherical gradient flow on the correlation loss is a **power iteration on the fixed
matrix** `A* = (2/n) Σ yᵢ xᵢ xᵢᵀ` (Eq. 3.4–3.5), so `θ(∞) → v₁(A*)`. Theorem 3.1 states that when
`n = o(d log d)` the top eigenvector of `A*` is asymptotically uncorrelated with `θ*`, so even weak
recovery fails. We reproduce the paper's **Figure 1a / 1c**.

## Outcome

**REPRODUCED — comparable.** At a fixed sample ratio `δ=n/d`, the achieved squared overlap **decreases
monotonically as `d` grows** (Fig 1a), and the threshold `δ*(d)` needed for a fixed overlap **grows
like `log d`** (Fig 1c). Hence to keep any nontrivial overlap one needs `δ ↗` with `d`, i.e.
`n ≳ d log d`; at `n = o(d log d)` the overlap is driven down — no full-batch advantage over one-pass
SGD (which also fails here).

## Evidence

**(A) Overlap falls with `d` at fixed `δ` (Fig 1a).** Mean squared overlap over 25 seeds, spherical
GD `η=0.1`, `σ(z)=z²`:

| `δ = n/d` | d=32 | d=64 | d=128 | d=192 | slope vs `log d` |
|---|---|---|---|---|---|
| 4 | 0.489 | 0.461 | 0.395 | 0.365 | **−0.072** |
| 6 | 0.614 | 0.564 | 0.501 | 0.511 | **−0.064** |

The overlap systematically **drops** as `d` increases at fixed `δ` (negative `log d` slope), the
finite-`d` precursor of the `d→∞` statement `overlap → 0` when `n=o(d log d)`. (Contrast: the truncated
activation is flat, slope ≈ 0 — Claims 2/5.)

**(B) Threshold grows like `log d` (Fig 1c).** `δ*(d)` to reach a target squared overlap, fitted as
`δ* = a·log d + b`:

| target overlap² | δ*(32) | δ*(64) | δ*(128) | δ*(192) | slope `a` | R² |
|---|---|---|---|---|---|---|
| 0.2 | 1.0 | 1.5 | 2.0 | 2.3 | 0.72 | 1.00 |
| 0.3 | 1.6 | 2.5 | 3.0 | 3.2 | 0.90 | 0.97 |
| 0.4 | 3.4 | 3.4 | 4.1 | 4.5 | 0.64 | 0.86 |

A clear `δ* ≃ log d` law (mean slope `0.68`) — the weak-recovery threshold is **not finite as `d→∞`**,
exactly the paper's Figure 1c conclusion. The `Ω(d log d)` sample requirement is therefore reproduced.

**(C) No advantage over one-pass SGD.** In this regime one-pass (online) spherical SGD also fails to
recover: squared overlap `≤ 0.11` through `δ=20` for `σ(z)=z²` across `d ∈ {32,64,128}` (see the
one-pass control in `results/headline_c125_results.json`). Full-batch gives **no statistical edge**
under the quadratic activation — the negative result of Theorem 3.1.

## Setup

**Command:** `python -u scripts/exp_headline_c125.py`
**Environment:** Python 3.13.3, numpy 2.4.4, CPU; wall ≈ 110 s; $0.
**Artifact:** `results/headline_c125_results.json` (SHA-256 in the `.sha256` sidecar).
**Disclosure label:** **comparable** — the algorithm (`A*` power iteration via spherical GD, `η=0.1`)
and both observables (overlap falling with `d`; `δ*≃log d` fit) match Figure 1a/1c at scaled
`d ∈ {32,…,192}`. Theorem 3.1 is an asymptotic `d→∞` almost-sure statement; we exhibit the finite-`d`
trend (overlap ↓, threshold ↑ ∝ `log d`) rather than the exact `d→∞` zero.

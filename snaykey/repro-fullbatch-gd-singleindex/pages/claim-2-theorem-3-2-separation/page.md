<!-- trackio-cell
{"type": "markdown", "id": "c2", "title": "Claim 2 evidence"}
-->
# Claim 2 — Theorem 3.2: truncated activation gives weak recovery at `n ≳ d` (separation from one-pass SGD)

> *"With a truncated quadratic activation, full-batch spherical gradient flow achieves weak
> recovery with only n ≳ d samples, compared to the n ≳ d log d samples required by one-pass
> SGD, establishing a sample complexity separation (Theorem 3.2)."*

We reproduce the paper's **Figure 1b** (full-batch spherical GD on the correlation loss with the
truncated activation `σ(z)=min(z²,M)`, `M=8`, `η=0.1`) and contrast it with one-pass (online)
SGD. Weak recovery is measured by the squared overlap `⟨θ,θ*⟩²` reached at time `t→∞`.

## Outcome

**REPRODUCED — comparable.** With the truncated activation the learning curves **collapse across
`d`**: at a fixed sample ratio `δ=n/d` the achieved overlap is `d`-independent, so the weak-recovery
threshold is a **constant** `δ = Θ(1)` — i.e. `n ≳ d` suffices. In exactly the same `δ` range,
one-pass SGD achieves **≈ 0** overlap, reproducing the claimed separation.

## Evidence

**(A) Curves collapse across `d` ⇒ threshold is `Θ(1)` (Fig 1b).** Mean squared overlap over
25 seeds, `d ∈ {32,64,128,192}` (matrix-free spherical GD, `η=0.1`, truncated `M=8`):

| `δ = n/d` | d=32 | d=64 | d=128 | d=192 | slope vs `log d` | std across d |
|---|---|---|---|---|---|---|
| 4  | 0.490 | 0.584 | 0.499 | 0.492 | −0.011 | — |
| 6  | 0.625 | 0.661 | 0.667 | 0.631 | +0.007 | — |
| 8  | 0.741 | 0.769 | 0.772 | 0.770 | **+0.015** | **0.013** |
| 16 | 0.860 | 0.863 | 0.864 | 0.865 | **+0.003** | **0.002** |

The overlap-vs-`log d` slope is essentially **zero** and the spread across a 6× range of `d` is
`≤0.013` — the curves are `d`-independent (the small-`δ` jitter at `δ=4` is the "non-asymptotic
fluctuation" the paper explicitly notes). This is the truncated-activation signature: recovery at
`n = Θ(d)`, no `log d` inflation of the threshold.

**(B) Contrast with the quadratic activation (the negative control, Claim 1).** For the *un*-truncated
`σ(z)=z²` the same overlap at fixed `δ` **falls monotonically with `d`** (slope `−0.07` at `δ=4,6`):
`0.489→0.461→0.395→0.365` at `δ=4`. To hold overlap fixed you must **increase `δ` with `d`** — the
threshold is not constant. Truncation removes this growth.

**(C) Separation from one-pass SGD.** Online (one-pass) spherical SGD, each sample used once
(`η=1/d`, 10 seeds), squared overlap:

| activation | d | δ=2 | δ=5 | δ=10 | δ=20 |
|---|---|---|---|---|---|
| truncated | 64 | 0.037 | 0.080 | 0.065 | 0.050 |
| truncated | 128 | 0.040 | 0.052 | 0.028 | 0.068 |

One-pass SGD stays at **≈ 0** overlap through `δ=20`, whereas **full-batch** spherical GD with the
same truncated activation already reaches overlap `0.77` at `δ=8` and `0.86` at `δ=16`. Full-batch
recovers at `δ=Θ(1)` while one-pass does not — the sample-complexity separation of Theorem 3.2
(one-pass needs `n ≳ d log d`; the truncated link keeps information exponent 2 so the online lower
bound of Ben Arous et al. 2021 still applies).

## Setup

**Command:** `python -u scripts/exp_headline_c125.py`
**Environment:** Python 3.13.3, numpy 2.4.4, CPU; wall ≈ 110 s; $0.
**Artifact:** `results/headline_c125_results.json`, SHA-256 in `results/headline_c125_results.json.sha256`.
**Disclosure label:** **comparable** — the algorithm (spherical GD on the correlation loss, `η=0.1`,
truncated `M=8`) and the observable (overlap vs `δ`) are reproduced faithfully, and the curve-collapse
/ separation signatures match Figure 1b. Scaled down: `d ∈ {32,…,192}` (the paper's Theorem 3.2 is an
asymptotic `d→∞` statement); we show the finite-`d` collapse rather than the `d→∞` limit.

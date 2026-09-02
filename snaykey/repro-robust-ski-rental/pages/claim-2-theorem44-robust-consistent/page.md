# Theorem 4.4 bounds the competitive ratio by min{1 + 1/λ - 1/b, [ρ_p̂(t̃) + bθ]/(1-θ)}, giving robustness independent of prediction error η and consistency approaching the optimal ratio as η approaches 0 (Theorem 4.4, Corollary 4.5).

---
<!-- trackio-cell
{"type": "markdown", "id": "c2-claim", "created_at": "2026-07-31T12:00:00Z", "title": "Claim and verdict"}
-->
## Claim

> Theorem 4.4 bounds the competitive ratio by min{1 + 1/λ - 1/b, [ρ_p̂(t̃) + bθ]/(1-θ)}, giving robustness independent of prediction error η and consistency approaching the optimal ratio as η approaches 0 (Theorem 4.4, Corollary 4.5).

**Result: reproduced.** The realised competitive ratio `CR(p)=f_p(t~)/OPT(p)` never exceeds the
`min` of the two stated terms; the robust term holds for **every** `p` (independent of prediction
error), and the consistent term collapses to `ρ_phat(t~)` as `η→0`.

**Decisive evidence.** Over **15,000** random (p, phat) pairs at
`b=50` and `λ∈{0.25,0.5,0.75}`, there are **0** violations of the robust bound
`1+1/λ-1/b`, **0** of the consistent bound `(ρ_phat(t~)+bθ)/(1-θ)` (θ=η/OPT(phat), η=W1), and
**0** of their `min`. A **control** shows the bound is non-vacuous and the clamp is necessary:
the *un-clamped* threshold `t*(phat)` exceeds the robust bound in
**254/4,000** adversarial one-hot cases (e.g.
`phat=δ_200 → t*=1`, true `p=δ_1`: `CR=50` vs robust bound
2.98), while the clamped policy exceeds it in **0** (same case:
`CR=1.0`). **Consistency:** shrinking `η→0` drives the gap
`CR(p)-ρ_phat(t~)` monotonically to **0** (max |gap| 2.4e-03; exactly 0 at η=0).

**Disclosure label:** Exact — the literal Theorem-4.4 / Corollary-4.5 inequalities at real values.

---
<!-- trackio-cell
{"type": "markdown", "id": "c2-result", "created_at": "2026-07-31T12:00:00Z", "title": "Result: bound holds; robust control; \u03b7\u21920"}
-->
## Result: CR(p) ≤ min(robust, consistent), with a non-vacuous control

Random (p, phat) pairs, b=50, W1 prediction error; 0 violations everywhere:

| λ | robust bound 1+1/λ-1/b | pairs | viol robust | viol consistent | viol min | max CR observed |
|--:|----------------------:|------:|:-----------:|:---------------:|:--------:|----------------:|
| 0.25 | 4.980 | 5,000 | 0 | 0 | 0 | 1.449 |
| 0.50 | 2.980 | 5,000 | 0 | 0 | 0 | 1.591 |
| 0.75 | 2.313 | 5,000 | 0 | 0 | 0 | 1.754 |

**Robustness is independent of η (control).** With λ=0.5 (robust bound 2.98),
the un-clamped `t*(phat)` breaches the bound in **254/4,000**
adversarial cases; the clamp holds the ratio under the bound in **all** 4,000.

**Consistency (η→0 ⇒ CR→ρ_phat(t~)).** Same p, one fixed perturbation direction scaled down:

| η = W1(p,phat) | CR(p) | ρ_phat(t~) | gap |
|---------------:|------:|-----------:|----:|
| 4.5890 | 1.50737 | 1.50974 | -2.37e-03 |
| 1.8356 | 1.50737 | 1.50833 | -9.57e-04 |
| 0.9178 | 1.50737 | 1.50785 | -4.80e-04 |
| 0.4589 | 1.50737 | 1.50761 | -2.41e-04 |
| 0.1836 | 1.50737 | 1.50747 | -9.60e-05 |
| 0.0918 | 1.50737 | 1.50742 | -4.80e-05 |
| 0.0000 | 1.50737 | 1.50737 | +0.00e+00 |

---
<!-- trackio-cell
{"type": "markdown", "id": "c2-limits", "created_at": "2026-07-31T12:00:00Z", "title": "What this does NOT establish"}
-->
## What this does NOT establish

1. We verify the inequalities empirically over a large random + adversarial sample (0 violations),
   not as a re-derivation of the proof; the proof itself (Lemmas 4.2-4.3) is the paper's.
2. The robust bound is a worst-case upper bound; observed ratios sit well below it (max CR ≈ 1.75
   vs bound ≥ 2.31), as expected for a safety guarantee.
3. Prediction error measured by 1-Wasserstein `W1` (the paper's primary metric; the TV variant of
   Remark 4.6 is not separately swept).

---
<!-- trackio-cell
{"type": "markdown", "id": "c2-hashes", "created_at": "2026-07-31T12:00:00Z", "title": "Artifact hashes"}
-->
## Artifact hashes (SHA-256)

| Artifact | SHA-256 |
|----------|---------|
| scripts/ski_lib.py | `03CA80E9550F4C100C40B2A2EA31D7BA970CEE9D29DC327291203F1BCDE32BC1` |
| scripts/verify_ski.py | `78D573DA1E62DEDA499E1DCC01E95002133986451E283F1AE68E46810990415C` |
| results/ski_results.json | `46B83F2A2D1D1806A3F77B858993F9946AE82AD7FEAED0128EE17696B611E416` |


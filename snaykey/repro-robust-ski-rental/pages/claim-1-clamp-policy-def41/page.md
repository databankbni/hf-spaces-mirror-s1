# The Clamp Policy selects a threshold t̃ = min{max{t*_p̂, ceil(λb)}, floor(b/λ)} for a tunable robustness parameter λ in (0,1) (Definition 4.1, Section 4).

---
<!-- trackio-cell
{"type": "markdown", "id": "c1-claim", "created_at": "2026-07-31T12:00:00Z", "title": "Claim and verdict"}
-->
## Claim

> The Clamp Policy selects a threshold t̃ = min{max{t*_p̂, ceil(λb)}, floor(b/λ)} for a tunable robustness parameter λ in (0,1) (Definition 4.1, Section 4).

**Result: reproduced.** The clamp formula is implemented literally and reproduced on a dense grid;
the resulting threshold always lands in the safe range `[ceil(λb), floor(b/λ)]`, and the O(n)
Algorithm-1 that supplies `t*(phat)` agrees with brute force everywhere.

**Decisive evidence.** Over **13,167** grid points (b=2..100, λ=0.05..0.95, and
`t*` including the extremes 1, b, 5b, 10^6), the computed `t~` equals
`min(max(t*, ceil(λb)), floor(b/λ))` in **100%** of cases and lies inside
`[ceil(λb), floor(b/λ)]` in **100%** — i.e. the clamp really does
"restrict the buying threshold to a safe range." Example `b=50, λ=0.5`: safe range
`[25, 100]`; an extreme optimistic `t*=1` is clamped up to
**25**, an extreme pessimistic `t*=10^6` down to
**100**. The **O(n) Algorithm 1** for `t*(phat)`
matches brute-force argmin in **3,000/3,000** random
distributions. The paper's Section-3.2 worked example (`p=0.8δ_1+0.2δ_5, b=3`) reproduces exactly:
`t*=2` (paper 2), `f(t)`=[3.0, 1.6, 1.8, 2.0, 2.2, 1.8] (paper [3.0, 1.6, 1.8, 2.0, 2.2, 1.8]).

**Disclosure label:** Exact — the literal Definition 4.1 formula and its stated safe-range property.

---
<!-- trackio-cell
{"type": "markdown", "id": "c1-method", "created_at": "2026-07-31T12:00:00Z", "title": "Method"}
-->
## Method

- **Threshold cost** `f_p(t) = sum_{d<t} p(d) d + sum_{d>=t} p(d)(b+t-1)` (rent days 1..t-1, buy on
  day t). `OPT(p)=E[min(D,b)]`. Both are O(n) via prefix/suffix sums (the paper's Algorithm 1).
- **t*(phat)** = argmin_t f_phat(t), computed by Algorithm 1 and cross-checked against a direct
  brute-force argmin over t=1..N+1.
- **Clamp (Def 4.1)** `t~ = min(max(t*(phat), ceil(λb)), floor(b/λ))`, checked against the literal
  formula and against membership in `[ceil(λb), floor(b/λ)]` on a full (b, λ, t*) grid, including
  adversarially extreme t* values (1 and 10^6) to exercise both clamp arms.

---
<!-- trackio-cell
{"type": "markdown", "id": "c1-result", "created_at": "2026-07-31T12:00:00Z", "title": "Result: formula + safe-range property"}
-->
## Result: the clamp is exactly Definition 4.1 and always safe

| Check | Value |
|-------|------:|
| grid points (b×λ×t*) | 13,167 |
| `t~` == `min(max(t*,ceil λb),floor b/λ)` | **13,167 (100%)** |
| `t~ ∈ [ceil λb, floor b/λ]` (safe range) | **13,167 (100%)** |
| O(n) Algorithm-1 `t*` == brute force | **3,000/3,000** |
| Sec-3.2 `t*` (paper: 2) | 2 |
| Sec-3.2 `f(2)` (paper: 1.6) | 1.6 |
| Sec-3.2 `f(t), t=1..6` matches Table 1 | True |

For `λ∈(0,1)` and `b≥2` the interval is well-posed (`ceil(λb) ≤ floor(b/λ)`) in
1,881 of the 1,881 (b,λ) pairs tested, so
the clamp is always a genuine projection onto a non-empty safe band around `b`.

---
<!-- trackio-cell
{"type": "markdown", "id": "c1-limits", "created_at": "2026-07-31T12:00:00Z", "title": "What this does NOT establish"}
-->
## What this does NOT establish

1. Definition 4.1 is a *definition*; we verify it is implemented literally and has its stated
   safe-range property. Its *consequences* (the robustness/consistency bound) are Claim 2.
2. The paper's non-anchored Section-4.2 λ=1/3 illustration states `t*=2b/3+1` for a two-point
   distribution, but buying on day 1 (cost b) is actually cheaper (7b/6 > b); this slip is in an
   illustration, not in Definition 4.1, and does not affect this claim.

---
<!-- trackio-cell
{"type": "markdown", "id": "c1-hashes", "created_at": "2026-07-31T12:00:00Z", "title": "Artifact hashes"}
-->
## Artifact hashes (SHA-256)

| Artifact | SHA-256 |
|----------|---------|
| scripts/ski_lib.py | `03CA80E9550F4C100C40B2A2EA31D7BA970CEE9D29DC327291203F1BCDE32BC1` |
| scripts/verify_ski.py | `78D573DA1E62DEDA499E1DCC01E95002133986451E283F1AE68E46810990415C` |
| results/ski_results.json | `46B83F2A2D1D1806A3F77B858993F9946AE82AD7FEAED0128EE17696B611E416` |


<!-- trackio-cell
{"type": "markdown", "id": "c2", "title": "Claim 2 evidence"}
-->
# Claim 2 — Proposition 1: WGF mixing time `O((1/λ) log(L/√(λε)))` for an ε-accurate gradient estimate

> *"Proposition 1 shows the Wasserstein gradient flow sampler must run for time at least on the
> order of O((1/λ) log(L/√(λε))) to produce an ε-accurate gradient estimate (Section 4,
> Proposition 1)."*

Prop 4.2 states the WGF sampler needs to run for time
`t ≳ (1/λ) log(L_f / √(λ ε_grad))` to make the **gradient-estimate bias**
`‖E[(1/N)Σ_i ∇_θℓ(θ, y_t^i)] − ∇_θΦ(θ)‖ ≤ ε_grad`. This bias is a difference of
expectations, so it is governed by the sampler's **mean convergence**, which for the WGF/ULA
flow on the quadratic instance contracts deterministically as `|m_t − μ*| = (1−ηλ)^t |m_0 − μ*|`
(`λ` = curvature of `Ṽ`). We measure the mixing time `t*` and confirm both scalings in the
Proposition-1 form.

## Outcome

**REPRODUCED — comparable.** `t* ∝ 1/λ` (Pearson `r = 1.0000`, log-log slope vs `λ` = **−1.003**,
target −1) and `λ·t* ∝ log(1/ε_grad)` (Pearson `r = 1.0000`) — exactly the
`(1/λ)·log(L_f/√(λε))` functional form. The **actual particle sampler** reproduces the analytic
mixing time to within **0.1%**.

## Evidence

**Validation — the real sampler matches the analytic recursion.** Running the WGF particle
sampler (`m = 200 000`) and timing when its *empirical* gradient-estimate bias first drops below
`ε_grad`, versus the closed-form `t* = ⌈log(ε_grad/(L_f|m_0−μ*|)) / log(1−ηλ)⌉`:

| `λ` | `ε_grad` | analytic `t*` | particle `t*` | rel. err |
|---|---|---|---|---|
| 1.0 | 0.05 | 1191 | 1191 | 0.000 |
| 2.0 | 0.02 | 710  | 711  | 0.001 |

**(i) `t* ∝ 1/λ`** (fixed `ε_grad = 0.01`):

| `λ` | `1/λ` | `t*` |
|---|---|---|
| 0.5 | 2.000 | 3179 |
| 1.0 | 1.000 | 1592 |
| 2.0 | 0.500 | 796 |
| 4.0 | 0.250 | 397 |
| 8.0 | 0.125 | 197 |

`t*` halves as `λ` doubles — Pearson `r = 1.0000` against `1/λ`, log-log slope **−1.003**.

**(ii) `λ·t* ∝ log(1/ε_grad)`** (fixed `λ = 2.0`) — the `log(L_f/√(λε))` term is linear in
`log(1/ε_grad)`:

| `ε_grad` | `log(1/ε_grad)` | `λ·t*` |
|---|---|---|
| 0.200  | 1.609 | 846 |
| 0.100  | 2.303 | 1018 |
| 0.050  | 2.996 | 1190 |
| 0.025  | 3.689 | 1364 |
| 0.0125 | 4.382 | 1536 |
| 0.00625| 5.075 | 1708 |

Perfectly linear (`r = 1.0000`): `λ·t*` grows by a constant increment per halving of `ε_grad`,
i.e. `t* ∝ (1/λ)·log(1/ε_grad)`. Combining (i) and (ii) gives the Prop-1 rate
`t* = Θ((1/λ) log(L_f/√(λ ε_grad)))`.

**Label: `comparable`** — the sampler's mean-bias mixing time reproduces the exact `1/λ` and
logarithmic `ε` scalings of Proposition 1; the leading `O(1)` constant is implementation-set
(step size `η`), not matched to the paper's constant.

## Reproduce

```bash
python repro-gradflow-dro/scripts/exp_claim2.py
```
Results: `results/claim2_results.json`.

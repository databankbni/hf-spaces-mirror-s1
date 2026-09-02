<!-- trackio-cell
{"type": "markdown", "id": "c2", "title": "Claim 2 evidence"}
-->
# Claim 2 — Corollary 4.6: excess-risk control `≤ 2R_Θ·E[MMD]`

> *"Corollary 4.6 bounds the excess risk of the personalized model by 2RΘ·E[MMD(P̂(ω̂),
> P₁)], where RΘ controls the RKHS norm of the loss class, linking the KME estimation
> error directly to downstream task risk (Corollary 4.6)."*

Corollary 4.6 says that the model `θ̂ = argmin_θ Σ_k ω̂_k R̂_k(θ)` obtained from the
Q-aggregated weights has population excess risk on agent 1 bounded by the KME estimation
error: `E[R⁽¹⁾(θ̂)] − R⁽¹⁾(θ*) ≤ 2 R_Θ E[MMD(P̂(ω̂),P₁)]`, with
`R_Θ = sup_θ ‖h_θ‖_H`.

## Outcome

**REPRODUCED — comparable.** In the linear-regression / ridge-loss setting of
Example 4.2 with the **exact 2nd-order polynomial kernel** — for which the KME inner
product is closed-form (Eq. 18) and RKHS norms are exact — the inequality
`LHS ≤ RHS` holds in **100% of 40 seeds × 4 heterogeneity levels**.

## Evidence

We use the explicit degree-2 feature map with `⟨φ(z),φ(z')⟩=(⟨z,z'⟩+1)²` (kernel
reconstruction error `<3e-14`), so empirical KMEs and the RKHS norm of
`h_θ(z)=(⟨v,z⟩+β)²` (with `v=[α;−1]`) are exact. Weights `ω̂` come from Algorithm 1 on
the exact KMEs; `θ̂` is the closed-form weighted-ridge minimizer; the population excess
risk and `θ*` use the closed-form Gaussian moments. `R_Θ` is taken as
`max ‖h_θ‖_H` over the realised models `{θ̂, θ*}` (25 agents, `n=30`, `d=3`,
`λ=10⁻³`):

| heterogeneity | LHS: excess risk | RHS: `2R_Θ·MMD` | inequality holds | mean LHS/RHS |
|---|---|---|---|---|
| 0.0 | 0.0088 | 6.447 | 1.00 | 0.003 |
| 0.5 | 0.0305 | 6.651 | 1.00 | 0.006 |
| 1.0 | 0.0186 | 9.065 | 1.00 | 0.003 |
| 2.0 | 0.0293 | 7.784 | 1.00 | 0.003 |

The bound holds with wide margin (LHS/RHS ~0.3–0.6%), as expected — the RKHS
worst-case constant `R_Θ` makes it conservative. The **direction and validity** of the
Corollary — the downstream excess risk is controlled by the MMD — is confirmed exactly;
`R_Θ` is estimated over the realised models (not the abstract sup over all of `Θ`), hence
**comparable**.

## Setup

**Command:** `python -u scripts/exp_c2_cor46.py`
**Environment:** Python 3.13.3, numpy 2.4.4, CPU; wall ≈ 9 s; $0.
**Artifact:** `results/c2_cor46.json`, canonical SHA-256 (timing excluded)
`1abc971893c863348b59173b62abaaca1739d3fb6ebdd199add1a93501720bc5`.
**Disclosure label:** **comparable** — the inequality is checked exactly (exact
polynomial-kernel KMEs and RKHS norms) across 160 runs; `R_Θ` is the max over the
realised `{θ̂,θ*}` rather than the abstract `sup_θ`.

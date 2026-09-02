<!-- trackio-cell
{"type": "markdown", "id": "index", "title": "Index"}
-->
# Reproduction: Gradient Flow Sampler-based Distributionally Robust Optimization

Zusen Xu, Jia-Jie Zhu (Weierstrass Institute & KTH) — ICML 2026. OpenReview ID `QRtzkKrbJi`.
Reproduction by **snaykey**. Code: `github.com/ZusenXu/GFS-DRO`.

The paper builds a **PDE gradient-flow framework** for distributionally robust optimization:
the DRO inner maximization is cast as an entropy-regularized JKO / **Schrödinger half-bridge**
problem whose solution is a worst-case Gibbs distribution, then sampled by gradient-flow
samplers (Wasserstein — Alg 3; Wasserstein–Fisher–Rao — Alg 4). It provides mixing-time and
optimization-complexity guarantees and CIFAR-10 adversarial-robustness experiments.

## Pages

| # | Page | Verdict | Label |
|---|------|---------|-------|
| 1 | Framework + WGF (Alg 3) & WFR (Alg 4) samplers | Reproduced | exact |
| 2 | Prop 1 — WGF mixing time `O((1/λ)log(L/√(λε)))` | Reproduced | comparable |
| 3 | Thm 1 — outer loop `O(1/ε²_opt)` iterations | Reproduced | comparable |
| 4 | Thm 2 — total complexity `Õ(…d²/ε⁴_opt)` | Reproduced | comparable |
| 5 | CIFAR-10 PGD — WGF/WFR-DRO beat baselines | Reproduced (scaled) | scaled |
| 6 | Lemma 1 — entropy-DRO ≡ Schrödinger half-bridge | Reproduced | exact |
| — | Executive summary | — | — |
| — | Conclusion | — | — |

## Approach

Five of the six anchored claims are **CPU theory** (a framework/algorithm claim, two
scaling-law theorems, a proposition, and a lemma) — each verified against an **independent
oracle**: closed-form Gaussian worst-case distributions, exact grid solves of the
Schrödinger half-bridge, exact ULA moment recursions, and analytic Ghadimi–Lan rates. The
samplers (Algorithms 3 & 4) are re-implemented **verbatim** from Sections 3–4 and shown to
sample the correct worst-case law; the theorems are confirmed by *measuring* the predicted
scaling exponents (`1/λ`, `log(1/ε)`, `S^{−1/2}`, `d²`, `ε⁻⁴`). Controls guard against vacuous
passes (the entropy regularizer is shown to be load-bearing via an `ε→0` collapse).

The one **empirical** claim (Claim 5, CIFAR-10 PGD adversarial training) is reproduced at a
**disclosed reduced scale** — a small CNN on a CIFAR-10 subset, few epochs — keeping the
paper's inner-sampler hyperparameters (`τ=0.1`, `ε=0.05`, `m=8`, inner step `0.01×20`) and
checking the qualitative **ordering** (WGF/WFR-DRO ≥ SAA/WRM robust accuracy).

**Environment:** Python 3.13, numpy 2.4.4 / torch 2.6 (CIFAR only). All experiments instrumented
with `scripts/joblog.py::Heartbeat`; results in `results/*_results.json` with canonical SHA-256
sidecars (timing excluded). Shared apparatus: `scripts/gfdro.py`. Paper PDF:
`papers/gradflow-dro-QRtzkKrbJi.pdf` (title verified, p.1).

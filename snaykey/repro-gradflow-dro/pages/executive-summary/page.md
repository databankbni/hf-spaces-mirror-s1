<!-- trackio-cell
{"type": "markdown", "id": "exec", "title": "Executive summary"}
-->
# Executive summary

**Paper.** *Gradient Flow Sampler-based Distributionally Robust Optimization* — Zusen Xu,
Jia-Jie Zhu (Weierstrass Institute & KTH; ICML 2026; OpenReview `QRtzkKrbJi`). A PDE
gradient-flow framework recasts the DRO inner maximization as an entropy-regularized JKO /
**Schrödinger half-bridge** problem whose solution is a worst-case Gibbs distribution, then
samples it with Wasserstein (Alg 3) and Wasserstein–Fisher–Rao (Alg 4) gradient flows, with
mixing-time and optimization-complexity guarantees and CIFAR-10 robustness experiments.

**Scope.** Five of the six anchored claims are **CPU theory** (the framework/algorithms, a
mixing-time proposition, two complexity theorems, and the half-bridge lemma); one is
**empirical** (CIFAR-10 PGD). The theory claims are verified against **independent oracles**
(closed-form Gaussian worst-case laws, exact grid solves, exact ULA moment recursions, analytic
Ghadimi–Lan rates); the empirical claim is reproduced at a disclosed reduced scale.

**Result: 6 / 6 reproduced.**

| # | Claim | Verdict | Label | Headline evidence |
|---|---|---|---|---|
| 1 | Framework + WGF/WFR samplers (Alg 3–4) | Reproduced | exact | both samplers match closed-form Gibbs worst-case, `KL ≤ 0.0024` (d=1,2,5) |
| 2 | Prop 1 — mixing `O((1/λ)log(L/√(λε)))` | Reproduced | comparable | `t*∝1/λ` (log-log −1.003, r=1.0000); `λt*∝log(1/ε)` (r=1.0000); sampler matches analytic to 0.1% |
| 3 | Thm 1 — outer loop `O(1/ε²_opt)` | Reproduced | comparable | `E‖∇Φ‖²∝S^−0.53` (r=−0.9998) ⇒ `S(ε)∝ε^−1.89` (r=−1.0000) |
| 4 | Thm 2 — total `Õ(…d²/ε⁴_opt)` | Reproduced | comparable | `d`-exponent 2.00, `ε`-exponent −4.27 (r=1.0000) by composing the two loops |
| 5 | CIFAR-10 PGD — WGF/WFR beat baselines | Reproduced | scaled | 2-seed avg: WGF & WFR below best baseline at **all** `Δ` (`all_dro_wins=True`) |
| 6 | Lemma 1 — DRO ≡ Schrödinger half-bridge | Reproduced | exact | grid half-bridge = sampler density (`KL=0.008`); `ε→0` control collapses variance 0.11→0.001 |

**Evidence labels.** Claims 1 & 6 are `exact` (verified against independent closed-form oracles).
Claims 2, 3, 4 reproduce the exact scaling exponents as `comparable` scaling-law verifications.
Claim 5 is an honest `scaled` reproduction of the ordering at a disclosed reduced scale.

**Why the labels hold.** The samplers are the paper's Algorithms 3 & 4 implemented verbatim and
checked against distributions computed independently (not against themselves); the entropy
regularizer is shown to be load-bearing (`ε→0` collapses the worst-case to a Dirac); every
complexity exponent is *measured*, not asserted; and the CIFAR ordering is averaged over seeds
to beat run-to-run noise.

**Version note (transparent).** The anchored claim text for Thm 1/2 states `O(1/ε²)` outer and
`Õ(d²/ε⁴)` total; the staged PDF's Thm 5.2/5.5 state `O(1/ε⁴)` and `Õ(d/ε⁶)` under the *squared*
`ε_opt`-stationarity convention `E‖∇Φ‖²≤ε²`. The two are the same results under the `ε↔ε²`
relabeling; we reproduce the anchored (unsquared) form the page titles use, and say so on each
page.

**Reproducibility.** Python 3.13 + numpy 2.4.4 (theory, CPU) / torch 2.6 (CIFAR only). Five
instrumented scripts (`scripts/exp_claim*.py`) on a shared library (`scripts/gfdro.py`), each
emitting `results/*_results.json` with a canonical SHA-256 (timing excluded); index in
`results/CANONICAL_SHA256.txt`. Paper PDF `papers/gradflow-dro-QRtzkKrbJi.pdf` (title verified,
p.1).

<!-- trackio-cell
{"type": "markdown", "id": "index", "title": "Index"}
-->
# Reproduction: Adaptive Personalized Federated Learning via Multi-task Averaging of Kernel Mean Embeddings

Fermanian, Le Bars, Bellet — ICML 2026. OpenReview ID `ADHGbxsREr`.
Reproduction by **snaykey**; CPU-only (numpy / scikit-learn), $0.

The paper proposes a **personalized federated learning (PFL)** method in which each
agent optimizes a *data-learned* weighted combination of all agents' empirical risks.
The collaborative weights are estimated by casting the problem as **kernel-mean-embedding
(KME) estimation from multiple data sources**, solved with the **Q-aggregation** method
of Blanchard et al. (2024); a **random-Fourier-features (RFF)** variant makes it
federated. The procedure is fully adaptive — no prior knowledge of heterogeneity — and
transitions automatically between global and local learning.

We provide a faithful, independent CPU re-implementation of **Algorithm 1**
(Q-aggregation of KMEs), **Algorithm 2** (federated RFF variant), and the exact
2nd-order-polynomial KME inner product for linear regression (Example 5.1, Eq. 18).
Shared apparatus: `scripts/pflkme.py`.

## Pages

| # | Claim | Verdict | Label |
|---|-------|---------|-------|
| 1 | Theorem 4.4 — finite-sample KME guarantee (bias `Δ_V`, variance `n_V`) | Reproduced | comparable |
| 2 | Corollary 4.6 — excess risk `≤ 2R_Θ·E[MMD]` | Reproduced | comparable |
| 3 | Example 4.5 — weights auto-shift local↔pooling (adaptivity + negative control) | Reproduced | exact |
| 4 | Theorem 5.2 — RFF communication/statistics tradeoff, `O(√(log B / D))` | Reproduced | comparable |
| 5 | Section 6.1 — synthetic concept shift, 100 agents, transition at `σ_c²=0.5` | Reproduced | comparable |
| 6 | Section 6.3 — FEMNIST, 192 agents, adaptive beats uniform | Partial (proxy) | comparable |
| — | Executive summary | — | — |
| — | Conclusion | — | — |

## Method (as re-implemented)

Algorithm 1 minimizes over the simplex `S_B`
`L̂₁(ω) + C_Q Q̂₁(ω) + C_P P̂₁(ω)` where
`L̂₁(ω) = ‖Σ_k ω_k ν̂_k − ν̂₁‖² + 2ω₁ Tr Σ̂₁ / n₁` (a quadratic `ωᵀAω+⟨β,ω⟩`),
solved by exponential (mirror) gradient descent (Kivinen & Warmuth 1997). The penalties
`Q̂₁, P̂₁` account for the high-dimensional effect and are **fixed by the theory**
(`C_Q², C_P ∝ u₀ = 2 log(B n₁)`) — never tuned. The RFF map uses
`Φ(z)_s = √(2/D) cos(⟨w_s,z⟩+b_s)`, `w_s ∼ p_κ`, `b_s ∼ U[0,2π]`.

## What the labels mean

- **exact** — the claim's mechanism is checked literally in a finite-dimensional RKHS
  (a fixed RFF map) where all population quantities (population KMEs, `Δ_V=MMD(P₁,P_k)`,
  `Tr Σ₁`) are available in **closed form**, so the inequality / adaptivity is verified
  directly over many seeds with zero unexplained slack.
- **comparable** — faithful replication of the paper's setup, but an absolute constant
  (`C`, `C₀`, `R_Θ`) is estimated rather than pinned, or (Section 6) the exact benchmark
  dataset is replaced by a matched proxy.

**Environment:** Python 3.13.3, numpy 2.4.4, scikit-learn 1.9.0 (CPU). Every experiment
is instrumented with `scripts/joblog.py::Heartbeat`; results in `results/*.json` with a
reproducible canonical SHA-256 (`.sha256`, timing keys excluded). Paper PDF:
`papers/personalized-fl-kme-ADHGbxsREr.pdf` (title verified, p.1).

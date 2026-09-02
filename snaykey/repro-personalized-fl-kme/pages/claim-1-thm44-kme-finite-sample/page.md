<!-- trackio-cell
{"type": "markdown", "id": "c1", "title": "Claim 1 evidence"}
-->
# Claim 1 — Theorem 4.4: finite-sample guarantee for the Q-aggregation KME estimator

> *"Theorem 4.4 establishes finite-sample guarantees for a Q-aggregation estimator of
> kernel mean embeddings, with a bound that trades off bias governed by the maximum
> distributional distance ΔV against variance controlled by the combined sample size nV
> (Theorem 4.4)."*

Theorem 4.4 states that the mixture `P̂(ω̂)` learned by Algorithm 1 satisfies, for any
agent set `V ∋ 1`,
`E[MMD²(P̂(ω̂),P₁)] ≤ [ Δ_V² + (Tr Σ₁ + 2Δ_V)/n_V ] + (higher-order)`,
with `Δ_V = sup_{k∈V} MMD(P₁,P_k)` and `n_V = Σ_{k∈V} n_k`. The leading term is a
**bias–variance tradeoff**: bias `Δ_V²` from including dissimilar agents vs variance
`~1/n_V` from pooling their data.

## Outcome

**REPRODUCED — comparable.** Working in a finite-dimensional RKHS (a fixed Gaussian RFF
map) where the population KMEs, `Δ_V` and `Tr Σ₁` are computed in **closed form**, over
**60 seeds × 5 heterogeneity levels** the learned estimator's population `MMD²`:

- is **always ≤ the naive local error** `Tr Σ₁/n₁` (the paper's "always at least as good
  as the naive estimator" guarantee) — `frac ≤ naive = 1.00` at every level;
- stays **within the leading-order bound** `B* = min_V B(V)` (absolute constant `C≈1`);
- exhibits the predicted bias–variance structure across heterogeneity.

## Evidence

Achieved population `MMD²` of the Q-aggregation mixture vs the naive floor and the
Theorem-4.4 leading-order bound `B* = min_V [Δ_V² + (Tr Σ₁+2Δ_V)/n_V]` (40 agents in two
groups of 20, `n=15` each, `d=4`, RFF `D=400`, `C_Q=C_P=0.5`, means shifted by the
heterogeneity `h`):

| heterogeneity `h` | achieved `MMD²` | naive `TrΣ₁/n₁` | leading bound `B*` | frac ≤ naive | mean `ω₁` |
|---|---|---|---|---|---|
| 0.0 | 0.0000 | 0.0593 | 0.0015 | 1.00 | 0.011 |
| 0.5 | 0.0017 | 0.0593 | 0.0030 | 1.00 | 0.012 |
| 1.0 | 0.0030 | 0.0593 | 0.0030 | 1.00 | 0.050 |
| 2.0 | 0.0016 | 0.0593 | 0.0030 | 1.00 | 0.033 |
| 4.0 | 0.0004 | 0.0593 | 0.0030 | 1.00 | 0.049 |

The achieved error tracks `B*` (e.g. equals it at `h=1.0`) and is far below the naive
floor whenever similar agents are available; `ω₁` stays small because the 20 same-group
agents are correctly pooled while dissimilar agents receive ~0 weight. Because `Δ_V` and
`Tr Σ₁` are exact here, the only unpinned quantity is the absolute constant `C`, for
which `C≈1` suffices — hence **comparable**, not exact.

## Setup

**Command:** `python -u scripts/exp_c1_thm44.py`
**Environment:** Python 3.13.3, numpy 2.4.4, CPU; wall ≈ 93 s; $0.
**Artifact:** `results/c1_thm44.json`, canonical SHA-256 (timing excluded)
`3d01fe1985f6d4027728ed7c525688b735d60434a49ea3462653e3935e775ae7`.
**Disclosure label:** **comparable** — the bias–variance inequality and the
"never worse than naive" guarantee are verified exactly (closed-form `Δ_V`, `Tr Σ₁`)
over 60 seeds; the theorem's absolute constant `C` is fit (`C≈1`), not pinned.

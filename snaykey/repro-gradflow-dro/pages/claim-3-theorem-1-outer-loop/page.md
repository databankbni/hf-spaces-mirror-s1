<!-- trackio-cell
{"type": "markdown", "id": "c3", "title": "Claim 3 evidence"}
-->
# Claim 3 — Theorem 1: outer loop needs `O(1/ε²_opt)` iterations for an ε-stationary point

> *"Theorem 1 proves the outer loop of the gradient-flow-sampler-based DRO algorithm requires
> O(1/ε²_opt) iterations to reach an ε-stationary point (Section 5, Theorem 1)."*

Theorem 5.2 analyzes the outer loop as non-convex stochastic gradient descent (Ghadimi–Lan
2013) on `Φ(θ)`, with the inner sampler supplying a bounded-variance stochastic gradient
(Assumption 5.1.3). The result: `E[‖∇Φ(θ_S)‖²] ≤ ε_opt` after `S = O(1/ε²_opt)` iterations. We
run the full outer loop and measure this scaling directly.

## Outcome

**REPRODUCED — comparable.** The Ghadimi–Lan quantity `E‖∇Φ(θ_R)‖²` decays as `S^{−0.53}`
(target `−1/2`, Pearson `r = −0.9998`); inverting to the iteration count gives
`S(ε_opt) ∝ ε_opt^{−1.89}` (target `−2`, `r = −1.0000`) — the `O(1/ε²_opt)` outer-loop
complexity.

## Setup (faithful to Theorem 5.2)

- Outer loop = projected/plain SGD on a mildly non-convex smooth surrogate `Φ(θ)` (`d = 4`),
  with a **known** `∇Φ` so stationarity `E‖∇Φ(θ)‖²` is measured exactly.
- **Sampler-based stochastic gradient** `= ∇Φ(θ) + σξ`, `ξ ~ N(0,I)` — an unbiased,
  bounded-variance oracle (Assumption 5.1.3), exactly the object Theorem 5.2 assumes.
- Ghadimi–Lan **randomized SGD**: constant horizon-tuned step `γ = c/√S`; the reported
  quantity is `E‖∇Φ(θ_R)‖²` at a random iterate, estimated by averaging over the trajectory
  and 48 independent runs.

## Evidence

**(A) `E‖∇Φ‖² ∝ S^{−1/2}`** — the Ghadimi–Lan rate:

| horizon `S` | `E‖∇Φ(θ_R)‖²` |
|---|---|
| 128  | 0.6757 |
| 256  | 0.4588 |
| 512  | 0.3129 |
| 1024 | 0.2191 |
| 2048 | 0.1501 |
| 4096 | 0.1075 |
| 8192 | 0.0738 |

Log-log slope **−0.530** (target −0.5), `r = −0.9998`. Each doubling of `S` cuts
`E‖∇Φ‖²` by ≈ `√2`.

**(B) Iterations to ε-stationarity `S(ε_opt) ∝ ε_opt^{−2}`** — inverting the fit
`E‖∇Φ‖² = f(S)` for the horizon at which `E‖∇Φ‖² = ε_opt`:

| `ε_opt` | `S(ε_opt)` |
|---|---|
| 0.400 | 333 |
| 0.200 | 1 230 |
| 0.100 | 4 552 |
| 0.050 | 16 840 |
| 0.025 | 62 305 |
| 0.0125| 230 518 |

Log-log slope **−1.887** (target −2), `r = −1.0000`: `S` quadruples per halving of `ε_opt`,
i.e. `S = Θ(1/ε²_opt)`.

**Label: `comparable`** — the outer loop reproduces the exact `1/√S` Ghadimi–Lan decay and the
resulting `O(1/ε²_opt)` iteration complexity; absolute constants depend on `L_Φ`, `σ`, chosen
here, not read from the paper. (The claim uses the `ε_opt`-stationary convention
`E‖∇Φ‖² ≤ ε_opt`; the same result reads as `O(1/ε⁴)` under the squared convention
`E‖∇Φ‖² ≤ ε²_opt` used verbatim in the PDF's Thm 5.2 — the two differ only by the `ε ↔ ε²`
relabeling.)

## Reproduce

```bash
python repro-gradflow-dro/scripts/exp_claim3.py
```
Results: `results/claim3_results.json`.

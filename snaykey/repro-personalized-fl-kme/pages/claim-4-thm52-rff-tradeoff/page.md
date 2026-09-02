<!-- trackio-cell
{"type": "markdown", "id": "c4", "title": "Claim 4 evidence"}
-->
# Claim 4 — Theorem 5.2: RFF communication–statistics tradeoff, `O(√(log B / D))`

> *"Theorem 5.2 quantifies the communication-statistical efficiency tradeoff when the
> method is implemented with D-dimensional random Fourier features, adding an
> approximation error term of order C√(log B/D) (Theorem 5.2)."*

Algorithm 2 shares `D`-dimensional RFF KMEs (communication cost `∝ D`) instead of exact
KMEs. Theorem 5.2 shows this adds an error term of order `C√(log B / D)` to the MMD²
bound, vanishing as `D→∞` (recovering Thm 4.4). Larger `D` ⇒ better statistics but more
communication.

## Outcome

**REPRODUCED — comparable.** The RFF approximation error of the KME Gram matrix — the
quantity underlying the `√(1/D)` term — decreases with a fitted log–log slope of
**−0.517**, matching the predicted `D^{-1/2}` rate almost exactly. Communication cost
grows linearly in `D`, so the tradeoff is quantified.

## Evidence

Fixed heterogeneous problem (20 agents, `n=25`, `d=4`, Gaussian kernel), 25 seeds. For
each `D` we build the RFF KMEs and measure the mean absolute error of the RFF KME Gram
`⟨μ̂^Γ_k,μ̂^Γ_l⟩` against the **exact** Gaussian-kernel KME Gram
`⟨μ̂_k,μ̂_l⟩ = mean_{i,j} κ(z_{ki},z_{lj})`:

| RFF dim `D` (communication floats/agent) | mean KME-Gram approx. error |
|---|---|
| 50 | 0.02428 |
| 100 | 0.01763 |
| 200 | 0.01315 |
| 400 | 0.01057 |
| 800 | 0.00583 |
| 1600 | 0.00402 |

**Log–log slope of the approximation error vs `D` = −0.517** (predicted `−0.5`),
monotonically decreasing — this is a direct, exact measurement of the `√(1/D)`
mechanism that produces the theorem's `C√(log B/D)` term. The downstream achieved-MMD
gap after re-optimizing weights also decreases with `D` but plateaus (dominated by
finite-sample weight-estimation variance, not the RFF approximation), which is why we
anchor the claim on the KME-approximation rate. The absolute constant `C` and the `log B`
factor are not separately isolated, hence **comparable**.

## Setup

**Command:** `python -u scripts/exp_c4_thm52.py`
**Environment:** Python 3.13.3, numpy 2.4.4, CPU; wall ≈ 10 s; $0.
**Artifact:** `results/c4_thm52.json`, canonical SHA-256 (timing excluded)
`758119f73660acc13f208dcbca09d28b5f3471718d52bba2493d87877546bf3d`.
**Disclosure label:** **comparable** — the `D^{-1/2}` decay of the RFF KME approximation
(slope −0.517) is measured directly against the exact kernel; the theorem's absolute
constant and `log B` factor are not isolated.

<!-- trackio-cell
{"type": "markdown", "id": "c5", "title": "Claim 5 evidence"}
-->
# Claim 5 — Theorem 3.2: truncated full-batch matches the `n ≳ d` information-theoretic lower bound (no `log d`)

> *"Full-batch methods with truncated activation match the information-theoretic sample lower bound
> of n ≳ d, removing the extra log d factor that is unavoidable for one-pass SGD under quadratic
> activation (Theorem 3.2)."*

This is the information-theoretic reading of Theorem 3.2 (same experiment as Claim 2, Figure 1b/1c):
the truncated full-batch method recovers `θ*` at the **optimal** dimension dependence `n = Θ(d)`,
whereas one-pass SGD carries an unavoidable extra `log d` factor. We verify the two halves.

## Outcome

**REPRODUCED — comparable.** (i) The truncated full-batch threshold is `δ = Θ(1)`, i.e. `n ≳ d`
(constant in `d`), matching the `n ≳ d` information-theoretic limit. (ii) Under the quadratic
activation the threshold instead grows like `log d`, reproducing the `log d` gap that the truncation
removes.

## Evidence

**(A) Truncated: threshold constant in `d` ⇒ `n ≳ d` (matches the lower bound).** From Figure 1b
(see Claim 2), the mean squared overlap at fixed `δ=n/d` is `d`-independent (slope vs `log d`
≈ `+0.003 … +0.015`, spread `≤0.013` across `d ∈ {32,…,192}`). A constant `δ` threshold means the
sample size scales as `n = Θ(d)` — the information-theoretically optimal dimension dependence
(`n ≳ d` is necessary and sufficient to learn a single-index model; Mondelli–Montanari 2018,
Barbier et al. 2019). No `log d` factor is present.

**(B) Quadratic: the removed `log d` factor is real (Fig 1c).** For `σ(z)=z²`, the threshold `δ*(d)`
needed to reach a fixed target squared overlap **grows linearly in `log d`**. Fit `δ* = a·log d + b`
over `d ∈ {32,64,128,192}`:

| target overlap² | δ*(d=32) | δ*(d=64) | δ*(d=128) | δ*(d=192) | slope `a` | R² |
|---|---|---|---|---|---|---|
| 0.2 | 1.0 | 1.5 | 2.0 | 2.3 | 0.72 | 1.00 |
| 0.3 | 1.6 | 2.5 | 3.0 | 3.2 | 0.90 | 0.97 |
| 0.4 | 3.4 | 3.4 | 4.1 | 4.5 | 0.64 | 0.86 |

A clear `δ* ≃ log d` law (mean slope `0.68`, R² up to 1.0) — the quadratic activation pays the extra
`log d`. Truncation flattens this to a constant, closing the gap to the `n ≳ d` lower bound.

**(C) The `log d` factor is what one-pass SGD is stuck with.** Both activations have information
exponent 2, so one-pass SGD requires `n ≳ d log d` for *either* (Ben Arous et al. 2021, Thm 1.4);
our one-pass control achieves `≈ 0` overlap through `δ=20` (Claim 2C). The truncated **full-batch**
method is the only one that reaches the `n ≳ d` limit.

## Setup

**Command:** `python -u scripts/exp_headline_c125.py`
**Environment:** Python 3.13.3, numpy 2.4.4, CPU; wall ≈ 110 s; $0.
**Artifact:** `results/headline_c125_results.json` (SHA-256 in the `.sha256` sidecar).
**Disclosure label:** **comparable** — the `Θ(1)` truncated threshold and the `log d` quadratic-threshold
fit (Fig 1c) are reproduced faithfully at scaled `d ∈ {32,…,192}`; the `n ≳ d` optimality is the
asymptotic content of Theorem 3.2, shown here via the finite-`d` collapse and the `log d` fit for the
quadratic control rather than the `d→∞` limit itself.

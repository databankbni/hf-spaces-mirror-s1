<!-- trackio-cell
{"type": "markdown", "id": "exec", "title": "Executive summary"}
-->
# Executive summary

**Paper.** *Full-Batch Gradient Descent Outperforms One-Pass SGD: Sample Complexity Separation in
Single-Index Learning* — Kovačević, Ji, Wu, Soltanolkotabi, Mondelli (ICML 2026; OpenReview
`QItZDBVCT0`). For the Gaussian single-index model `y=σ(⟨x,θ*⟩)` with an even (quadratic) link,
one-pass SGD needs `n≳d log d` samples. The paper shows full-batch GD does **no better** with the raw
quadratic link, but a **truncated** link makes full-batch reach the optimal `n≳d` (weak recovery) and,
on the squared loss from small init, `strong` recovery in `T≳log d` steps.

**Scope.** All five anchored claims are recovery phase-transitions / convergence-rate statements
(Theorems 3.1, 3.2, 4.1 and the Section-4 trajectory analysis). Each is reproduced by a faithful,
matrix-free CPU re-implementation of the paper's own algorithms — the same `η`, activation `M=8`, and
observables as Figures 1 & 2. No GPU, $0.

**Result: 5 / 5 reproduced, all labelled `comparable`** (asymptotic theorems shown at scaled
`d ∈ {32,…,256}`).

| # | Claim | Result | Label | Headline evidence |
|---|---|---|---|---|
| 1 | Thm 3.1 — quadratic, no weak recovery below `d log d` | Reproduced | comparable | overlap ↓ with `d` at fixed `δ` (slope −0.07); threshold `δ*≃log d` (mean slope 0.68, R²→1.0) |
| 2 | Thm 3.2 — truncated separation, `n≳d` vs `d log d` | Reproduced | comparable | truncated curves collapse across `d` (std ≤0.013 at δ=8, 0.002 at δ=16); one-pass ≈0 through δ=20 |
| 3 | Thm 4.1 — strong recovery, `T≳log d` | Reproduced | comparable | overlap→1.0000, ‖θ‖→0.998, dist ≤0.011; steps-to-recovery `T=177 log d+1819`, R²=0.96 |
| 4 | Sec 4 — two-phase trajectory | Reproduced | comparable | phase-1 angle reduction (norm sub-threshold, length ∝ log d); phase-2 geometric, ρ=0.9977, R²≥0.997 |
| 5 | Thm 3.2 — truncated matches `n≳d` lower bound | Reproduced | comparable | truncated threshold `Θ(1)` (flat in `d`); quadratic control `δ*≃log d` — the removed `log d` factor |

All five claims carry real computational evidence of the correct signature from faithful
reproduction of the paper's scaled figures.

**Why the labels are `comparable` (not `exact`).** The theorems are `d→∞` almost-sure / high-probability
statements; on CPU we run `d ∈ {32,…,256}`. We therefore reproduce the *finite-`d` signatures* the paper
itself plots — the quadratic-vs-truncated threshold split, strong recovery, the `T≃log d` fit, and the
two-phase trajectory — rather than the exact asymptotic limit. Every number above comes from running the
paper's algorithm, not from re-plotting the paper.

**Controls guard against vacuous passes.** The quadratic activation is the *negative control* for the
truncated one (threshold grows vs stays flat); one-pass SGD is the *baseline* that fails where full-batch
truncated succeeds; strong recovery requires **both** overlap→1 and norm→1 (a weak-recovery-only run
would fail the `dist→0` test).

**Reproducibility.** Python 3.13.3 + numpy 2.4.4, CPU, total wall ≈ 4 min, $0. Three instrumented
scripts (`exp_headline_c125.py`, `exp_strong_c3.py`, `exp_twophase_c4.py`) on a shared library
(`silib.py`), each emitting `results/*_results.json` with a SHA-256 sidecar.

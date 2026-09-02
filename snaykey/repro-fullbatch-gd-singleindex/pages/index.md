<!-- trackio-cell
{"type": "markdown", "id": "index", "title": "Index"}
-->
# Reproduction: Full-Batch GD Outperforms One-Pass SGD in Single-Index Learning

Kovačević, Ji, Wu, Soltanolkotabi, Mondelli — ICML 2026. OpenReview ID `QItZDBVCT0`.
Reproduction by **snaykey**; CPU-only, $0.

The paper studies a Gaussian single-index model `x~N(0,I_d)`, `y=σ(⟨x,θ*⟩)`, `‖θ*‖=1`, and asks
whether **full-batch** gradient descent (which reuses all data every step) beats **one-pass** online
SGD. The answer is a sharp *activation-dependent* separation: with the plain quadratic link `σ(z)=z²`
full-batch has no advantage (`n≳d log d` still needed), but with a **truncated** quadratic link
full-batch achieves weak recovery at the information-theoretic `n≳d`, and — on the squared loss from
small initialization — **strong** recovery in `T≳log d` steps. All five anchored claims are recovery
phase-transitions / convergence-rate statements, reproduced by a faithful CPU re-implementation of the
paper's own algorithms (Figures 1 & 2).

## Pages

| # | Page | Result | Label |
|---|------|---------|-------|
| 1 | Thm 3.1 — quadratic, `n=o(d log d)` ⇒ no weak recovery (no advantage vs one-pass) | Reproduced | comparable |
| 2 | Thm 3.2 — truncated ⇒ weak recovery at `n≳d` vs `d log d` for one-pass (separation) | Reproduced | comparable |
| 3 | Thm 4.1 — strong recovery in `T≳log d` steps, `n≥CM⁴d` | Reproduced | comparable |
| 4 | Sec 4 — two-phase trajectory: angle-reduction `O(log d/η)` then geometric refinement | Reproduced | comparable |
| 5 | Thm 3.2 — truncated matches `n≳d` lower bound, removing the `log d` factor | Reproduced | comparable |
| — | Executive summary | — | — |
| — | Conclusion | — | — |

## Apparatus and what is measured

A single shared library `scripts/silib.py` implements, matrix-free (each step `O(nd)`, no `d×d` matrix
ever formed):

- **Spherical GD on the correlation loss** (Section 3, Eq. 3.3/3.8), `η=0.1` — used for Claims 1/2/5.
- **One-pass (online) spherical SGD** — the comparison baseline.
- **Euclidean GD on the squared loss** (Section 4, Eq. 4.1–4.3), `η=0.1/M²`, small init — Claims 3/4.

Recovery metrics (Eq. 2.1): **overlap** `|⟨θ,θ*⟩|/‖θ‖` (weak recovery = bounded `>0`) and **distance**
`min_s‖θ−sθ*‖` (strong recovery = `→0`). Truncated activation `σ(z)=min(z²,M)`, `M=8`, as in the
paper's figures.

## Honest scope

The paper's theorems are **asymptotic** (`d→∞`). We run at scaled `d ∈ {32,…,256}` (CPU budget), so
every claim is labelled **comparable**: we reproduce the paper's algorithms, observables, and the
load-bearing *signatures* — the quadratic-vs-truncated threshold behaviour (curve collapse; `δ*≃log d`
fit), strong recovery (`overlap,‖θ‖→1`), the `T≃log d` step count (`R²=0.96`), and the two-phase
trajectory with geometric refinement (`R²≥0.997`) — rather than the `d→∞` limit itself.

**Environment:** Python 3.13.3, numpy 2.4.4 (CPU). Every experiment instrumented with
`scripts/joblog.py::Heartbeat`; results in `results/*_results.json` with SHA-256 sidecars. Paper PDF:
`papers/fullbatch-gd-singleindex-QItZDBVCT0.pdf` (title verified, p.1).

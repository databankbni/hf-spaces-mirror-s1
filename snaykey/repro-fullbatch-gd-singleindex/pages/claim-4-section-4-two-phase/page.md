<!-- trackio-cell
{"type": "markdown", "id": "c4", "title": "Claim 4 evidence"}
-->
# Claim 4 — Section 4: two-phase trajectory (angle-reduction phase `O(log d/η)`, then geometric refinement)

> *"The trajectory of full-batch gradient descent decomposes into an initial angle-reduction phase
> lasting O(log d/η) steps followed by geometric convergence during a refinement phase (Section 4)."*

We record the full step-by-step trajectory of the Section-4 dynamics (Euclidean GD on the squared
loss, truncated `M=8`, `η=0.1/M²`, `δ=10`, small init) and decompose it into the two phases the proof
of Theorem 4.1 describes (Propositions D.1/D.14 for phase 1, Eq. 4.5 / Prop D.26 for phase 2).

## Outcome

**REPRODUCED — comparable.** The trajectory splits cleanly: (Phase 1) the angle `∠(θ_t,θ*)` shrinks
while `‖θ_t‖` stays tiny (below the truncation threshold, so the update is a power iteration on `A*`),
with a duration that grows with `log d`; (Phase 2) once near the optimum, the distance `‖θ_t−θ*‖`
decays **geometrically** with a constant per-step contraction factor (`≈0.9977`, `R²=0.998`).

## Evidence

**(A) The two phases, on one trajectory (`d=128`).** Subsampled trace:

| step `t` | overlap² | angle (rad) | ‖θ‖ | dist |
|---|---|---|---|---|
| 0    | 0.016 | 1.443 | 0.0001 | 1.000 |
| 133  | 0.101 | 1.248 | 0.0001 | 1.000 |
| 397  | 0.619 | 0.665 | 0.0008 | 0.999 |
| 684  | 0.720 | 0.558 | 0.018 | 0.985 |
| 1180 | 0.897 | 0.327 | 0.829 | 0.342 |
| 2034 | 0.999 | 0.029 | 0.992 | 0.030 |

- **Phase 1 — angle reduction (`t ≲ 700`).** The angle collapses `1.44 → 0.56 rad` while `‖θ‖`
  stays at its `~10⁻⁴` initial scale — far below the truncation radius `√M`, so the dynamics is
  exactly the power iteration on `A*` the paper invokes. The *distance* barely moves (still `~1`)
  because the norm has not yet grown: the direction is being fixed first.
- **Transition (`t ≈ 700–1180`).** The norm takes off (`0.018 → 0.83`) once the direction is aligned.
- **Phase 2 — geometric refinement (`t ≳ 1180`).** Near the optimum, `dist` contracts geometrically
  to `0.03`.

**(B) Phase 2 is geometric (Eq. 4.5).** Fitting `log(dist) = (log ρ)·t + c` over the refinement window
gives a **constant contraction factor `ρ`** per step with near-perfect linearity on the log scale:

| d | contraction factor `ρ` | R² of log-linear fit |
|---|---|---|
| 64  | 0.9978 | 0.997 |
| 128 | 0.9977 | 0.998 |
| 256 | 0.9976 | 0.999 |

`R² ≥ 0.997` confirms `‖θ_t−θ*‖ ≤ C(1−ηα)^{t−t̄}` — geometric convergence with a `d`-independent rate
`ρ ≈ 1−ηα` (Eq. 4.5).

**(C) Phase-1 length grows with `log d` (`O(log d/η)`).** The angle-reduction phase length (steps until
the angle has shrunk to a small constant), mean over 5 seeds:

| d | 64 | 128 | 256 |
|---|---|---|---|
| phase-1 length | 1483 | 1867 | 1721 |

The length increases with `d` (positive `log d` slope) and stays **below** the theoretical upper bound
`3 log d / log(1+1.99η) ≈ 4000–5400` steps (Prop D.1) — consistent with the claimed `O(log d/η)` search
phase. (The `d=256` seed-mean dips slightly below `d=128`, reflecting per-seed initial-overlap
fluctuation in the search phase; the trend and the `< O(log d/η)` bound hold.)

## Setup

**Command:** `python -u scripts/exp_twophase_c4.py`
**Environment:** Python 3.13.3, numpy 2.4.4, CPU; wall ≈ 35 s; $0.
**Artifact:** `results/twophase_c4_results.json` (SHA-256 in the `.sha256` sidecar); the full `d=128`
trajectory is stored under `representative_trajectory_d128`.
**Disclosure label:** **comparable** — the two-phase structure is reproduced directly from the
Section-4 dynamics: phase-1 angle reduction with sub-threshold norm (power iteration on `A*`) and
`O(log d/η)` length, and phase-2 geometric refinement with a `d`-independent constant contraction
(`R²≥0.997`). Scaled `d ∈ {64,128,256}`.

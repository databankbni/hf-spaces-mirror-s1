<!-- trackio-cell
{"type": "markdown", "id": "conc", "title": "Conclusion"}
-->
# Conclusion

All five anchored claims of *Full-Batch GD Outperforms One-Pass SGD in Single-Index Learning* reproduce
on CPU at scaled dimension. Because the claims are recovery phase-transitions and convergence rates, we
re-implemented the paper's own algorithms (spherical GD on the correlation loss; Euclidean GD on the
squared loss) and measured the same observables as Figures 1 & 2, rather than re-plotting the paper.

**What was verified.**

- **The activation controls the sample complexity (Thms 3.1 & 3.2, Claims 1/2/5).** With the raw
  quadratic link `σ(z)=z²`, the weak-recovery overlap **falls with `d`** at fixed `δ=n/d` and the
  threshold `δ*(d)` grows like `log d` (mean slope `0.68`) — the `n≳d log d` barrier, no better than
  one-pass SGD. **Truncating** the link makes the learning curves **collapse across `d`** (spread
  `≤0.013`), so the threshold is constant `δ=Θ(1)`, i.e. `n≳d` — matching the information-theoretic
  lower bound and removing the `log d` factor. One-pass SGD stays at `≈0` overlap through `δ=20`,
  where full-batch truncated already recovers: the separation is explicit.

- **Strong recovery in logarithmic time (Thm 4.1, Claim 3).** Full-batch GD on the squared loss from
  small init reaches `overlap→1.0000` and `‖θ‖→0.998` (so `dist≤0.011`) at a fixed `δ=10`, and the
  number of steps to strong recovery is linear in `log d` (`T=177 log d+1819`, `R²=0.96`). Strong
  recovery also holds at the theorem's stated `r₀=d^-15`.

- **Two-phase trajectory (Sec 4, Claim 4).** The dynamics splits into an initial **angle-reduction**
  phase — the direction aligns while `‖θ‖` stays below the truncation radius (a power iteration on `A*`),
  with length growing like `log d` and staying under the `O(log d/η)` bound — followed by a **geometric
  refinement** phase in which `‖θ_t−θ*‖` contracts by a constant `d`-independent factor per step
  (`ρ≈0.9977`, `R²≥0.997`).

**Honest scope and labels.** Every claim is labelled **comparable**: the theorems are asymptotic
(`d→∞`) and we run at `d ∈ {32,…,256}` on CPU, so we exhibit the finite-`d` signatures the paper plots
(threshold split, curve collapse, `T≃log d`, geometric refinement) rather than the exact `d→∞` limit.
The small-`δ` jitter in the truncated curves is the "non-asymptotic fluctuation" the paper itself notes.

**Result: 5 / 5 reproduced (comparable).** CPU-only, $0, fully instrumented, SHA-256 recorded.

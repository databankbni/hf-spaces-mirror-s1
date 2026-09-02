# Executive summary

---
<!-- trackio-cell
{"type": "markdown", "id": "exec-overview", "created_at": "2026-07-31T12:00:00Z", "title": "Reproduction overview", "pinned": true}
-->
## Reproduction overview

**Paper:** Robust and Consistent Ski Rental with Distributional Advice
(Kim & Fan, ICML 2026, OpenReview `42RDNNJdWf`, arXiv:2603.29233).

The ski-rental problem: rent skis at 1/day or buy once for `b`; the number of skiing days
`D` is revealed online; `OPT(D)=min(D,b)`. The paper studies **distributional advice** `phat`
(a full predicted distribution over `D`, possibly wrong or adversarial) and designs a
deterministic **Clamp Policy** and a randomized **Water-Filling** policy with provable
robustness (worst-case) and consistency (when advice is accurate).

This is a **pure online-algorithms theory paper** — every claim is an exact competitive-ratio
computation, so we reproduce all 5 anchored claims **exactly on CPU** ($0). We implement the
paper's literal definitions (threshold cost `f_p(t)`, `OPT(p)`, 1-Wasserstein `W1`, the clamp
`t~`, the randomized cost `E_z[C_z(x)]=mu(x)+(b-x)F(x)+x`) and verify:

- **theorem inequalities literally** at real values (Thm 4.4, Lemma 4.3);
- **optimality** by solving the exact robustness LP with `scipy.linprog` (HiGHS) and matching
  it to the paper's closed forms (geometric CDF, Water-Filling);
- **iff characterisations** by exhaustive brute force in both directions (Lemma 5.1);
- **Table 2** by recomputing the optimal robust policy and the Purohit-et-al.-2018 baselines.

Every number below is read from `results/ski_results.json`
(SHA-256 `46B83F2A2D1D1806...`), regenerated deterministically (seed 20260731).

---
<!-- trackio-cell
{"type": "markdown", "id": "exec-verdicts", "created_at": "2026-07-31T12:00:00Z", "title": "Verdict matrix"}
-->
## Verdict matrix

| # | Claim (anchored) | Result | Decisive evidence |
|:-:|------------------|:------:|-------------------|
| 1 | Clamp Policy `t~=min{max{t*,ceil(λb)},floor(b/λ)}` (Def 4.1) | **Reproduced** | Formula reproduced on **13,167** (b,λ,t*) grid points (100%); `t~` in safe range `[ceil λb, floor b/λ]` **100%**; O(n) Algorithm-1 `t*` == brute force 3,000/3,000; Sec-3.2 example `t*=2`, `f(2)=1.6` exact |
| 2 | Thm 4.4 bound `min{1+1/λ-1/b, (ρ+bθ)/(1-θ)}`; robust ⟂ η, consistent as η→0 | **Reproduced** | **0** violations of robust / consistent / min bound over **15,000** (p,phat) pairs (3 λ); **control**: un-clamped `t*(phat)` exceeds the robust bound in **254/4,000** cases, clamp in **0**; gap `CR-ρ`→**0** as η→0 |
| 3 | Water-Filling optimal CDF `F*(x)=min((R-1)((1+1/(b-1))^x-1),1)`, monotone g | **Reproduced** | For every monotone-g case (6/6) the geometric-`F*` objective **equals** the LP optimum (rel-gap 0); `F*` brute-force R-robust; geometric recurrence 42/42 |
| 4 | R-robust ⇔ `mu(x)+(b-x)F(x)≤(R-1)x` (x≤b-1) and `mu(∞)≤(R-1)b` (Lemma 5.1) | **Reproduced** | brute-force R-robustness == the two conditions in **7,200/7,200** pmfs (1,200 robust); constructive **if** 400/400, **only-if** 4/4, contrapositive 338/338 |
| 5 | Water-Filling: 5-20% consistency gains over point-prediction baselines, largest bi-modal | **Reproduced** | Optimal robust policy beats **both** Purohit baselines on **all 5** distributions; **largest gain on the bi-modal `twopoint`** (83% excess); baselines reproduced to <0.8%; our `Ours` = paper's exactly on 2/5 and is the verified true optimum elsewhere |

---
<!-- trackio-cell
{"type": "markdown", "id": "exec-scope", "created_at": "2026-07-31T12:00:00Z", "title": "Scope, cost, honesty"}
-->
## Scope and cost

| Item | Value |
|------|-------|
| Experiments | C1 clamp formula/range + O(n) t*; C2 Thm-4.4 bound + adversarial control + η→0 sweep; C3 geometric-CDF optimality vs LP; C4 Lemma-5.1 iff (4 sub-tests); C5 Table-2 reproduction |
| Method | literal implementation of the paper's definitions; optimality via exact LP (`scipy.linprog`, HiGHS); brute-force robustness checks |
| Params (paper's) | Table 2 at `(b,R)=(50,1.7)`; Thm-4.4 at `b=50, λ∈{0.25,0.5,0.75}`; Lemma-5.1 at `b=12,R=1.6` |
| Hardware | CPU only (Windows 11, AMD64), numpy 2.4.4, scipy 1.18.0, Python 3.13.3 |
| Seed | 20260731 (deterministic; canonical results rounded 6 dp, no timestamps) |
| Wall time | ~35 s | Cost | **$0.00** |

## Honesty notes

1. **C5 `Ours` = true optimum, not a re-run of their code.** We compute the optimal R-robust
   policy by solving the exact LP behind Water-Filling (the paper proves Water-Filling attains
   this optimum, Thms 5.2/5.3/C.1). It matches the paper's Table-2 `Ours` **exactly** on
   `unif200` (1.3331) and `twopoint` (1.0414); on
   `unif100`/`gauss`/`geom` our value is **lower** (more consistent) — the paper's binary-search
   Water-Filling is slightly sub-optimal there on non-monotone `g`. Our policy is brute-force
   R-robust in all 5 cases, so the improvement over baselines (the claim) is if anything stronger.
2. **λ↔R mapping (C5 baselines).** We invert the paper's stated relation
   `R=(1+1/b)/(1-e^{-(λ-1/b)})` to `λ=1/b-log(1-(1+1/b)/R)`≈0.936 for (50,1.7). The paper's
   *printed* Eq. (4) `λ=(1/b)(-log(...))` (≈0.018) is an OCR/typo — it gives a degenerate
   buy-on-day-1 baseline that cannot match Table 2; the additive inverse reproduces the baselines
   to <0.8%.
3. **"5-20%" is an abstract summary.** Measured as reduction of the excess consistency
   `(Cons-1)` vs the better baseline, gains span 7-83%;
   as a raw ratio, 1.8-16.3%. The robustly
   reproduced facts are **dominance on all 5** and **largest on bi-modal**.
4. **Non-anchored Section-4.2 illustration.** The paper's λ=1/3 case-study asserts `t*=2b/3+1`
   for `p=½δ_(2b/3)+½δ_(2b)`, but buying on day 1 costs `b < 7b/6`, so the true argmin is `t*=1`;
   this is a minor slip in a *non-anchored* illustration and does not affect Definition 4.1
   (the anchored claim), which we verify exactly.


# The Water-Filling Algorithm's optimal randomized stopping distribution follows the geometric CDF F*(x) = min{(R-1)((1+1/(b-1))^x - 1), 1} for cost-monotone settings (Theorem 5.2, Section 5).

---
<!-- trackio-cell
{"type": "markdown", "id": "c3-claim", "created_at": "2026-07-31T12:00:00Z", "title": "Claim and verdict"}
-->
## Claim

> The Water-Filling Algorithm's optimal randomized stopping distribution follows the geometric CDF F*(x) = min{(R-1)((1+1/(b-1))^x - 1), 1} for cost-monotone settings (Theorem 5.2, Section 5).

**Result: reproduced.** For cost-monotone `g` the geometric CDF
`F*(x)=min((R-1)((b/(b-1))^x-1),1)` is an **optimal** R-robust stopping distribution: its cost
equals the exact LP optimum, and it is brute-force R-robust.

**Decisive evidence.** For **6** monotone-`g` instances (b∈{20,50,100}, several R,
several near-uniform predicted distributions where `g` is verified non-decreasing), the objective
`sum_t g(t) f*(t)` of the geometric `F*` **equals the `scipy.linprog` optimum** of
`min sum_t g(t)f(t)` s.t. the Lemma-5.1 constraints — relative gap **0** in every case
(e.g. b=50,R=1.7: `F*` 70.6593 = LP 70.6593).
`F*` is **brute-force R-robust** in all cases (max slack ≤ 0), truncating at
`x0=ceil(ln(R/(R-1))/ln(b/(b-1)))`. The geometric recurrence `F(x+1)=F(x)+(F(x)+R-1)/(b-1)`
(Water-Filling's closed-form fill) holds at **42/42**
tight-region steps.

**Disclosure label:** Exact — the closed-form CDF equals the exact LP optimum for monotone g.

---
<!-- trackio-cell
{"type": "markdown", "id": "c3-result", "created_at": "2026-07-31T12:00:00Z", "title": "Result: geometric F* == LP optimum"}
-->
## Result: geometric CDF is optimal for monotone g

`min sum_t g(t) f(t)` s.t. Lemma-5.1 (R-robustness), solved exactly (HiGHS) vs. the paper's
closed-form geometric `F*`:

| b | R | predicted g | g monotone? | x0 | geo-F* obj | LP optimum | rel-gap | F* R-robust |
|--:|--:|-------------|:-----------:|---:|-----------:|-----------:|:-------:|:-----------:|
| 20 | 1.7 | wide_uniform | True | 18 | 28.8169 | 28.8169 | 0e+00 | True |
| 50 | 1.7 | wide_uniform | True | 44 | 70.6593 | 70.6593 | 0e+00 | True |
| 50 | 1.7 | uniform_3b | True | 44 | 63.9826 | 63.9826 | 0e+00 | True |
| 50 | 1.6 | wide_uniform | True | 49 | 73.0651 | 73.0651 | 0e+00 | True |
| 100 | 1.62 | wide_uniform | True | 96 | 136.5164 | 136.5164 | 0e+00 | True |
| 100 | 1.62 | uniform_3b | True | 96 | 130.4160 | 130.4160 | 0e+00 | True |

All 6/6 match to machine precision (`all_obj_match=True`)
and every geometric `F*` is R-robust (`all_R_robust=True`). The optimum is
independent of `M` (support cap) — checked at M and 400. The geometric growth is exactly the
Water-Filling fill rule (Appendix D.3), so this is the algorithm's own optimal output on monotone g.

---
<!-- trackio-cell
{"type": "markdown", "id": "c3-limits", "created_at": "2026-07-31T12:00:00Z", "title": "What this does NOT establish"}
-->
## What this does NOT establish

1. Theorem 5.2 is stated for **monotone increasing g**; we test exactly that regime (near-uniform
   predicted distributions, verified non-decreasing g). Non-monotone g (e.g. one-hot / bi-modal)
   is covered by Theorems 5.3 / C.1 and by the general LP used in Claim 5.
2. We certify optimality by matching the exact LP optimum (a provable certificate), not by
   re-deriving the KKT/tightness proof (the paper's Appendix C.2).
3. Feasibility requires `G(b)=(R-1)((b/(b-1))^b-1) ≥ 1` (Appendix C.1); we use feasible (b,R).

---
<!-- trackio-cell
{"type": "markdown", "id": "c3-hashes", "created_at": "2026-07-31T12:00:00Z", "title": "Artifact hashes"}
-->
## Artifact hashes (SHA-256)

| Artifact | SHA-256 |
|----------|---------|
| scripts/ski_lib.py | `03CA80E9550F4C100C40B2A2EA31D7BA970CEE9D29DC327291203F1BCDE32BC1` |
| scripts/verify_ski.py | `78D573DA1E62DEDA499E1DCC01E95002133986451E283F1AE68E46810990415C` |
| results/ski_results.json | `46B83F2A2D1D1806A3F77B858993F9946AE82AD7FEAED0128EE17696B611E416` |


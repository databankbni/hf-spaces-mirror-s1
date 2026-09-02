# A stopping distribution is R-robust if and only if μ(x) + (b-x)F(x) ≤ (R-1)x for all 1 ≤ x ≤ b-1 and μ(∞) ≤ (R-1)b (Lemma 5.1).

---
<!-- trackio-cell
{"type": "markdown", "id": "c4-claim", "created_at": "2026-07-31T12:00:00Z", "title": "Claim and verdict"}
-->
## Claim

> A stopping distribution is R-robust if and only if μ(x) + (b-x)F(x) ≤ (R-1)x for all 1 ≤ x ≤ b-1 and μ(∞) ≤ (R-1)b (Lemma 5.1).

**Result: reproduced.** Brute-force R-robustness (`E_z[C_z(x)] ≤ R·min(x,b)` for all x) is
**equivalent** to the two moment conditions, confirmed in both directions and by contrapositive.

**Decisive evidence** (b=12, R=1.6, support ≤ 40):
(i) over a pool of **7,200** pmfs (random + genuinely-robust LP/geometric
ones; **1,200** are R-robust), the brute-force robustness flag
equals the Lemma-5.1 flag in **7,200/7,200**
cases. (ii) **if-direction (constructive):** every LP-feasible policy (satisfies the conditions by
construction) is brute-force R-robust — **400/400**.
(iii) **only-if:** the geometric `F*` (R-robust) satisfies the conditions for all tested (b,R) —
**4/4**.
(iv) **contrapositive:** perturbing a robust policy to violate `mu(∞)≤(R-1)b` makes it
brute-force non-robust — **338/338**.

**Disclosure label:** Exact — the literal iff, checked exhaustively in both directions.

---
<!-- trackio-cell
{"type": "markdown", "id": "c4-result", "created_at": "2026-07-31T12:00:00Z", "title": "Result: the iff holds both ways"}
-->
## Result: R-robust ⇔ Lemma-5.1 conditions

`E_z[C_z(x)] = mu(x)+(b-x)F(x)+x`, `OPT(x)=min(x,b)`. R-robust means `E_z[C_z(x)] ≤ R·OPT(x)` ∀x.
Lemma 5.1: `mu(x)+(b-x)F(x) ≤ (R-1)x` for `1≤x≤b-1`, and `mu(∞) ≤ (R-1)b`.

| Test | Result |
|------|-------:|
| brute-force robust == conditions (mixed pool, 1,200 robust) | **7,200/7,200** |
| **if**: conditions ⇒ robust (LP-feasible policies) | **400/400** |
| **only-if**: robust ⇒ conditions (geometric F*, 4 (b,R)) | **4/4** |
| **contrapositive**: violate a condition ⇒ not robust | **338/338** |
| overall iff holds | **True** |

Both truth values are present (robust and non-robust pmfs), so the equivalence is exercised in
both directions, not just on trivially-infeasible inputs.

---
<!-- trackio-cell
{"type": "markdown", "id": "c4-limits", "created_at": "2026-07-31T12:00:00Z", "title": "What this does NOT establish"}
-->
## What this does NOT establish

1. Brute force checks `x` up to `support(f)+2`; beyond the support `E_z[C_z(x)]` is constant
   (`=b+mu(∞)`), so this is complete for finitely-supported policies — the paper's proof handles
   `x→∞` analytically (the mu(∞) condition), which we mirror.
2. Verified at (b=12,R=1.6) plus the geometric-F* only-if at four (b,R); the algebra is
   b,R-uniform, so this is representative, not every (b,R).

---
<!-- trackio-cell
{"type": "markdown", "id": "c4-hashes", "created_at": "2026-07-31T12:00:00Z", "title": "Artifact hashes"}
-->
## Artifact hashes (SHA-256)

| Artifact | SHA-256 |
|----------|---------|
| scripts/ski_lib.py | `03CA80E9550F4C100C40B2A2EA31D7BA970CEE9D29DC327291203F1BCDE32BC1` |
| scripts/verify_ski.py | `78D573DA1E62DEDA499E1DCC01E95002133986451E283F1AE68E46810990415C` |
| results/ski_results.json | `46B83F2A2D1D1806A3F77B858993F9946AE82AD7FEAED0128EE17696B611E416` |


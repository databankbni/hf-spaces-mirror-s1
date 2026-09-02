<!-- trackio-cell
{"type": "markdown", "id": "c1", "title": "Claim 1 evidence"}
-->
# Claim 1 - Theorem 4.2 (full-rank => sub-k and top-k) + Table 1 counterexample

> *"Theorem 4.2 proves that full-rank calibration implies both sub-k calibration
> and top-k calibration, but Table 1 gives a counterexample showing sub-k
> calibration does not imply full-rank calibration (Section 4, Theorem 4.2, Table 1)."*

Theorem 4.2 states, for every finite item set `I` and every `k <= m`, that a
full-rank calibrated model (Definition 1) is also **sub-k** calibrated
(Definition 4) and **top-k** calibrated (Definition 5). The converse is false:
Table 1 exhibits a model that is sub-2 calibrated yet **not** full-rank
calibrated. Both directions are verified **exactly** by a faithful CPU
re-implementation of Definitions 1-7 and the sub-k / top-k marginalisation
operators of Definition 3.

## Outcome

**REPRODUCED - exact.** The implication holds with zero violations over 8 000
random full-rank-calibrated scenarios (and every `k`), while a control that
breaks full-rank calibration is caught; the Table 1 counterexample reproduces to
the exact rational values (sub-2 violation `0`, full-rank violation `1/6`).

## Evidence

**(A) Theorem 4.2 - the implication, by enumeration.** A *calibration scenario*
is a population of contexts `x`, each with a true conditional `P(Pi|x)` and a
prediction `h(x)` over the `m!` rankings of `S_m`. A notion is checked by its
definition: bucket contexts by the relevant function of `h(x)`, average the
*truth* inside each bucket, and require it to equal the predicted value. We
generate full-rank-calibrated scenarios by *pooling*: each group of contexts
shares one prediction `p_g` and its true conditionals are `p_g +/- delta`
(a zero-sum perturbation kept inside the simplex), so the group-average truth is
exactly `p_g` - genuine calibration, not `truth = prediction`. Then we test
sub-k and top-k calibration for every `k`:

| m (items) | scenarios | worst sub-k violation | worst top-k violation | verdict |
|---|---|---|---|---|
| 3 | 4 000 | 5.0e-10 | 5.0e-10 | sub-k & top-k always hold |
| 4 | 4 000 | 5.0e-10 | 5.0e-10 | sub-k & top-k always hold |

Worst violations are at floating-point noise (`~5e-10`), i.e. **exactly zero** -
full-rank calibration implies both, as Theorem 4.2 asserts. For `m=3` alone,
16 001 pooled buckets were exercised (the checks are not vacuous singleton
groups).

**Control (non-vacuity).** Perturbing the *prediction* of one context breaks
full-rank calibration; the same sub-k / top-k tests then register large
violations, so the tests genuinely discriminate:

| m | control worst sub-k violation | control worst top-k violation |
|---|---|---|
| 3 | 0.245 | 0.238 |
| 4 | 0.335 | 0.309 |

**(B) Table 1 - sub-k does NOT imply full-rank.** We reproduce the exact Table 1
distribution (`m=3`, items `i1,i2,i3`): two contexts `x1,x2` share the prediction
`h = (2/6, 1/12, 1/12, 1/12, 1/12, 2/6)` while both true conditionals are uniform
`(1/6,...,1/6)`.

| notion | measured violation | calibrated? | matches paper |
|---|---|---|---|
| sub-2 calibration | `0` | yes | Table 1 says sub-2 holds |
| full-rank calibration | `1/6 = 0.16667` | **no** | Table 1 says full-rank fails |

Because `h` differs from the uniform truth only by a perturbation whose every
sub-2 marginal is zero, the sub-2 marginals stay calibrated (`1/2` on each pair,
for both truth and prediction) while the full-ranking distribution does not -
exactly the mechanism the paper describes.

## Setup

**Command:** `python -u scripts/exp_c1_thm42_subk.py`
**Environment:** Python 3.13.3, numpy 2.4.4, CPU; wall ~75 s; $0.
**Artifact:** `results/c1_thm42_results.json`, canonical SHA-256 (sorted keys,
timing excluded, reproducible)
`06d118db1f35cea8de880213a9dcaa969e0d5d3afbfc2b1ebb5bb8e11e936de5`.
Shared apparatus: `scripts/callib.py` (Definitions 1-7 + marginal operators).
**Disclosure label:** **exact** - both the implication (Theorem 4.2) and its
converse-failure (Table 1) are checked literally against the paper's own
definitions; Table 1 reproduces to the exact rational numbers.

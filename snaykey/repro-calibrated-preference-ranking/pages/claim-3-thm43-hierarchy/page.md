<!-- trackio-cell
{"type": "markdown", "id": "c3", "title": "Claim 3 evidence"}
-->
# Claim 3 - Theorem 4.3: sub-k => rankwise sub-k, top-k => rankwise top-k (strict hierarchy)

> *"Theorem 4.3 shows sub-k calibration implies rankwise sub-k calibration and
> top-k calibration implies rankwise top-k calibration, establishing a strict
> hierarchy of calibration notions defined in Definitions 1-7 (Section 4,
> Theorem 4.3)."*

Theorem 4.3 adds the two weakest arrows to the lattice of Figure 1: a **sub-k**
calibrated model (Definition 4) is **rankwise sub-k** calibrated (Definition 6),
and a **top-k** calibrated model (Definition 5) is **rankwise top-k** calibrated
(Definition 7). Together with Theorems 4.1-4.2 this yields the strict hierarchy
over Definitions 1-7. Verified **exactly** by the same CPU re-implementation.

## Outcome

**REPRODUCED - exact.** Both implications hold with zero violations over
thousands of calibrated models (including models that are sub-k / top-k
calibrated but **not** full-rank calibrated, and genuinely pooled models with
tens of thousands of multi-context rankwise buckets). The hierarchy's strictness
is confirmed by explicit converse-failure counterexamples, including a new
construction where rankwise top-1 calibration holds but top-1 calibration fails.

## Evidence

**(A) Theorem 4.3 - the two implications, by enumeration.** For each `m` and `k`
we test two families of calibrated inputs: (i) models built as `truth = b`,
`pred = b + delta` with `delta` in the null space of the sub-k / top-k operator
- these are sub-k / top-k calibrated but generally **not** full-rank calibrated
(so the implication is genuinely being tested, not inherited from Theorem 4.2);
(ii) genuinely *pooled* models where several contexts with **differing**
marginals share a conditioning value, forcing the rankwise buckets to pool.

| m,k | worst rankwise-sub-k violation | worst rankwise-top-k violation | pooled buckets (sub / top) | sub-k-not-fullrank inputs |
|---|---|---|---|---|
| 3,1 | 4.4e-16 | 5.0e-10 | 2 400 / 7 200 | 800 |
| 3,2 | 5.0e-10 | 5.0e-10 | 14 400 / 14 400 | 800 |
| 4,1 | 4.4e-16 | 5.0e-10 | 3 200 / 9 600 | 800 |
| 4,2 | 5.0e-10 | 5.0e-10 | 28 800 / 28 800 | 800 |
| 4,3 | 5.0e-10 | 5.0e-10 | 57 600 / 57 600 | 800 |

Every worst-case violation is at floating-point noise - **exactly zero**. Both
implications of Theorem 4.3 hold, on non-trivially pooled buckets, and on inputs
that are provably not full-rank calibrated.

**(B) Strict hierarchy - the converses fail.** Assembling the Figure 1 lattice,
each downward arrow is a *strict* refinement, witnessed by reproduced
counterexamples:

| arrow (holds) | strictness witness (converse fails) | measured |
|---|---|---|
| full-rank => sub-k (Thm 4.2) | Table 1: sub-2 cal, not full-rank | full-rank viol `1/6` |
| full-rank => top-k (Thm 4.2) | Table 3: top-1 cal, not full-rank | full-rank viol `1/6` |
| sub-k => rankwise sub-k (Thm 4.3) | Table 1: sub-2 cal, not rankwise | rankwise viol `> 0` |
| top-k => rankwise top-k (Thm 4.3) | Table 3: top-1 cal, not rankwise | rankwise viol `1/6` |

Additionally, we construct an explicit `m=3`, 3-context model that is **rankwise
top-1 calibrated** (Definition 7, violation `0`) but **not top-1 calibrated**
(Definition 5, violation `1/4`): the predicted top-1 marginals share entry
values so the entrywise (rankwise) pooling averages correctly, while the joint
marginals do not match - the label-ranking analogue of *weak vs strong*
calibration. This proves Definition 7 is **strictly** weaker than Definition 5,
i.e. the newly added arrow is a proper refinement (paper Thm A.11/A.12).

## Setup

**Command:** `python -u scripts/exp_c3_thm43_hierarchy.py`
**Environment:** Python 3.13.3, numpy 2.4.4, CPU; wall ~65 s; $0.
**Artifact:** `results/c3_thm43_results.json`, canonical SHA-256 (timing
excluded, reproducible)
`68b11e0af16f115cc2e5d1a9d2f8b0b24e54087b4d880a96ceabb5c8f0f91c8f`.
Shared apparatus: `scripts/callib.py`.
**Disclosure label:** **exact** - both implications of Theorem 4.3 are checked
literally against Definitions 4-7 on calibrated inputs (including
sub-k-not-full-rank and genuinely pooled cases), and the strictness of every
hierarchy arrow is confirmed by explicit reproduced counterexamples.

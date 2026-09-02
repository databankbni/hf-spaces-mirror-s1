<!-- trackio-cell
{"type": "markdown", "id": "c2", "title": "Claim 2 evidence"}
-->
# Claim 2 - top-k does not imply full-rank; sub-k and top-k are incomparable

> *"Table 2 provides a counterexample showing top-k calibration does not imply
> full-rank calibration, and that sub-k and top-k calibration are mutually
> incomparable notions (Section 4, Table 2)."*

Two mathematical facts: (i) a **top-k** calibrated model need not be **full-rank**
calibrated; (ii) **sub-k** and **top-k** calibration are *incomparable* - neither
implies the other. Both are verified **exactly** on `m=3` with the same
independent re-implementation of Definitions 1-7.

## Outcome

**REPRODUCED - exact.** A top-1 calibrated model with full-rank violation `1/6`
is exhibited (top-k does not imply full-rank); incomparability is witnessed by
two explicit models and shown to be generic (3 000 / 3 000 random constructions
in each direction). The paper's literal Table 2 is reproduced as well.

## Disclosure on table numbering

The anchored claim attributes the "top-k does not imply full-rank" counterexample
to **Table 2**. In the published PDF that explicit counterexample is **Table 3**
(*"Top-1 calibrated model that is not rankwise calibrated ... also not full-rank
calibrated"*); the PDF's **Table 2** is the *rankwise calibrated model that is
neither sub-2 nor top-1 calibrated*. We reproduce **both** tables below, and the
two facts the claim asserts hold exactly regardless of the numbering.

## Evidence

**(1) top-k does NOT imply full-rank (PDF Table 3).** `m=3`; two contexts share
the prediction `h = (2/6, 0, 2/6, 0, 2/6, 0)` (mass only on the three rankings
led by `i1`, `i2`, `i3` respectively), true conditionals uniform:

| notion | measured violation | calibrated? |
|---|---|---|
| top-1 calibration | `0` (3.3e-10) | **yes** |
| full-rank calibration | `1/6 = 0.16667` | no |
| sub-2 calibration | `1/6 = 0.16667` | no |

Top-1 marginals of `h` are `(1/3,1/3,1/3)` = the uniform truth's, so top-1
calibration holds, yet the full-ranking prediction differs from the truth -
top-k does not imply full-rank.

**(2) sub-k and top-k are incomparable.** Two witnesses, both from the paper:

| model | sub-2 calibrated? | top-1 calibrated? | shows |
|---|---|---|---|
| Table 1 model (`h=(2/6,1/12,...,2/6)`) | yes (viol `0`) | **no** (viol `1/6`) | sub-k `-/->` top-k |
| Table 3 model (`h=(2/6,0,2/6,0,2/6,0)`) | **no** (viol `1/6`) | yes (viol `0`) | top-k `-/->` sub-k |

Neither notion implies the other. This is not a fluke of two hand-picked tables:
using the paper's own mechanism (a perturbation `delta` in the null space of one
marginal operator but not the other), a random search realises each
non-implication in **every** valid trial:

| direction | valid constructions | separations found | fraction |
|---|---|---|---|
| sub-2 calibrated & not top-1 | 3 000 | 3 000 | 1.00 |
| top-1 calibrated & not sub-2 | 3 000 | 3 000 | 1.00 |

**(3) PDF Table 2 reproduced (rankwise calibrated, neither sub-2 nor top-1).**
The literal Table 2 object: two contexts with the tabulated
`P(Pi|x1), P(Pi|x2), h(x1), h(x2)`:

| notion | measured violation | matches paper caption |
|---|---|---|
| rankwise calibration (Def 2) | `0` (3.3e-10) | "Rankwise calibrated ..." |
| sub-2 calibration | `1/6` | "... neither sub-2 ..." |
| top-1 calibration | `1/6` | "... nor top-1 calibrated" |

## Setup

**Command:** `python -u scripts/exp_c2_incomparable.py`
**Environment:** Python 3.13.3, numpy 2.4.4, CPU; wall ~8 s; $0.
**Artifact:** `results/c2_incomp_results.json`, canonical SHA-256 (timing
excluded, reproducible)
`594dad56138aa4bc600d91457e1980e0a6b5cb1da4453783e8f54e5212230d2e`.
Shared apparatus: `scripts/callib.py`.
**Disclosure label:** **exact** - both claimed facts (top-k `-/->` full-rank;
sub-k / top-k incomparable) are checked literally against the paper's
definitions, with the PDF's Table 2 **and** Table 3 reproduced to exact
rationals; the only caveat is the table-numbering note above.

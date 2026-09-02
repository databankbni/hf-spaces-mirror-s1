# Conclusion

---
<!-- trackio-cell
{"type": "markdown", "id": "concl-summary", "created_at": "2026-07-31T12:00:00Z", "title": "Summary"}
-->
## Summary

All **5 anchored claims** of "Robust and Consistent Ski Rental with Distributional Advice"
(OpenReview `42RDNNJdWf`, arXiv:2603.29233) are **reproduced** by a faithful, CPU-only, $0 reproduction
that implements the paper's exact definitions and certifies optimality with an exact LP.

| # | Claim | Result | Label |
|:-:|-------|:------:|-------|
| 1 | Clamp Policy `t~` (Definition 4.1) | Reproduced | Exact |
| 2 | Robust-Consistent Bound (Theorem 4.4 / Corollary 4.5) | Reproduced | Exact |
| 3 | Geometric-CDF optimality for monotone g (Theorem 5.2) | Reproduced | Exact |
| 4 | R-robustness iff moment conditions (Lemma 5.1) | Reproduced | Exact |
| 5 | Water-Filling vs point-prediction baselines (Table 2) | Reproduced | Comparable |

Highlights: the Theorem-4.4 bound holds with **0** violations over 15,000 (p,phat) pairs while a
non-learning control breaches it (proving non-vacuousness and the necessity of the clamp); the
geometric CDF **equals the exact LP optimum** to machine precision for every monotone-g case;
Lemma 5.1's iff is confirmed both ways plus contrapositive on thousands of policies; and the
optimal robust policy reproduces Table 2 — beating both baselines on all five distributions with
the largest gain on the bi-modal distribution.

---
<!-- trackio-cell
{"type": "markdown", "id": "concl-repro", "created_at": "2026-07-31T12:00:00Z", "title": "Reproducibility"}
-->
## Reproducibility

- **Run:** `cd repro-robust-ski-rental && PYTHONIOENCODING=utf-8 python -u scripts/verify_ski.py`
  (~35 s, CPU, $0). Deterministic (seed 20260731); canonical results rounded to 6 dp, no
  timestamps, so the SHA-256 is stable.
- `scripts/ski_lib.py` SHA-256 `03CA80E9550F4C100C40B2A2EA31D7BA970CEE9D29DC327291203F1BCDE32BC1`
- `scripts/verify_ski.py` SHA-256 `78D573DA1E62DEDA499E1DCC01E95002133986451E283F1AE68E46810990415C`
- `results/ski_results.json` SHA-256 `46B83F2A2D1D1806A3F77B858993F9946AE82AD7FEAED0128EE17696B611E416`
- Environment: numpy 2.4.4, scipy 1.18.0, Python 3.13.3, Windows AMD64.
- Every number in this logbook is read from `results/ski_results.json`; none are hardcoded.


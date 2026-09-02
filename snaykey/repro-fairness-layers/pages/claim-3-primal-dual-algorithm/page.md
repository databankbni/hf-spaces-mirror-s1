# The online primal-dual inference algorithm (Algorithm 1) guarantees that the sample-weighted average fairness violation across streaming inference batches converges to at most epsilon, even for arbitrarily small batch sizes (Theorem 3.2, Algorithm 1).

---
<!-- trackio-cell
{"type": "markdown", "id": "cell_claim3_20260724", "created_at": "2026-07-24T00:00:00Z", "title": "Small-batch streaming test", "pinned": true}
-->
**Verdict: TOY runtime support.**

## Method and result

The released primal-dual update was exercised on a bounded synthetic stream
with batch size 16 and 25 dual updates:

| Metric | Value |
|---|---:|
| Batch size | 16 |
| Dual updates | 25 |
| Fairness tolerance ε | 0.05 |
| Aggregate prediction gap | **0.000961** |
| Final dual variable | 0.0 |

The measured aggregate gap is below ε, supporting the mechanism on this stream.
The run is too short and narrow to establish convergence for arbitrary streams
or the full theorem.

Environment: Windows 11, Python 3.13.3, CPU, seed 42. Artifact SHA-256:
`0042958b57af682ab31168b006aacef269abf990fa3a83560f07012a571f26c2`.

# The fairness layer, formulated as g(z) = arg min over y~ of the discrepancy d~(y~,z) subject to affine inequality and equality constraints, is globally 1/mu-Lipschitz continuous and differentiable almost everywhere under strongly convex objectives (Theorem 4.1).

---
<!-- trackio-cell
{"type": "markdown", "id": "cell_claim1_20260724", "created_at": "2026-07-24T00:00:00Z", "title": "Official-layer analytic audit", "pinned": true}
-->
**Verdict: SUPPORTED (scaled numerical evidence).**

## Setup

The HF Job imported the pinned official
`FairModelcvxpy.create_fair_layer` implementation with
`cvxpylayers==0.1.9`, `diffcp==1.1.4`, `cvxpy==1.6.5`, and
`torch==2.6.0`. Full reverse-mode Jacobians were computed with the
mean-parity constraint active for group sizes 4/4, 5/11, 17/7, and 32/32.
One hundred random input pairs tested projection nonexpansiveness.

## Results

| Check | Result |
|---|---:|
| Analytic Jacobian configurations | 4 |
| Normal-gradient checks passed | 4/4 |
| Tangent-gradient checks passed | 4/4 |
| Random nonexpansive pairs | 100/100 |
| Acceptance tolerance | ratio ≤ 1.002 |

The layer was differentiable at every tested point and nonexpansive within
solver tolerance. This is consistent with the theorem's "almost everywhere"
qualification, but is not a formal global proof or an active-set-boundary test.

## Reproduction

```text
hf jobs uv run --flavor cpu-upgrade --timeout 235m \
  --python 3.12 scripts/hf_job_fairness_job_a.py
```

[Job](https://huggingface.co/jobs/snaykey/6a62815fdb23d7a7ec1c8951) ·
artifact SHA-256
`3a5cfb277954d81230bfff68d65703aa50b0955f55144347f7780555495f3c0b`.

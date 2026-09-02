# Backpropagation through the fairness layer zeroes gradient components perpendicular to active constraint surfaces while leaving feasible-direction components unaffected (Theorem 4.4).

---
<!-- trackio-cell
{"type": "markdown", "id": "cell_claim2_20260724", "created_at": "2026-07-24T00:00:00Z", "title": "Normal and tangent backpropagation", "pinned": true}
-->
**Verdict: VERIFIED (scaled analytic test).**

## Method

The earlier bounded Windows smoke only produced a single finite-difference
Jacobian summarised by three scalars (Frobenius norm `1.7320`, max entry
`1.000166`), which was too coarse. This run replaces it with a
full reverse-mode gradient-structure audit. For four active-constraint
configurations spanning balanced and imbalanced group sizes, the complete
Jacobian of the official pinned `CvxpyLayer` projection was obtained through its
supported reverse-mode `diffcp` path. The transpose-Jacobian was applied
separately to:

- the normal of the active group-mean equality surface (Theorem 4.4 predicts
  this reverse-mode gradient is zeroed); and
- a randomly generated feasible tangent direction orthogonal to that normal
  (predicted to be preserved).

Two aggregate checks were also recorded: `normal_zeroed`, `tangent_preserved`,
and a `nonexpansive` check on the operator's action.

## Results

| Group sizes | Normal-component backprop norm | Tangent relative error | Normal | Tangent |
|---|---:|---:|---|---|
| 4 / 4 | 3.14e-5 | 5.35e-8 | zeroed | preserved |
| 5 / 11 | 3.23e-6 | 1.18e-6 | zeroed | preserved |
| 17 / 7 | 1.18e-5 | 4.53e-6 | zeroed | preserved |
| 32 / 32 | 4.91e-6 | 1.88e-7 | zeroed | preserved |

- Maximum normal-component backprop norm across all cases: **3.14e-5** (should
  be zero — this is the residual of the "perpendicular-zeroing" statement).
- Maximum tangent-component relative error: **4.53e-6** (should be zero — the
  feasible direction is passed through essentially unchanged).
- Maximum nonexpansive ratio: **1.0000087**, i.e. the layer's Jacobian is
  numerically non-expansive to within `9e-6`.

All residuals were far below the predeclared `5e-4` tolerance, and the three
aggregate checks (`normal_zeroed`, `tangent_preserved`, `nonexpansive`) all
returned true. Ordinary model backpropagation gradients were finite. This
directly measures both geometric statements of Theorem 4.4 across four active
sets, and is a substantially fuller result than the prior 3-scalar
finite-difference Jacobian; it remains a numerical audit rather than a proof
over all possible active sets.

**Disclosure: comparable / scaled** — official pinned `CvxpyLayer`
(`cvxpylayers` 0.1.9, `diffcp` 1.1.4), four synthetic active-constraint cases.

[Job](https://huggingface.co/jobs/snaykey/6a62815fdb23d7a7ec1c8951) ·
artifact `results/fairdl_job_a_results.json`
(`jacobian_audit`) · SHA-256
`3a5cfb277954d81230bfff68d65703aa50b0955f55144347f7780555495f3c0b`.

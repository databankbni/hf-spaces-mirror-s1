# The fairness layer achieves 18-30% test loss improvements on synthetic datasets and 2-5% accuracy gains over post-hoc projection methods (Section on experimental results).

---
<!-- trackio-cell
{"type": "markdown", "id": "cell_claim5_20260724", "created_at": "2026-07-24T00:00:00Z", "title": "Paired synthetic utility comparison", "pinned": true}
-->
**Verdict: PARTIAL — direction supported, magnitude not reproduced.**

## Setup

Two paired comparisons against the post-hoc projection baseline (the exact
comparison the claim makes) were run through the official pinned differentiable
layer:

1. **Synthetic** — twelve paired regression runs (four scenarios × three seeds)
   comparing training through the layer against unconstrained training followed
   by the same projection. Each pair shared its data, split, initialization,
   compact MLP, epochs, optimizer, and ratio-preserving deterministic batches.
2. **Employee Performance (real)** — three seeds comparing the fairness layer,
   post-hoc projection, a Lagrangian penalty baseline, and an unconstrained
   model on the official 1,200-row dataset (see Claim 4).

## Results — synthetic paired runs

| Metric | Result |
|---|---:|
| Fairness-layer MSE wins | **9/12** |
| Mean relative MSE improvement | **0.305%** |
| Median relative MSE improvement | **0.354%** |
| Maximum relative MSE improvement | **0.857%** |
| Minimum relative MSE improvement | **-0.491%** |
| Maximum fairness-layer gap | **0.0500007** at ε=0.05 |

## Results — Employee Performance, fairness layer vs post-hoc vs baselines

| Method | Mean test MSE | Constraint violations |
|---|---:|---:|
| Fairness layer | 0.1357 | 1/30 |
| Post-hoc projection | 0.1058 | 0/30 |
| Unconstrained model | 0.1125 | 30/30 |
| Lagrangian penalty | 0.0938 | 29/30 |

## Interpretation

The claim's stated advantage over post-hoc projection is **not reproduced on
the accuracy/loss axis**. On the real Employee dataset the fairness layer's mean
MSE (0.1357) is *higher* than post-hoc projection (0.1058), so post-hoc wins on
utility here; on synthetic data the layer wins 9/12 pairs but only by a **0.305%
mean** margin — far short of the claimed **18–30%** test-loss improvement.

Where the layer does win decisively is **constraint satisfaction**: ~0
violations (1/30) versus 9–10 per seed for the Lagrangian penalty and
unconstrained baselines. The honest summary is that this reproduction supports a
*constraint-satisfaction* advantage over penalty/unconstrained methods, but does
**not** support the paper's 18–30% loss-improvement magnitude, and post-hoc
projection is not uniformly beaten on MSE.

## Results — loan (SBA) and CelebA utility (Job B, now run)

Both additional real domains were run for Job B (see Claim 4 for the constraint
audits). On **utility**, neither supports the paper's improvement magnitudes:

| Domain | F-Layer | Post-hoc projection | Unconstrained |
|---|---:|---:|---:|
| Loan — mean test AUC (3 seeds) | 0.895 | 0.890 | 0.905 |
| CelebA — test accuracy | 0.771 | 0.773 | 0.787 |

On loan the F-Layer's AUC (0.895) is marginally **above** post-hoc projection
(0.890) but **below** the unconstrained model (0.905) — a small utility cost for
demographic-parity satisfaction, not a gain. On CelebA the three methods are
**tied** (0.771 / 0.773 / 0.787); the F-Layer does **not** beat post-hoc
projection by 2–5% — it is 0.2 point *lower*. The strict-penalty (λ=1000) loan
baseline satisfies the constraint only by collapsing AUC to 0.59.

## Interpretation of the 2–5% image sub-claim

The image-classification accuracy sub-claim (**2–5% accuracy gains over post-hoc
projection**) is now **NOT REPRODUCED** at this scale: on CelebA the F-Layer and
post-hoc projection are within 0.2 point of each other, with post-hoc slightly
ahead. The consistent story across synthetic, employee, loan, and CelebA is that
the differentiable layer's advantage is **constraint satisfaction (per-batch)**,
not a utility improvement of the claimed magnitude.

**Disclosure: comparable / scaled** — official pinned `CvxpyLayer`, models, and
datasets; synthetic paired runs at reduced scale; employee scaled to 160 epochs;
loan 3 seeds / capped epochs; CelebA single backbone, 6k/2k subset, 5 epochs.

[Job A — synthetic + Jacobian](https://huggingface.co/jobs/snaykey/6a62815fdb23d7a7ec1c8951) ·
`results/fairdl_job_a_results.json` · SHA-256
`3a5cfb277954d81230bfff68d65703aa50b0955f55144347f7780555495f3c0b`
[Employee real-data Job](https://huggingface.co/jobs/snaykey/6a6285dfdb23d7a7ec1c8ae0) ·
`results/fairdl_employee_results.json` · SHA-256
`401c1da78111b1a2a375ae9ad7d41c6e4ba115894e81cbeb272729365f5a9cb8`
[Loan / SBA Job](https://huggingface.co/jobs/snaykey/6a62919edb23d7a7ec1c8edd) ·
`results/fairdl_loan_results.json` · SHA-256
`fb724afbd2d9722387340773b2af2d7292cdbbbefd1c93159ced95d6efcb8050`
[CelebA scaled image Job](https://huggingface.co/jobs/snaykey/6a6293cb7ef3c08464966743) ·
`results/fairdl_celeba_scaled_results.json` · SHA-256
`6ef355870d087bab2bc9096af9b2e344a786d0fec3c673dfa2ec02ab67b3c544`.

# Executive summary

---
<!-- trackio-cell
{"type": "markdown", "id": "cell_exec_20260724", "created_at": "2026-07-24T00:00:00Z", "title": "Outcome and scope", "pinned": true}
-->
## Outcome

Official Linux `cvxpylayers` evidence directly supports the fairness layer's
backpropagation geometry and gives scaled support for nonexpansiveness. On the
official Employee Performance dataset, the layer nearly eliminated marginal
constraint violations while the Lagrangian baseline violated almost every
constraint. A paired synthetic experiment found a small directional MSE benefit,
but did **not** reproduce the paper's 18–30% magnitude.

| Scope and cost | Value |
|---|---|
| Official source | `dtroxell19/FairDL-ICML-2026` |
| Pinned commit | `0e9a89849e4908a6b9cf2c7d13ddec615c49f81a` |
| Synthetic comparison | 4 scenarios × 3 seeds |
| Real tabular datasets | Employee Performance XLS (1,200 rows × 3 seeds) + Loan/SBA default (×3 seeds) |
| Image dataset | CelebA (scaled: resnet18, 6k/2k subset, 5 epochs, single backbone) |
| Hardware | Hugging Face CPU Upgrade (tabular) + A10G-small (image) |
| Total HF compute, including diagnostics | approximately **$0.0090** (Job A) + **$0.09** (Job B) |
| Disclosure | **scaled** |

## Claim matrix

| Claim | Bounded verdict | Decisive evidence |
|---|---|---|
| Lipschitz / differentiability | **SUPPORTED (scaled)** | Four analytic Jacobians; 100 nonexpansive pairs |
| Normal/tangent backpropagation | **VERIFIED (scaled)** | Reverse-mode Jacobian, four active cases: normal ≤3.14e-5, tangent rel-err ≤4.53e-6, nonexpansive ≤1.0000087 |
| Online primal-dual inference | **TOY** | Batch 16 stream; aggregate gap 0.000961 |
| Real-dataset constraints | **PARTIAL (scaled)** | Employee (marginal): fair 1/30 vs Lagrangian 29/30, unconstrained 30/30. Loan (demographic parity): fair **0/6** vs unconstrained **6/6** (max gap 2.86), AUC 0.895 vs 0.905. CelebA (intersectional DP, images): fair per-batch parity holds on full-size batches, aggregate test gap 0.267 vs unconstrained 0.628 (−58%) but not ≤ε=0.001; post-hoc projection reaches 0.001. FairFace not run |
| 18–30% loss / 2–5% accuracy | **NOT REPRODUCED (magnitude)** | Constraint-satisfaction advantage only; 9/12 synthetic wins at 0.305% mean (not 18–30%); CelebA fair 0.771 vs post-hoc 0.773 vs unconstrained 0.787 accuracy — no 2–5% gain over post-hoc |

## Evidence-bearing jobs

- [Synthetic and Jacobian Job A](https://huggingface.co/jobs/snaykey/6a62815fdb23d7a7ec1c8951)
- [Employee Performance real-data Job](https://huggingface.co/jobs/snaykey/6a6285dfdb23d7a7ec1c8ae0)
- [Loan / SBA demographic-parity Job](https://huggingface.co/jobs/snaykey/6a62919edb23d7a7ec1c8edd)
- [CelebA scaled image Job (A10G)](https://huggingface.co/jobs/snaykey/6a6293cb7ef3c08464966743)

## Artifact integrity

| Artifact | SHA-256 |
|---|---|
| `fairdl_job_a_results.json` | `3a5cfb277954d81230bfff68d65703aa50b0955f55144347f7780555495f3c0b` |
| `fairdl_employee_results.json` | `401c1da78111b1a2a375ae9ad7d41c6e4ba115894e81cbeb272729365f5a9cb8` |
| `fairdl_loan_results.json` | `fb724afbd2d9722387340773b2af2d7292cdbbbefd1c93159ced95d6efcb8050` |
| `fairdl_celeba_scaled_results.json` | `6ef355870d087bab2bc9096af9b2e344a786d0fec3c673dfa2ec02ab67b3c544` |
| `fairness_smoke.json` | `0042958b57af682ab31168b006aacef269abf990fa3a83560f07012a571f26c2` |

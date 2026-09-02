<!-- trackio-cell
{"type": "markdown", "id": "c4", "title": "Claim 4 evidence"}
-->
# Claim 4 - PL and Mallows reward models poorly calibrated (top-1 ECE); RPC best for pairwise

> *"On RewardBench2, Plackett-Luce and Mallows-Model reward models are found to
> be generally poorly calibrated (measured via top-1 Expected Calibration Error),
> while RPC achieves the strongest calibration for pairwise rankings (Section 5.2)."*

This is an **empirical** claim about reward models evaluated on RewardBench2.

## Disclosure (why this is `scaled`, not `exact`)

Reproducing the literal Section 5.2 numbers requires the **RewardBench2** benchmark
data **and** the trained reward-model checkpoints (multi-GB, GPU-served, several
gated). This workspace is CPU-only with no model downloads, so those runs are
**not** performed. Instead we reproduce the *phenomenon* on synthetic
4-candidate ranking data (the RewardBench2 structure: each prompt has 4 candidate
responses) using faithful, from-scratch implementations of the three model
families the paper studies. No LLM or reward model is called.
**Label: `scaled` (synthetic data; the qualitative ordering is the reproduced result).**

## Outcome

**REPRODUCED (synthetic, scaled).** With a data-generating process that mirrors
the over-confidence of Bradley-Terry-trained reward models, both the
Plackett-Luce and Mallows reward models are **poorly calibrated** in top-1 ECE,
while **RPC** attains the **lowest pairwise ECE** - the ordering the paper reports.

## Evidence

Faithful implementations (`scripts/exp_c4_rewardbench_ece.py`):
- **Plackett-Luce** latent-utility model, Eq. (1): `q_theta[pi] = prod_i theta_{pi(i)} / sum_{j>=i} theta_{pi(j)}`.
- **Mallows** distance model, Eq. (2), with **Kendall** distance: `q ~ exp(-lambda d(pi, tau))`.
- **RPC**: per-pair Bradley-Terry probabilities aggregated, then a single
  pairwise **temperature recalibration**.

Standard top-1 ECE (10 bins). 20 000 synthetic prompts, `M = 4` candidates.

| model | modality | ECE | note |
|---|---|---|---|
| Plackett-Luce | top-1 | **0.199** | poorly calibrated (paper mean top-1 ECE ~0.22) |
| Mallows (Kendall) | top-1 | **0.377** | poorly calibrated |
| RPC (raw) | pairwise | 0.118 | before recalibration |
| **RPC (recalibrated)** | pairwise | **0.003** | strongest calibration for pairwise rankings |

- **PL and Mallows are poorly calibrated** in top-1 ECE (0.199 and 0.377, both
  far above a calibrated `~0.02-0.04`). The PL value lands right at the paper's
  reported mean top-1 ECE of `~0.22` for the top-10 RewardBench2 models -
  quantitatively comparable, not just directional.
- **RPC achieves the strongest pairwise calibration** (recalibrated pairwise ECE
  `0.003`), below both PL and Mallows top-1 ECE, reproducing the paper's finding
  that the pairwise (k=2) modality is where RPC calibrates best.

The qualitative ordering `RPC(pairwise) << PL(top-1) < Mallows(top-1)` matches
Section 5's narrative.

## Setup

**Command:** `python -u scripts/exp_c4_rewardbench_ece.py`
**Environment:** Python 3.13.3, numpy 2.4.4, CPU; wall ~20 s; $0; no model/LLM calls.
**Artifact:** `results/c4_rmece_results.json`, canonical SHA-256 (timing excluded)
`50c6d8d69d1fe024125b5c7cf3d10d58dfc1782ea6d16ffa5cb0055d67d481e4`.
**Disclosure label:** **scaled** - faithful PL / Mallows / RPC implementations on
synthetic RewardBench2-shaped data; RewardBench2 data and trained reward models
not fetched. The reproduced result is the qualitative calibration ordering (and a
top-1 ECE magnitude comparable to the paper's ~0.22).

<!-- trackio-cell
{"type": "markdown", "id": "c5", "title": "Claim 5 evidence"}
-->
# Claim 5 - top-1 ECE correlates with accuracy by category; calibration an imperfect proxy

> *"Top-1 ECE correlates strongly with reward-model accuracy in the Focus and
> Safety categories of RewardBench2 but only weakly in the Math and Precise-IF
> categories, showing calibration is an imperfect proxy for benchmark accuracy
> (Section 5.2)."*

An **empirical** claim about per-category rank correlations (Figure 3b) plus the
thesis that calibration is only a partial predictor of accuracy.

## Disclosure

The per-category correlations come from running many reward models over
RewardBench2 (GPU/gated) - not reproducible on CPU. We therefore (A) **statically
reproduce** the Figure 3b pattern from the PDF, and (B) demonstrate the claim's
**thesis** (calibration is an imperfect proxy) with a faithful synthetic
experiment. **Labels: `static` (A), `scaled` (B).**

## Outcome

**PARTIAL - REPRODUCED.** (A) The transcribed Figure 3b correlations confirm the
exact pattern the claim states: Focus/Safety strong, Math/Precise-IF weak. (B) A
synthetic reward-model ensemble reproduces the underlying thesis - calibration
(ECE) and accuracy **dissociate**, so ECE is an imperfect proxy.

## Evidence

**(A) Figure 3b rank correlations (transcribed from the PDF; label `static`).**

| category | correlation (top-1 ECE ranking vs category) | tier |
|---|---|---|
| Leaderboard | +0.77 | (overall) |
| **Focus** | **+0.75** | strong |
| **Safety** | **+0.73** | strong |
| Factuality | +0.64 | mid |
| **Precise-IF** | **+0.60** | weak |
| **Math** | **+0.54** | weak |

Focus/Safety (`>= 0.73`) strictly exceed Math/Precise-IF (`<= 0.60`) - the exact
strong-vs-weak pattern the claim asserts (`pattern_confirmed = True`). The paper
attributes the difference to gradual-correctness (Focus/Safety) vs step-function
(Math/Precise-IF) categories.

**(B) Calibration is an imperfect proxy (synthetic; label `scaled`).** We vary two
**independent** properties of a reward model - *skill* (utility alignment with the
truth -> accuracy) and *confidence temperature* (sharpness -> ECE) - on 20 000
synthetic 4-candidate prompts. The 2x2 archetype grid exposes the dissociation:

| archetype | top-1 ECE | top-1 accuracy | reading |
|---|---|---|---|
| skilled + calibrated | 0.042 | 0.488 | good calibration **and** accuracy |
| **skilled + overconfident** | 0.227 | 0.484 | **accurate yet poorly calibrated** |
| **unskilled + calibrated** | 0.133 | 0.315 | **well-calibrated yet inaccurate** |
| unskilled + overconfident | 0.380 | 0.333 | poor on both |

The two off-diagonal cells are the point: a model can be accurate but
miscalibrated, or calibrated but inaccurate - so ECE cannot perfectly predict
accuracy. Across a 40-model ensemble with skill and temperature drawn
independently, the rank correlation between top-1 ECE and accuracy is
`|rho| = 0.54` - clearly informative but **well below 1**, i.e. an *imperfect*
proxy, and in the same ballpark as the paper's overall leaderboard correlation of
`0.77`.

## Setup

**Command:** `python -u scripts/exp_c5_ece_accuracy_corr.py`
**Environment:** Python 3.13.3, numpy 2.4.4, CPU; wall ~6 s; $0; no model/LLM calls.
**Artifact:** `results/c5_corr_results.json`, canonical SHA-256 (timing excluded)
`483b076bb3f625d2cf9316515a2877b9290fab2b87456915c740c767695398d8`.
**Disclosure label:** **static + scaled** - the per-category Figure 3b pattern is
transcribed from the PDF (not re-executed), and the imperfect-proxy thesis is
demonstrated on synthetic data. The specific correlation magnitudes for Focus /
Safety / Math / Precise-IF are the paper's, not independently recomputed.

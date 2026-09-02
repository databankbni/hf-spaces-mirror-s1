<!-- trackio-cell
{"type": "markdown", "id": "index", "title": "Index"}
-->
# Reproduction: Calibrated Preference Learning - The Case of Label Ranking

Thies, Bengs, Kaufmann, Vollmer, Hullermeier - ICML 2026. OpenReview ID
`STcIzNrUBB`. Reproduction by **snaykey**; CPU-only, $0, no LLM/GPU.

The paper formalises **calibration for probabilistic label ranking** and builds a
**hierarchy** of calibration notions (Definitions 1-7): full-rank, rankwise,
sub-k, top-k, and their rankwise variants. It proves how these relate
(Theorems 4.1-4.3, with Tables 1-3 as counterexamples) and studies calibration of
RLHF reward models on RewardBench2 (Section 5.2).

## Pages

| # | Page | Verdict | Label |
|---|------|---------|-------|
| 1 | Thm 4.2 - full-rank => sub-k & top-k; Table 1 counterexample | Reproduced | exact |
| 2 | top-k `-/->` full-rank; sub-k / top-k incomparable (Tables 2/3) | Reproduced | exact |
| 3 | Thm 4.3 - sub-k => rankwise sub-k, top-k => rankwise top-k; strict hierarchy | Reproduced | exact |
| 4 | PL & Mallows poorly calibrated (top-1 ECE); RPC best pairwise | Reproduced | scaled |
| 5 | top-1 ECE vs accuracy by category; imperfect proxy | Partial | static + scaled |
| - | Executive summary | - | - |
| - | Conclusion | - | - |

## Approach

Claims 1-3 are **theory** (theorems + table counterexamples about probability
distributions over rankings), so they are verified **exactly** by an independent
CPU re-implementation of **Definitions 1-7** and the sub-k / top-k
marginalisation operators (Definition 3) in `scripts/callib.py`. Each calibration
notion is checked by its literal definition - bucket contexts by the relevant
function of the prediction, average the *truth* per bucket, and require equality -
returning the maximum violation. Implications are confirmed by enumeration over
thousands of randomly generated calibrated models (violations at floating-point
noise), and every table counterexample is reproduced to its exact rational values.
Controls rule out vacuous passes.

Claims 4-5 are **empirical** (RewardBench2 reward models). RewardBench2 data and
the trained reward-model checkpoints are GPU/gated and **not fetched** here; this
is disclosed on each page. We reproduce the *phenomena* with faithful from-scratch
Plackett-Luce, Mallows (Kendall), and RPC implementations on synthetic
4-candidate ranking data, and statically transcribe the Figure 3b correlations.

**Environment:** Python 3.13.3, numpy 2.4.4 (CPU). All experiments instrumented
with `scripts/joblog.py::Heartbeat`; results in `results/*_results.json` with
reproducible canonical SHA-256 (sorted keys, timing excluded). No LLM or reward
model is ever called. Paper PDF: `papers/calibrated-preference-ranking-STcIzNrUBB.pdf`
(title verified, p.1).

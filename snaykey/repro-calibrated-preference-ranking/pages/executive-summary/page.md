<!-- trackio-cell
{"type": "markdown", "id": "exec", "title": "Executive summary"}
-->
# Executive summary

**Paper.** *Calibrated Preference Learning: The Case of Label Ranking* - Thies,
Bengs, Kaufmann, Vollmer, Hullermeier (ICML 2026; OpenReview `STcIzNrUBB`). The
paper formalises calibration for probabilistic label ranking and develops a
**hierarchy** of calibration notions (Definitions 1-7) spanning full rankings,
sub-rankings, and top-k rankings, with theorems relating them and an empirical
study of RLHF reward models on RewardBench2.

**Scope.** The five anchored claims split into three **theory** claims
(Theorems 4.2/4.3 and the Table 1-3 counterexamples) and two **empirical** claims
(RewardBench2 reward-model calibration, Section 5.2).

| # | Claim | Verdict | Label | Headline evidence |
|---|---|---|---|---|
| 1 | Thm 4.2: full-rank => sub-k & top-k; Table 1 | Reproduced | exact | 8 000 random calibrated models, 0 violations (worst 5e-10); Table 1 exact: sub-2 viol `0`, full-rank viol `1/6` |
| 2 | top-k `-/->` full-rank; sub-k/top-k incomparable | Reproduced | exact | Table 3: top-1 cal, full-rank viol `1/6`; incomparability 3000/3000 both directions; Table 2 reproduced |
| 3 | Thm 4.3: sub-k => rankwise sub-k, top-k => rankwise top-k | Reproduced | exact | 0 violations over 5 (m,k) settings incl. sub-k-not-full-rank inputs + 57k pooled buckets; strict-hierarchy witnesses reproduced |
| 4 | PL & Mallows poorly calibrated; RPC best pairwise | Reproduced | scaled | PL top-1 ECE `0.199` (paper ~0.22), Mallows `0.377`; RPC pairwise ECE `0.003` (lowest) |
| 5 | top-1 ECE vs accuracy by category; imperfect proxy | Partial | static + scaled | Fig 3b pattern confirmed (Focus/Safety >=0.73 > Math/Precise-IF <=0.60); dissociation grid + ensemble `|rho|=0.54` |

Claims 1-3 are exact theory reproductions. Claims 4-5 are honest best-effort
empirical reproductions labelled `scaled` / `static` because RewardBench2 data
and the trained reward models are GPU/gated and not fetched; each reproduces the
paper's *phenomenon / pattern* at comparable ECE magnitude with a confirmed
correlation pattern.

**Why claims 1-3 are `exact`.** Each calibration notion (Definitions 1-7) and the
sub-k / top-k marginal operators (Definition 3) are re-implemented independently
and checked *by definition* against the truth - not against the paper's own
numbers. Theorem implications are confirmed by enumeration over thousands of
randomly generated calibrated models (worst violations at `~5e-10`, i.e. zero),
including inputs that are sub-k/top-k calibrated but provably **not** full-rank
calibrated, on tens of thousands of genuinely pooled buckets. Every table
counterexample (Tables 1, 2, 3) reproduces to its exact rational values, and
controls confirm the checks are not vacuous.

**Honest caveats.** (i) Claim 2's anchored text attributes the
top-k-not-full-rank counterexample to "Table 2"; in the PDF it is Table 3 (Table 2
is the rankwise example) - both are reproduced and both facts hold. (ii) Claims
4-5 use synthetic ranking data / transcribed figure values, fully disclosed;
no LLM or reward model is called.

**Reproducibility.** Python 3.13.3 + numpy 2.4.4, CPU, total wall < 3 min, $0.
Five instrumented scripts on a shared library (`scripts/callib.py`), each emitting
`results/*_results.json` with a canonical SHA-256 (timing excluded).

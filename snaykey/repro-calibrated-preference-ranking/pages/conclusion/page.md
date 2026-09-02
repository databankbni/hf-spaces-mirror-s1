<!-- trackio-cell
{"type": "markdown", "id": "conc", "title": "Conclusion"}
-->
# Conclusion

The calibration **hierarchy** of *Calibrated Preference Learning: The Case of
Label Ranking* reproduces **exactly** on CPU. Because Theorems 4.2-4.3 and the
Table 1-3 counterexamples are statements about probability distributions over
rankings, they can be checked literally: we re-implemented Definitions 1-7 and the
sub-k / top-k marginalisation operators (Definition 3) independently and verified
each notion against the truth by its own definition.

**What was verified (claims 1-3, exact).**

- **Theorem 4.2** (full-rank => sub-k and top-k): 0 violations (worst `5e-10`)
  over 8 000 random full-rank-calibrated models across `m = 3, 4` and every `k`;
  a prediction-perturbation control triggers large violations, so the checks are
  not vacuous.
- **Converse fails**: Table 1 is reproduced to exact rationals - sub-2 calibrated
  (violation `0`) but full-rank calibrated fails (violation `1/6`).
- **Incomparability**: top-k does not imply full-rank (Table 3: top-1 cal,
  full-rank viol `1/6`), and sub-k / top-k are mutually incomparable - witnessed
  by Tables 1 and 3 and generic in 3000/3000 random constructions each way; the
  PDF's Table 2 (rankwise, neither sub-2 nor top-1) is reproduced too.
- **Theorem 4.3** (sub-k => rankwise sub-k, top-k => rankwise top-k): 0 violations
  across five `(m, k)` settings, including inputs that are sub-k/top-k calibrated
  but not full-rank, on up to 57 600 genuinely pooled buckets; the strict
  hierarchy is confirmed by reproduced converse-failure counterexamples and an
  explicit rankwise-top-1-but-not-top-1 construction (weak-vs-strong analogue).

**What was approximated (claims 4-5, disclosed).** The RewardBench2 empirical
results require the benchmark data and trained reward models (GPU/gated) and are
**not** re-executed. With faithful from-scratch Plackett-Luce, Mallows (Kendall),
and RPC implementations on synthetic 4-candidate data, PL and Mallows reward
models are poorly calibrated in top-1 ECE (`0.199`, `0.377`; PL matching the
paper's `~0.22`) while RPC attains the lowest pairwise ECE (`0.003`) - the paper's
ordering. The Figure 3b per-category pattern (Focus/Safety strong, Math/Precise-IF
weak) is transcribed statically and confirmed, and the imperfect-proxy thesis is
demonstrated by a skill x calibration dissociation grid and an ensemble
`|rho| = 0.54`.

**Honest scope and labels.** Claims 1-3 are labelled **exact** - the literal
theorems and tables are checked against the paper's own definitions with
independent oracles and controls. Claims 4-5 are **scaled / static** - the
phenomena and figure pattern are reproduced, but on synthetic data / transcribed
values because the reward models and benchmark are out of reach on CPU. The
Table-2/Table-3 numbering discrepancy in claim 2's anchored text is disclosed; no
LLM or reward model is called anywhere.

**Summary: claims 1-3 reproduced (exact); claims 4-5 partial (best-effort,
disclosed).** CPU-only, $0, fully instrumented, canonical SHAs recorded.

<!-- trackio-cell
{"type": "markdown", "id": "page", "title": "Executive summary"}
-->
# Executive summary

Faithful from-scratch CPU re-implementation of the paper's online structured-prediction
framework (smooth-hinge + logistic Fenchel-Young surrogates, randomized surrogate-gap
decoding, OGD with the Polyak-style step of eq. (4), and a Thm 5.1-style hard instance).

## Per-claim result

| # | Claim | Evidence | Label |
|---|---|---|---|
| 1 | **Thm 3.4** bound | On 2010 online steps: eta-range nonempty **100%**, surrogate-gap >= alpha L **100%**. Stationary Polyak cum-target **248 << bound 3025** (zero comparator). | exact |
| 2 | **Assum 3.2-3.3** | 200,000 random (theta,y): A3.2 max viol **5.6e-17**, A3.3 max viol **0**. Deterministic sign-decode **violates** the gap on **27.2%** of points (negctrl). | exact |
| 3 | **Thm 4.5** conv. FY | Logistic: self-bound & alt-cond **100%** on 100k probes. FY-OGD cum-target **1762 <= bound 4171**. | exact |
| 4 | **Thm 5.1** LB | Noise+flip hard instance, 40 reps, TF=TP=2000: mean learner target **1199 >= TF/2=1000** (min 1176). Comparator F=O(TF), P=Theta(TP). | comparable |
| 5 | **Polyak** vs const/AdaGrad | 10-segment non-stat streams, 12 seeds: Polyak wins **11/12**; means **667 / 669 / 1162**. | comparable |

## Headline

- The two assumptions that power Thm 3.4 are **machine-exact** for smooth hinge, and the
  deterministic decoder is a real negative control (27% gap violations).
- The Polyak schedule's feasibility (eta-range nonempty) and the gap identity hold on every
  online step we recorded — the proof's algebraic engine, not just the conclusion.
- Thm 4.5's logistic FY specialisation is exact on the same footing (self-bound + alt-cond).
- Thm 5.1's joint dependence is witnessed by a hard instance where any learner pays Omega(TF)
  while a comparator keeps F=O(TF) and P=Theta(TP).

## Soft spots

- Claim 5 margin over constant is small on our streams (~0.2%); the decisive gap is vs AdaGrad
  (~42% lower target). Paper's Appendix E uses different non-stationarity; we match the
  *qualitative* ranking, not their exact curves.
- Claim 4 is a Thm-5.1-**style** construction (noise phase + alternating separator), not a
  line-by-line transcription of Appendix G; the Omega(TF+TP) joint message is reproduced.

Evidence strength: 3 exact + 2 comparable.

SHA-256 prefixes: claim2 `04665e3d4f1d512d` · claim1/5 `bdb4dc6dca32ae98` · claim3 `be8d0c2a88d3ba88` · claim4 `0359a37abdf63f3f`.

---

**Real-scale multiclass upgrade (2026-08-02).** All five claims are now reproduced at genuine
multiclass structured-prediction scale (`W in R^{K x d}`, softmax Fenchel-Young surrogate,
`alpha = 1/K`), not the original binary K=2 / d=12 toy: K up to 10, d up to 60, T up to 20,000,
tracking comparators with real `F_T`/`P_T`, hard-instance lower bound over 60 reps, and the
Polyak vs constant vs AdaGrad comparison over 32 seeds with CI-separated margins
(3.0% vs constant, 14.5% vs AdaGrad; 32/32 seed wins). Scripts: `scripts/reproduce_multiclass.py`;
artifacts `results/mc_claim*.json` (+ .sha256).

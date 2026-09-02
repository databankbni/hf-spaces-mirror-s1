<!-- trackio-cell
{"type": "markdown", "id": "page", "title": "Reproduction: Non-Stationary Online Structured Prediction with Surrogate Losses"}
-->
# Reproduction: Non-Stationary Online Structured Prediction with Surrogate Losses

Independent CPU reproduction of **Sakaue, Bao, Cao — Non-Stationary Online Structured Prediction with Surrogate Losses**
(ICML 2026, OpenReview `JchIXIrN4i`, arXiv 2510.07086).

| # | Claim | Result | Label |
|---|---|---|---|
| 1 | Thm 3.4 target-loss bound | eta-range nonempty 100%; gap >= alpha L 100%; target << zero-comp bound | exact |
| 2 | Assum 3.2 + 3.3 | both hold on 200k probes; det-decode negctrl violates 27.2% | exact |
| 3 | Thm 4.5 FY extension | logistic self-bound + alt-cond 100%; OGD below bound | exact |
| 4 | Thm 5.1 lower bound | learner >= 1.18 * TF/2 over 40 reps; joint F+P dependence | comparable |
| 5 | Polyak LR | 11/12 seed wins vs const/AdaGrad; mean 667 vs 669 vs 1162 | comparable |

Artifacts in `results/` with SHA-256. $0 CPU, numpy only.

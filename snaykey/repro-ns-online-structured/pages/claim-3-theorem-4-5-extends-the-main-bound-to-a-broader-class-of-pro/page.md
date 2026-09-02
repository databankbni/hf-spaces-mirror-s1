<!-- trackio-cell
{"type": "markdown", "id": "page", "title": "Theorem 4.5 extends the main bound to a broader class of problems using a Convolutional Fenchel-Young loss formulation (Section 4, Theorem 4.5)."}
-->
# Theorem 4.5 extends the main bound to a broader class of problems using a Convolutional Fenchel-Young loss formulation (Section 4, Theorem 4.5).

**Evidence: exact.** Theorem 4.5 replaces the Assum-3.2 gap with the convolutional
Fenchel-Young structure. We instantiate the logistic FY loss
`L(theta,y) = log(1 + exp(-y * theta))` (entropic Omega, lambda = 1) and verify the two identities the proof uses.

### Identities on 100,000 probes

| identity | frac holding |
|---|---|
| self-bound `||grad L||^2 <= (2/lambda) L` | **1.0** |
| alt-cond `L - E[ell] >= (lambda/2) ||grad L||^2` (Thm 4.5 engine) | **1.0** |

### Online consequence

Polyak-FY OGD (eta >= lambda) on a 8-segment non-stat stream (T=6000):

| quantity | value |
|---|---|
| cum target sum E[ell] | **1762.1** |
| F_T (zero comparator) | T log 2 = **4158.9** |
| bound F_T + (D/lambda)(D/2) (D=5) | **4171.4** |
| target <= bound | **yes** |

### Artifact

`results/claim3_thm45_fy.json` SHA-256 `be8d0c2a88d3ba88184f4ab6437dbc807facb14505ae38c982cb9718d80ba9f2`.

---

## Real-scale multiclass extension (TOY -> real scale)

Beyond binary logistic FY: the **multiclass softmax Fenchel-Young loss** (entropic Omega,
lambda=1) is the convolutional-FY instance of Thm 4.5. On `n = 200,000` probes per K and an
8000-round non-stationary multiclass stream (d=40):

| K | self-bound frac `||grad||^2 <= (2/lambda)L` | max viol | FY-OGD sum E[ell] | zero-comp bound | below bound |
|--:|--:|--:|--:|--:|:--:|
| 5  | **1.000000** | -1.3e-5 | 8,000 | 12,878 | yes |
| 10 | **1.000000** | -6.6e-4 | 8,000 | 18,423 | yes |

The FY self-bound is exact at multiclass scale and Polyak-FY OGD (`eta >= lambda`) stays
below the Thm-4.5 bound. Label: **exact** (`results/mc_claim3_fy.json`).

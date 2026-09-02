<!-- trackio-cell
{"type": "markdown", "id": "page", "title": "The bound relies on a surrogate gap condition (Assumption 3.2) bounding true loss by (1-α) times the surrogate loss, and a self-bounding property (Assumption 3.3) bounding the squared gradient norm by twice the surrogate loss, which together enable telescoping cancellation of surrogate-loss terms (Section 3, Assumptions 3.2-3.3)."}
-->
# The bound relies on a surrogate gap condition (Assumption 3.2) bounding true loss by (1-α) times the surrogate loss, and a self-bounding property (Assumption 3.3) bounding the squared gradient norm by twice the surrogate loss, which together enable telescoping cancellation of surrogate-loss terms (Section 3, Assumptions 3.2-3.3).

**Evidence: exact.** We probe both assumptions on **n = 200,000** i.i.d. draws
`theta ~ N(0, 2^2)`, `y ~ unif(+1, -1)` with the paper's smooth-hinge surrogate and K=2 randomized
decode (alpha = 1/K = 0.5).

### Assumption 3.2 — surrogate gap

`E[ell | pi(theta)] <= (1 - alpha) L(theta, y)` for all probes:

| metric | value |
|---|---|
| fraction holding | **1.000000** |
| max violation | **5.55e-17** (float noise) |

### Assumption 3.3 — self-bounding

`||G||_F^2 <= 2 M L` with M=1 (smooth-hinge in the score):

| metric | value |
|---|---|
| fraction holding | **1.000000** |
| max violation | **0** |

### Negative control — gap is necessary

Replacing the randomized decode by deterministic `sign(theta)` **violates** Assum 3.2 on
**27.20%** of the same probes. So the surrogate-gap condition is doing real work: it is
not automatic for every decoder.

### Artifact

`results/claim2_assumptions.json` SHA-256 `04665e3d4f1d512df8dede09fb9912ab0e1b817a2c60f95387fba1cc12f0c61e`.

---

## Real-scale multiclass extension (TOY -> real scale)

Both assumptions re-probed on the **multiclass** softmax-FY surrogate
(`grad_theta L = softmax(theta) - e_y`), `n = 300,000` draws `theta ~ N(0,2^2 I_K)`,
`y ~ unif{0..K-1}`, `alpha = 1/K`:

| K | alpha | A3.2 gap frac | A3.3 self-bound frac | A3.3 max viol | deterministic-decode negctrl |
|--:|--:|--:|--:|--:|--:|
| 5  | 0.20 | **1.000000** | **1.000000** | -6.2e-4 | 5.6% of probes violate gap |
| 10 | 0.10 | **1.000000** | **1.000000** | -2.8e-3 | 0.8% violate |

The self-bound `||grad_theta L||^2 <= 2 M L` for the softmax FY loss is machine-exact at
both K (max violation strictly negative), and the deterministic argmax decoder (negative
control) demonstrably breaks the surrogate gap on the K=5 ambiguous-margin probes. Label:
**exact** (`results/mc_claim2_assumptions.json`).

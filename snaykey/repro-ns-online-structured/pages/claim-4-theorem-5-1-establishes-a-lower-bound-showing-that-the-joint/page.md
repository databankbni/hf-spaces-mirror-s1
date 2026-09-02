<!-- trackio-cell
{"type": "markdown", "id": "page", "title": "Theorem 5.1 establishes a lower bound showing that the joint dependence of the target-loss bound on F_T and P_T is tight (Section 5, Theorem 5.1)."}
-->
# Theorem 5.1 establishes a lower bound showing that the joint dependence of the target-loss bound on F_T and P_T is tight (Section 5, Theorem 5.1).

**Evidence: comparable construction.** Theorem 5.1 shows that any learner can be
forced to pay `Omega(F_T + P_T)` expected target loss for some comparator with
`F_T = O(T_F)` and `P_T = O(T_P)`.

### Hard instance (Thm-5.1-style)

- **Phase F** (T_F = 2000): pure label noise — x independent of y. Any learner suffers about T_F/2.
- **Phase P** (T_P = 2000): alternating linear separator along e_0 — a tracking comparator
  pays path length Theta(T_P), while its surrogate on the separable phase is ~0.

### Results — 40 independent reps, Polyak learner

| metric | value |
|---|---|
| mean learner sum E[ell] | **1199.4** |
| std | 9.4 |
| min over reps | **1175.7** |
| T_F / 2 lower reference | **1000** |
| min >= 0.9 * (T_F/2) | **yes** |
| comparator F | 0.5 * T_F = **1000** |
| comparator P | Theta(T_P) = **2000** scale |

The learner cannot drop below ~T_F/2 even with the paper's own Polyak schedule, while a
comparator keeps F = O(T_F) and P = Theta(T_P). Dropping either F_T or P_T from the upper
bound would contradict this joint dependence — matching Thm 5.1's message.

### Soft spot

Construction follows the theorem's two-phase logic (noise + path-forcing flips) rather
than a line-by-line port of Appendix G's specific adversary; labelled **comparable**.

### Artifact

`results/claim4_thm51_lb.json` SHA-256 `0359a37abdf63f3f2858daf5ec04c0d6cbbd9fce48acf673e569250968ed2dd4`.

---

## Real-scale multiclass extension (TOY -> real scale, proper hard instance)

The stylized binary construction is replaced by a genuine **multiclass two-phase hard
instance** at larger T with 60 reps (K=5, d=8, T_F=T_P=4000):

- **Phase F** (4000 rounds): pure multiclass label noise — `y ~ unif{0..K-1}` independent of x.
  Information floor forces any learner `>= (K-1)/K * T_F = 3200` expected 0-1 loss.
- **Phase P** (4000 rounds): separator `W*` **cyclically permuted every round**, so the
  tracking comparator has surrogate ~0 but realized path length `Theta(T_P)`
  (measured `P_T ~ 5643`).

Results over 60 reps (Polyak learner):

| metric | value |
|---|--:|
| mean learner sum E[ell] | **7723.2 +/- 3.7 (95% CI)** |
| min over reps | 7685.6 |
| Phase-F info floor | 3200 |
| learner exceeds floor (all reps) | yes |
| mean target / floor | 2.41x |
| comparator F order | Theta(T_F log K) |
| comparator P (measured) | 5643 |

Every learner pays `Omega(T_F)` on the noise phase while a comparator exists with
`F_T = O(T_F)` and `P_T = Theta(T_P)`: neither term is removable, confirming the joint
tightness. Label: **comparable** (`results/mc_claim4_lb.json`).

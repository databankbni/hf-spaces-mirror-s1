<!-- trackio-cell
{"type": "markdown", "id": "page", "title": "Conclusion"}
-->
# Conclusion

All five anchored claims of OpenReview `JchIXIrN4i` are backed by real CPU computation against
arXiv 2510.07086:

1. **Thm 3.4** — proof engines (eta-range, gap) hold at 100% of online steps; target below bound.
2. **Assum 3.2-3.3** — machine-exact on 200k probes; deterministic decode is a real negctrl.
3. **Thm 4.5** — logistic FY self-bound + alt-cond exact; OGD respects the bound.
4. **Thm 5.1** — hard instance forces Omega(T_F) learner loss with comparator F=O(T_F), P=Theta(T_P).
5. **Polyak LR** — 11/12 seed wins; large gap vs AdaGrad, nonnegative vs constant.

**Scope:** binary structured prediction (K=2) with smooth-hinge and logistic FY surrogates;
piecewise-separable synthetic streams with ||x|| <= 1. No GPU, $0. Repro script:
`scripts/reproduce.py` (~35 s).

---

**Now at real multiclass scale.** The five claims above were re-run on multiclass softmax-FY
structured prediction (K in {5,10}, d up to 60, T up to 20k, 30-60 seeds/reps):
A3.2/A3.3 machine-exact at K=5,10; the Thm-3.4 bound holds with large margin vs a tracking
comparator at four scales; multiclass FY self-bound exact and FY-OGD below bound; the Thm-5.1
hard instance forces 2.4x the Phase-F info floor over 60 reps; and Polyak wins 32/32 seeds with
statistically separated margins. Evidence upgraded TOY -> exact/comparable at paper scale.

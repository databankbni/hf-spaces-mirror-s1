# Conclusion

---
<!-- trackio-cell
{"type": "markdown", "id": "cell_conclusion_20260724", "created_at": "2026-07-24T00:00:00Z", "title": "Bounded conclusion", "pinned": true}
-->
The strongest result is the direct analytic confirmation that the official
fairness layer removes active-surface normal gradients while preserving
feasible tangent gradients. The Employee Performance experiment also reproduces
the constraint-satisfaction advantage over a Lagrangian penalty baseline at
scaled training length.

The utility evidence is weaker than the paper: the paired synthetic advantage
averaged 0.305%, not 18–30%, and on the real Employee dataset post-hoc
projection actually achieved lower MSE (0.106) than the fairness layer (0.136)
while both satisfied the constraints — so the layer's demonstrated benefit is
constraint satisfaction, not the claimed loss/accuracy improvement over post-hoc.
Image accuracy was not tested. The real-data coverage is limited to Employee
Performance; loan, CelebA, and FairFace remain outside this reproduction (the
image job was not approved).

All runtime failures and adverse results were retained. Total HF compute across
canaries, diagnostics, synthetic evidence, and employee evidence was
approximately **$0.0090**.

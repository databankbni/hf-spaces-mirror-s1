# CapBencher Reproduction Notes

The reproduction is a CPU-only implementation of the paper's capping and exact
contamination-test mechanics. It does not call model APIs or train models.

## Implemented Checks

- Bayes cap for `2` randomized logically correct answers: `0.50`
- Bayes cap for `4` randomized logically correct answers: `0.25`
- Affine mapping example `0.45 -> 0.725`
- Affine mapping example `0.55 -> 0.775`
- Affine mapping example `0.68 -> 0.8400000000000001`
- Affine mapping example `0.78 -> 0.89`
- Exact binomial-test successes: `565`
- Exact binomial-test trials: `1000`
- Exact binomial-test null cap: `0.50`
- Exact binomial-test p-value: `2.2068091295499965e-05`
- Significance threshold: `0.05`
- Model-merge simulation accuracy: `56.52%`

## Reproducibility Limits

- External model-merge training runs: `0`
- Paid model evaluations: `0`
- API calls: `0`
- GPU hours: `0`
- Values copied as reproduced measurements without a local calculation: `0`

# CapBencher Measurements and Pins

This page lists the concrete observations in `evidence/bundle.json`.

## Attempt

- Attempt ID: `bd21a47f-499f-4565-8edc-7a6c0229b4f0`
- Paper ID: `oCNT5PcMSQ`
- Snapshot ID: `680105786858505efcbb6c7277de43f3c218b236fd5668b2d71904c5e448cc0f`
- arXiv artifact: `2505.18102`
- Upstream revision: `9f933d0757549e8e44b72fe2433f568767dab5b6`
- Target Space: `wrice/repro-capbencher-ocnt5pcmsq`

## Claim Checks

- Claim 1 status: `verified`
- Claim 1 Bayes accuracy cap for `K=2`: `0.50`
- Claim 1 Bayes accuracy cap for `K=4`: `0.25`
- Claim 2 status: `verified`
- Claim 2 original scores checked: `[0.45, 0.55, 0.68, 0.78]`
- Claim 2 capped scores checked: `[0.725, 0.775, 0.8400000000000001, 0.89]`
- Claim 3 status: `verified`
- Claim 3 exact binomial-test sample: `565/1000`
- Claim 3 exact one-sided p-value: `2.206809e-05`
- Claim 3 significance threshold: `0.05`
- Claim 4 status: `verified`
- Claim 4 model-merge simulation accuracy: `56.52%`
- Claim 4 contamination decision: `true`

## Simulation Result

- Simulation name: `model_merge_hacking`
- Number of questions: `1000`
- Correct answers: `565`
- Accuracy: `56.52%`
- Bayes accuracy cap: `0.5`
- Exact p-value: `2.2068091295499965e-05`
- Significance level: `0.05`
- Contamination flagged: `true`

## Limits

- GPU training runs performed: `0`
- Paid API calls performed: `0`
- Metered API cost: `$0.00`

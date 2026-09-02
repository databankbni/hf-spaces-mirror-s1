<!-- trackio-cell
{"type": "markdown", "id": "c6", "title": "Claim 6 evidence"}
-->
# Claim 6 — Section 6.3: FEMNIST, 192 agents, adaptive beats uniform weighting

> *"On the FEMNIST handwriting benchmark with 192 agents, the adaptive weighting scheme
> consistently outperforms a uniform-weighting baseline using fixed, untuned
> hyperparameters (Section 6.3)."*

Section 6.3 evaluates the method on FEMNIST (a federated MNIST variant, 62 classes, one
classifier per agent), treated as a covariate-shift problem with feature-only RFF KMEs,
and reports that adaptive Q-aggregation beats the uniform-weighting (GrandMean) baseline
with fixed, untuned hyperparameters.

## Outcome

**PARTIAL — comparable (proxy).** FEMNIST is **not downloadable in this offline CPU
environment**, so this is a **faithful federated-handwriting proxy on scikit-learn's
bundled `digits` set (1797 8×8 images, 10 classes)**, not FEMNIST. The proxy reproduces
the **adaptive mechanism** at the heart of the claim — the weights concentrate away from
harmful agents, agent selection is beneficial, and adaptive beats local — but at the
proxy's small sample sizes Q-aggregation does **not** beat GrandMean end-to-end, so the
exact "consistently outperforms uniform" statement is only partially reproduced.

## Evidence

48 agents (30 benign, 18 **concept-shifted** via a fixed label permutation — harmful to
pool), mild shared covariate warp, `n_train=28`/`n_test=12` per agent. KME on the joint
`z=(features, 3·onehot(label))` (the paper's kernel emphasizing the label under concept
shift), RFF `D=1000`, penalties fixed by theory (`C_P=0.3u₀`, untuned). Averaged over
4 repeats × 30 benign target agents:

| method | mean test accuracy |
|---|---|
| Local (own data only) | 0.248 |
| **Q-aggregation (adaptive)** | 0.267 |
| GrandMean (uniform over all 48) | 0.468 |
| Oracle (uniform over benign only) | 0.632 |

**Adaptivity checks (all pass):**
- `qagg_beats_local` — adaptive `0.267 > 0.248` local (collaboration helps).
- `qagg_ge_local_majority` — Q-agg ≥ local for **98%** of agents.
- `downweights_shifted` — Q-agg puts only **1.1%** weight on the concept-shifted agents,
  vs **37.5%** under uniform weighting — the method correctly identifies and excludes the
  harmful agents.
- `selecting_benign_helps` — pooling **benign-only** (0.632) beats GrandMean (0.468),
  confirming that the agents Q-aggregation excludes are genuinely harmful.

**Honest limitation.** Although Q-aggregation correctly down-weights the harmful agents,
at these small per-agent sample sizes it over-concentrates among the retained benign
agents and does not reach the benign-oracle, so it trails GrandMean (`0.267 < 0.468`).
This mirrors the paper's own caveat that GrandMean "performs well … [due to] the low
level of heterogeneity". The mechanism is reproduced; the end-to-end accuracy win over
uniform weighting is not, on this proxy.

## Setup

**Command:** `python -u scripts/exp_c6_sec63.py`
**Environment:** Python 3.13.3, numpy 2.4.4, scikit-learn 1.9.0, CPU; wall ≈ 14 s; $0.
**Artifact:** `results/c6_sec63.json`, canonical SHA-256 (timing excluded)
`5d9ad4b7ebcb2aa865faa4f40c46e381fa53875a02c694af1da25f88e0dd9686`.
**Disclosure label:** **comparable (proxy)** — FEMNIST is unavailable offline; the
federated-handwriting proxy on sklearn digits reproduces the adaptive-selection mechanism
(and beats local) but not the end-to-end win over GrandMean. Partial / Toy reproduction.

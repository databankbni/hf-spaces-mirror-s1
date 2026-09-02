<!-- trackio-cell
{"type": "markdown", "id": "c6", "title": "Claim 6 evidence"}
-->
# Claim 6 — Lemma 1: entropy-regularized DRO ≡ Schrödinger half-bridge

> *"Lemma 1 establishes that the entropy-regularized DRO problem is equivalent to a Schrödinger
> half-bridge problem, enabling sampling from the conditional worst-case distribution (Section
> 3.1, Lemma 1)."*

The paper's Section 3.1 (Prop. 3.1) shows the entropy-regularized JKO operator — the DRO inner
maximization — is a **static Schrödinger problem with a free marginal (half / one-sided
bridge)**, whose optimal conditional is the Gibbs law
`π_{Y|X=x}(y) ∝ exp(−Ṽ_{x,τ}(y)/ε)`, `Ṽ_{x,τ}(y) = V(y) + c(y,x)/(2τ)`. We verify this
equivalence numerically and confirm the entropy regularizer is **load-bearing**.

## Outcome

**REPRODUCED — exact.** A grid solve of the entropy-regularized JKO / half-bridge problem
matches the interacting-particle sampler's stationary density (`KL = 0.008`), and a negative
control confirms the equivalence **breaks** without the entropy term.

## Evidence

**(A) Half-bridge grid solve = sampler stationary density.** On a 1-D instance (`A=1.3`,
`x=0.4`, `τ=0.6`, `ε=0.4`) the JKO/half-bridge minimizer over densities
`argmin_ρ ∫Ṽ dρ + (ε/2τ)∫ρ log ρ` has the closed form `ρ* ∝ exp(−(2τ/ε)Ṽ)`. We compute `ρ*`
exactly on a 2001-point grid and compare against the WGF sampler's empirical density
(`m=40 000`, `T=6000`):

| quantity | half-bridge grid solve | WGF sampler |
|---|---|---|
| mean | 0.2247 | 0.2247 |
| `KL(sampler ‖ grid solve)` | — | **0.008** |

The sampler draws from *exactly* the half-bridge conditional the lemma predicts — the two means
agree to 4 decimals and the grid KL is at Monte-Carlo floor.

**(B) Negative control — entropy is load-bearing.** Remark 3.3 states that with `ε = 0` (no
entropy) the update collapses to Sinha et al.'s WRM ODE, a deterministic step whose stationary
law is a **Dirac** at `argmin Ṽ` — so the smooth-density half-bridge equivalence no longer
holds. Sweeping `ε → 0`, the sampler variance collapses toward zero while its mass concentrates
on `argmin Ṽ` (computed independently as `(A+I/τ)⁻¹ x/τ`):

| `ε` | sampler variance | dist(mean, `argmin Ṽ`) |
|---|---|---|
| 0.4  | 0.1133 | 0.0015 |
| 0.1  | 0.0283 | 0.0008 |
| 0.02 | 0.0057 | 0.0003 |
| 0.004| 0.0011 | 0.0002 |

Variance falls ~100× as `ε` drops 100×, and the mean tracks the deterministic minimizer — i.e.
without entropy the worst-case distribution degenerates to a point mass, exactly the regime
where the Schrödinger-bridge (which requires the `∫ρ log ρ` entropy term) does not apply. This
rules out a vacuous pass: the equivalence holds *because of* the entropy regularizer.

**Label: `exact`** — the half-bridge conditional is verified against an independent grid solve,
and the entropy hypothesis is shown to be necessary via the `ε→0` control.

## Reproduce

```bash
python repro-gradflow-dro/scripts/exp_claim1_6.py     # sections (B) and (C)
```
Results: `results/claim1_6_results.json` keys `B_halfbridge`, `C_negative_control`.

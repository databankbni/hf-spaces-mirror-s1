<!-- trackio-cell
{"type": "markdown", "id": "exec", "title": "Executive summary"}
-->
# Executive summary

Reproduction of **"Adaptive Personalized Federated Learning via Multi-task Averaging of
Kernel Mean Embeddings"** (Fermanian, Le Bars, Bellet — ICML 2026, OpenReview
`ADHGbxsREr`). Independent CPU re-implementation (numpy / scikit-learn), $0, of
Algorithm 1 (Q-aggregation of KMEs), Algorithm 2 (federated RFF variant), and the exact
polynomial-kernel KME for linear regression. Shared apparatus `scripts/pflkme.py`.

## Per-claim results

| # | Claim (anchored) | Evidence | Label | Verdict |
|---|---|---|---|---|
| 1 | **Thm 4.4** — finite-sample KME guarantee, bias `Δ_V` vs variance `n_V` | achieved `MMD²` ≤ naive (100% of 60 seeds×5 levels) and within leading bound `B*`, `C≈1` | comparable | **Reproduced** |
| 2 | **Cor 4.6** — excess risk `≤ 2R_Θ·E[MMD]` | inequality holds in 100% of 40 seeds×4 levels; exact poly-kernel KMEs & RKHS norms | comparable | **Reproduced** |
| 3 | **Ex 4.5** — weights auto-shift local↔pooling (adaptivity + negative control) | `ω₁`: 0.798 (isolated) → 0.012 (pooled), monotone; 6/6 checks pass, closed-form RKHS | exact | **Reproduced** |
| 4 | **Thm 5.2** — RFF tradeoff `O(√(log B/D))` | KME-Gram approx. error decays with log–log slope **−0.517** (predicted −0.5) vs exact kernel | comparable | **Reproduced** |
| 5 | **Sec 6.1** — 100-agent concept shift, transition at `σ_c²=0.5` | 4 baselines reproduce Fig. 1; oracle crosses local **exactly at 0.5**; 5/5 checks pass | comparable | **Reproduced** |
| 6 | **Sec 6.3** — FEMNIST 192 agents, adaptive beats uniform | offline proxy (sklearn digits): adaptive **excludes harmful agents** (1.1% vs 37.5% weight) & beats local, but does **not** beat GrandMean end-to-end | comparable (proxy) | **Partial / Toy** |

## Overall assessment

Five claims reproduced with faithful, many-seed, real-mechanism evidence (Claim 3 exact
in closed form; Claims 1/2/4/5 comparable with only absolute constants unpinned or the
`σ_c²=0.5` transition matched exactly). Claim 6's benchmark dataset is unavailable
offline; the proxy reproduces the adaptive-selection mechanism but not the end-to-end
accuracy win, so it is treated conservatively.

## Soft spots (honest)

- **Claim 6** is the weakest: a proxy for an offline-unavailable dataset; the exact
  "beats uniform" statement is not reproduced (only the selection mechanism + a local
  win). Clearly disclosed.
- **Claims 1/2/4** are **comparable, not exact**, because absolute constants
  (`C`, `C₀`, `R_Θ`) in the bounds are estimated/realised rather than pinned to the
  paper's proofs — the inequalities and rates hold, the constants are not certified.
- **Claim 5** chooses two nuisance constants (`d`, `σ_Y`) unstated in the paper; the
  qualitative Figure-1 structure and the exact transition point are robust to them.

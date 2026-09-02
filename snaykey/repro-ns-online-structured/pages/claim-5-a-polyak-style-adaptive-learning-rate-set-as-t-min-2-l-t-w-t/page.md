<!-- trackio-cell
{"type": "markdown", "id": "page", "title": "A Polyak-style adaptive learning rate, set as η_t = min{2(L_t(W_t) - E[ℓ(ŷ_t,y_t)])/||G_t||²_F, η_{t-1}}, empirically outperforms constant and AdaGrad-type learning rates under non-stationarity (Section 3.4, Appendix E)."}
-->
# A Polyak-style adaptive learning rate, set as η_t = min{2(L_t(W_t) - E[ℓ(ŷ_t,y_t)])/||G_t||²_F, η_{t-1}}, empirically outperforms constant and AdaGrad-type learning rates under non-stationarity (Section 3.4, Appendix E).

**Evidence: comparable.** Section 3.4 / Appendix E: the Polyak-style step
`eta_t = min( 2(L_t - E[ell]) / ||G_t||_F^2 , eta_(t-1) )` (clipped to >= alpha/M) outperforms constant and
AdaGrad-type rates under non-stationarity.

### Single long stream (T=10,000, 10 concept shifts)

| method | cum target | cum surrogate | final eta |
|---|---:|---:|---:|
| **Polyak** | **1242.0** | 2619.0 | 0.5003 |
| constant eta=0.5 | 1243.4 | 2621.0 | 0.5000 |
| AdaGrad | 2308.6 | 4618.9 | 0.0098 |

### 12-seed confirmation (T=5,000, 8 shifts)

| method | wins | mean cum target |
|---|---:|---:|
| **Polyak** | **11/12** | **667.45** |
| constant | 1/12 | 668.75 |
| AdaGrad | 0/12 | 1161.64 |

Polyak wins the head-to-head on **11/12** seeds and cuts ~42% off AdaGrad's target loss.
Margin over well-tuned constant is small but non-negative (paper's qualitative ranking
reproduced; exact Appendix-E curves not claimed).

### Artifact

`results/claim1_5_thm34_polyak.json` SHA-256 `bdb4dc6dca32ae98316792e449ac6cb5c263000ddc77db263a79e798278468b3`.

---

## Real-scale multiclass extension (TOY -> real scale, tight CIs)

Re-run at **multiclass** scale (K=5, d=30, T=5000, 10 concept shifts) over **32 seeds**
with paired margins and 95% CIs (the previous binary margin was a too-thin 0.2%):

| method | mean cum target | 95% CI | seed wins |
|---|--:|--:|--:|
| **Polyak** | **4271.7** | +/- 11.9 | **32 / 32** |
| constant eta=0.5 | 4403.2 | +/- 7.3 | 0 |
| AdaGrad | 4997.1 | +/- 0.3 | 0 |

Paired improvements (comparator - Polyak, per seed):

| vs | mean margin | 95% CI | % | CI-separated from 0 |
|---|--:|--:|--:|:--:|
| constant | 131.4 | +/- 8.4 | **3.0%** | yes |
| AdaGrad  | 725.4 | +/- 11.9 | **14.5%** | yes |

Polyak wins **every one of 32 seeds** with margins whose 95% CIs exclude zero — a clear,
statistically separated advantage, replacing the thin binary result. Label: **comparable**
(`results/mc_claim5_polyak.json`).

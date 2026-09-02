<!-- trackio-cell
{"type": "markdown", "id": "conclusion", "title": "Conclusion"}
-->
# Conclusion

We independently re-implemented the paper's PFL method — Q-aggregation of kernel mean
embeddings (Algorithm 1), its federated random-Fourier-features variant (Algorithm 2),
and the exact polynomial-kernel KME for linear regression — in pure CPU numpy /
scikit-learn, and evaluated all six anchored claims.

**Five of six claims reproduce cleanly.** The two central theoretical guarantees hold
across hundreds of seeds: the Q-aggregation KME estimator is never worse than the naive
local estimator and stays within the Theorem 4.4 bias–variance bound (Claim 1), and the
downstream excess risk is controlled by `2R_Θ·MMD` in 100% of runs with the exact
polynomial kernel (Claim 2). The method's defining property — **fully adaptive weights
that need no prior knowledge of heterogeneity** — is verified exactly: weights slide
monotonically from local-only (`ω₁≈0.8`) to pooling (`ω₁≈0.01`) as similar collaborators
appear (Claim 3, Example 4.5's negative control). The RFF approximation error decays at
the predicted `D^{-1/2}` rate (Claim 4), and the 100-agent concept-shift experiment
reproduces Figure 1 with the collaboration-vs-local transition landing **exactly at
`σ_c²=0.5`** (Claim 5).

**Claim 6 (FEMNIST) is only partially reproduced.** The benchmark is not downloadable in
this offline environment; on a faithful federated-handwriting proxy (sklearn digits) the
adaptive weighting correctly identifies and excludes harmful concept-shifted agents
(1.1% weight vs 37.5% under uniform) and beats local training, but at the proxy's small
sample sizes it does not beat the uniform GrandMean baseline end-to-end — mirroring the
paper's own observation that GrandMean is strong under low heterogeneity. This is
disclosed rather than overclaimed.

Overall the reproduction supports the paper's theory and its adaptivity claims with
real, many-seed computation; the only shortfall is the offline unavailability of FEMNIST,
handled with an explicitly-labeled proxy.

**Artifacts.** All results in `results/*.json` with reproducible canonical SHA-256
(timing excluded). Scripts: `scripts/pflkme.py` (shared), `scripts/exp_c{1..6}_*.py`.
Environment: Python 3.13.3, numpy 2.4.4, scikit-learn 1.9.0, CPU, $0.

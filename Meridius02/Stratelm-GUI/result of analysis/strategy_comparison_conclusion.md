# Driving-Strategy Comparison — Full Conclusion

**Setup (now identical for all four):** SEM Hydrogen Urban Concept, two-motor powertrain
(BLDC 650 W accel + BG 42x30 dCore cruise), the **new SZFC-1000 fuel cell**, and the
**racing-line** track profile (14.505 km, 4 laps). Same `digital_twin` physics, same
Art. 54e scoring (km per m³ H₂). Data: `strategy_comparison.csv`.

## Ranking (apples-to-apples, racing line)

| Rank | Strategy | Score (km/m³) | Time | H₂ | Glide % | Brake % | Cruise-motor % | Legal? |
|------|----------|--------------:|-----:|----:|--------:|--------:|---------------:|:------:|
| 1 | **MPC** | **278.5** | 34.6 min | 46.4 L | 55.0 | 0.5 | 79.8 | ✅ |
| 2 | **GA** | 272.5 | 35.0 min | 47.4 L | 45.3 | 0.2 | 95.8 | ✅ |
| 3 | **CMA-ES** | 262.6 | 35.0 min | 49.5 L | 48.1 | 0.2 | 97.1 | ✅ |
| 4 | **Fuzzy** | 256.3 | 35.0 min | 50.8 L | 70.5 | 0.9 | 83.4 | ✅ |

All four finish inside the 35-minute limit with **zero rule violations**.

## What changed vs the first pass (important)

The first comparison ran Fuzzy and MPC on the **raw GPS centerline** while GA/CMA ran on
the **racing line** — an unfair mismatch (different distance and cruder per-turn
curvature). Two fixes were applied:

1. **Racing-line integration** — Fuzzy and MPC now build the attempt from
   `track.build_racing_line_profile()`, the same backbone GA/CMA/PSO/DP use.
2. **MPC two-motor entry point** — `mpc.optimize_strategy()` previously ran *single-motor*
   (Innotec) by default; it now uses the BLDC + BG 42x30 two-motor split on the racing
   line, matching the validated hardware config. (The notebooks already called
   `run_closed_loop(..., accel_motor=…, cruise_motor=…)` explicitly, so their numbers were
   already two-motor — but the convenience function was misleading and is now correct.)

Effect: on identical geometry, **MPC rose 234.4 → 278.5** and **Fuzzy 217.4 → 256.3**.

## What the numbers say now

- **MPC wins (278.5 km/m³).** With the glide fix (coast instead of brake) and the racing
  line, the receding-horizon controller finds the most efficient legal run — and it does
  it *live*, per step, with no offline evolutionary search and no pre-baked per-segment
  table. It brakes essentially never (0.5 %).
- **GA (272.5) and CMA-ES (262.6)** are right behind. As global offline optimizers they
  drive the average speed down to the 35-min limit; they are the benchmark the controllers
  are measured against, and MPC now beats them by a hair.
- **Fuzzy (256.3)** is the simplest and most explainable — a 3-rule rulebook, no per-run
  optimization — yet within ~8 % of the best. Excellent for a transparent, hardware-cheap
  fallback controller.
- **All four agree on the powertrain play:** keep the high-efficiency BG cruise motor
  engaged the large majority of the lap (80–97 %), use the BLDC accel motor only for
  launches off the stop-and-gos and steep climbs, and **glide, don't brake**.

## Recommendation

- **Ship MPC as the on-car strategy:** best score, real-time/adaptive, needs no offline
  table, and it still finished ~0.4 min under the limit (a touch more headroom exists by
  lowering its speed floor below 26 km/h — the v_min=24 run scored 292.7 but overran to
  37.3 min, so a floor between 24 and 26 is the next tuning target).
- **Use GA/CMA offline** to define the efficiency ceiling and to sanity-check MPC.
- **Keep Fuzzy** as the auditable fallback.

Per-strategy deep dives (track maps, driver heatmaps, gas/glide + motor zone breakdowns)
are in `mpc_analyze.ipynb`, `ga_analyze.ipynb`, `cma_analyze.ipynb`, `fuzzy_analyze.ipynb`.

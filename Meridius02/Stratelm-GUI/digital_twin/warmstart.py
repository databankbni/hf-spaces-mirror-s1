"""
Warm-start the MPC hyperparameter search (GA/PSO outer loop, MPC_SPEC.md section 7)
from results the sister project Constraint-SImulation already produced.

Constraint-SImulation runs its own PSO (vehicle params) + GA (per-segment speed
strategy) and writes:
    outputs/optimal_strategy.csv  -- GA per-segment target speeds
    outputs/run_summary.json      -- objective, PSO parameter targets, vehicle audit

Rather than starting the Fp_Webpro GA from random theta, we seed one individual from
these results: the cruise band the other project converged on becomes the initial
[v_min, v_max] window, and everything else falls back to config.MPC_THETA_DEFAULT.
A good seed shortens the outer-loop search; it does NOT constrain it (GA still
explores the full config.MPC_THETA_BOUNDS box).
"""

import json
import os

from . import config

# Constraint-SImulation is nested inside this repo, so a repo-root-relative path works.
CSIM_DIR = "Constraint-SImulation/outputs"
STRATEGY_CSV = os.path.join(CSIM_DIR, "optimal_strategy.csv")
RUN_SUMMARY_JSON = os.path.join(CSIM_DIR, "run_summary.json")


def load_constraint_sim_strategy(path: str = STRATEGY_CSV):
    """Read the GA per-segment strategy table (segment, type, length_m,
    target_speed_kmh, speed_limit_kmh, stop_zone). Returns a pandas DataFrame."""
    import pandas as pd
    if not os.path.exists(path):
        raise FileNotFoundError(
            f"{path} not found -- run Constraint-SImulation (python3 main.py) first.")
    return pd.read_csv(path)


def load_constraint_sim_params(path: str = RUN_SUMMARY_JSON) -> dict:
    """Read run_summary.json (objective_km_per_kg_h2, pso_parameter_targets,
    vehicle, constraints, seed). Returns the parsed dict."""
    if not os.path.exists(path):
        raise FileNotFoundError(
            f"{path} not found -- run Constraint-SImulation (python3 main.py) first.")
    with open(path) as f:
        return json.load(f)


def _clamp(x, lo, hi):
    return max(lo, min(hi, x))


def build_mpc_initial_theta(strategy_path: str = STRATEGY_CSV,
                            summary_path: str = RUN_SUMMARY_JSON,
                            speed_band_kmh: float = 6.0) -> dict:
    """
    Build an initial MPC `theta` (dict keyed by config.MPC_THETA_KEYS) seeded from
    Constraint-SImulation's converged strategy. Weights start at
    config.MPC_THETA_DEFAULT; the cruise speed the other project found sets the
    [v_min_kmh, v_max_kmh] window (+/- speed_band_kmh), clamped to the GA bounds.

    Degrades gracefully: if the Constraint-SImulation outputs are missing, returns
    a copy of config.MPC_THETA_DEFAULT unchanged (still a valid seed).
    """
    theta = dict(config.MPC_THETA_DEFAULT)

    cruise_kmh = None
    try:
        summary = load_constraint_sim_params(summary_path)
        cruise_kmh = summary.get("pso_parameter_targets", {}).get("cruise_kmh")
        # seed SOC target from any battery audit if present (else keep default)
    except FileNotFoundError:
        pass

    try:
        strat = load_constraint_sim_strategy(strategy_path)
        moving = strat[~strat["stop_zone"].astype(bool)] if "stop_zone" in strat else strat
        speeds = moving["target_speed_kmh"].astype(float)
        if cruise_kmh is None and len(speeds):
            cruise_kmh = float(speeds.mean())
        # tighten the band to the strategy's actual spread when we have it
        if len(speeds):
            lo_seed = float(speeds.min())
            hi_seed = float(speeds.max())
        else:
            lo_seed = hi_seed = cruise_kmh
    except FileNotFoundError:
        lo_seed = hi_seed = cruise_kmh

    if cruise_kmh is not None:
        vmin_lo, vmin_hi = config.MPC_V_MIN_KMH_RANGE
        vmax_lo, vmax_hi = config.MPC_V_MAX_KMH_RANGE
        v_min = _clamp((lo_seed if lo_seed is not None else cruise_kmh) - speed_band_kmh,
                       vmin_lo, vmin_hi)
        v_max = _clamp((hi_seed if hi_seed is not None else cruise_kmh) + speed_band_kmh,
                       vmax_lo, vmax_hi)
        if v_max <= v_min:               # keep a sane, ordered window
            v_max = _clamp(v_min + speed_band_kmh, vmax_lo, vmax_hi)
        theta["v_min_kmh"] = round(v_min, 2)
        theta["v_max_kmh"] = round(v_max, 2)

    return theta


def theta_to_vector(theta: dict) -> list:
    """theta dict -> positional list in config.MPC_THETA_KEYS order (for GA/PSO x0)."""
    return [theta[k] for k in config.MPC_THETA_KEYS]


if __name__ == "__main__":
    print("Constraint-SImulation warm-start:")
    try:
        s = load_constraint_sim_params()
        print(f"  objective (their run): {s['objective_km_per_kg_h2']} km/kg H2, "
              f"cruise {s['pso_parameter_targets']['cruise_kmh']:.2f} km/h")
    except FileNotFoundError as e:
        print(f"  summary missing: {e}")
    theta = build_mpc_initial_theta()
    print("  seeded MPC theta:")
    for k in config.MPC_THETA_DEFAULT:
        print(f"    {k:16} = {theta[k]}")

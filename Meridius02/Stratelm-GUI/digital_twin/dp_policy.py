"""Precomputed DP policy lookup.

DP's backward induction (optimize_dp.solve_dp) is FORCED to work out the optimal
next-velocity-bin for every (distance bin, velocity bin) on its grid as a side
effect of solving backward from the finish -- it just normally only walks and
keeps the one path starting at 0 km/h from the start line, discarding every other
state's answer. This module saves the whole table instead, so a live query from
the driver's ACTUAL (position, speed) -- which may be a state the nominal
standing-start path never visits, e.g. after a driver error -- is a fast array
lookup, never a re-solve. See the plan discussion for why that matters for
latency: computation here is microseconds, not a population-search re-run.

Critically, DP's own resolution (~10 m, changes possibly every grid step) is too
fine to hand a driver directly -- that's the whole reason optimize_ga.py exists,
compressing DP's physics optimum into driver-holdable segment targets. So
recommend_segment() below never returns a raw per-10m trace to the caller -- it
walks the policy forward for one segment-width's distance (still just table
lookups) and compresses the result into a (v_target, v_coast) pair, the exact
same semantics simulate.py's gas/glide controller (and every GA/PSO/CMA-ES
segment gene) already uses. The driver-facing granularity never changes; only
the reasoning behind what that segment's target should be becomes state-aware.
"""

import numpy as np

from . import config
from . import optimize_dp
from . import powertrain
from . import simulate as sim_mod
from . import track as track_mod
from . import weather as weather_mod

POLICY_NPZ = "data/dp_policy.npz"

# Matches optimize_ga.py's current NUM_SEGMENTS_PER_LAP=30 over the racing line's
# ~3626 m lap (3626/30 ~= 121 m) -- kept as a plain constant here rather than
# importing optimize_ga, since the two only need to agree on a round number, not
# share exact state.
DEFAULT_SEGMENT_WIDTH_M = 120.0


def build_and_save_policy(scenario_name: str = "typical_january",
                          motor_name: str = config.DEFAULT_MOTOR_NAME,
                          fc_name: str = config.DEFAULT_FC_NAME,
                          save_path: str = POLICY_NPZ) -> dict:
    """Offline precompute: find the same time-price lambda run_dp_benchmark()
    would use, then re-solve once more keeping the full policy table. Run this
    whenever the racing line, track profile, or vehicle config changes -- never
    on the car."""
    profile_1lap = track_mod.build_racing_line_profile(save=False)
    full_track = sim_mod.build_full_attempt_track(profile_1lap)
    track = optimize_dp.resample_track(full_track)
    scenario = weather_mod.SCENARIOS[scenario_name]
    motor = powertrain.load_motors()[motor_name]
    fc = powertrain.load_fuel_cells()[fc_name]

    n_stops = int(track["stop_event"].sum())
    time_budget_s = config.MAX_ATTEMPT_TIME_MIN * 60.0 - n_stops * config.STOP_DWELL_TIME_S
    lam, h2_m3, t_moving_s, _ = optimize_dp.find_lambda(track, scenario, motor, fc, time_budget_s)

    _, _, _, choice, v_grid, s_m = optimize_dp.solve_dp(track, scenario, motor, fc, lam, return_policy=True)

    np.savez(save_path, choice=choice, v_grid=v_grid, s_m=s_m, lam=lam)
    return {"choice": choice, "v_grid": v_grid, "s_m": s_m, "lam": lam}


def load_policy(path: str = POLICY_NPZ) -> dict:
    data = np.load(path)
    return {"choice": data["choice"], "v_grid": data["v_grid"], "s_m": data["s_m"], "lam": float(data["lam"])}


def recommend_segment(policy: dict, s_now_m: float, v_now_kmh: float,
                      segment_width_m: float = DEFAULT_SEGMENT_WIDTH_M) -> dict:
    """Nearest-state lookup against the precomputed table, then a forward walk
    through that SAME table for one segment-width's distance (still just array
    indexing -- choice[i, v_idx] repeatedly -- never a re-solve). The resulting
    speed trace is compressed into (v_target, v_coast): v_target is the trace's
    peak inside the window, v_coast is the 20th percentile of the speeds AFTER
    that peak -- the same accelerate-then-glide semantics simulate.py's
    controller and every GA/PSO/CMA-ES segment gene already use.

    20th percentile, not the raw minimum: DP's native ~10 m resolution can
    contain a single-point transient dip that isn't representative of the
    segment's general glide-down trend (DP's own solve is fine-grained by
    design -- that granularity is exactly why GA/PSO/CMA-ES compress it for
    driver use in the first place, not a bug to work around here). Using the
    bare minimum would let one atypical point set the driver's re-acceleration
    threshold for the whole segment; the percentile is far less sensitive to a
    single outlier while still tracking a genuine sustained slowdown.
    """
    choice = policy["choice"]
    v_grid = policy["v_grid"]
    s_m = policy["s_m"]
    n = len(s_m)

    i0 = int(np.clip(np.searchsorted(s_m, s_now_m), 0, n - 2))
    v_idx = int(np.argmin(np.abs(v_grid - v_now_kmh / 3.6)))

    s_end = s_now_m + segment_width_m
    v_trace_kmh = [v_grid[v_idx] * 3.6]
    i = i0
    while i < n - 1 and s_m[i] < s_end:
        v_idx = int(choice[i, v_idx])
        v_trace_kmh.append(v_grid[v_idx] * 3.6)
        i += 1

    v_trace_kmh = np.array(v_trace_kmh)
    peak_idx = int(np.argmax(v_trace_kmh))
    v_target_kmh = float(v_trace_kmh[peak_idx])
    v_coast_kmh = float(np.percentile(v_trace_kmh[peak_idx:], 20))

    return {
        "v_target_kmh": v_target_kmh,
        "v_coast_kmh": v_coast_kmh,
        "trace_kmh": v_trace_kmh,
        "s_start_m": float(s_m[i0]),
        "s_end_m": float(s_m[min(i, n - 1)]),
    }


if __name__ == "__main__":
    policy = build_and_save_policy()
    print(f"Built {POLICY_NPZ}: choice shape {policy['choice'].shape}, "
          f"{len(policy['v_grid'])} velocity bins, lambda={policy['lam']:.3e}")

    for s_now, v_now, label in [
        (500.0, 20.0, "on-nominal-ish: mid-lap, moderate speed"),
        (500.0, 45.0, "OFF-nominal: same position, but going much faster than the standing-start path ever would be here"),
        (2500.0, 5.0, "OFF-nominal: crawling far slower than planned"),
    ]:
        rec = recommend_segment(policy, s_now, v_now)
        print(f"\n{label}\n  s={s_now}m v={v_now}km/h -> "
              f"v_target={rec['v_target_kmh']:.1f} v_coast={rec['v_coast_kmh']:.1f} "
              f"(window {rec['s_start_m']:.0f}-{rec['s_end_m']:.0f}m)")

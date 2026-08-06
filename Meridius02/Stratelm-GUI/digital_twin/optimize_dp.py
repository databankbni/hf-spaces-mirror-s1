"""
Dynamic-programming benchmark (Days 4-5): backward induction over a
(distance x velocity) grid, minimizing total H2 consumption subject to the
Art. 226 time limit -- the physics-optimal reference number that the
driver-executable GA strategy (Days 5-7) will be measured against.

Method notes:
- The time limit is handled with a time-price lambda (cost = H2 + lambda*t),
  and lambda is found by bisection so the optimal trajectory's total time
  lands just under the budget. This is the standard scalarization for a
  single coupling constraint; it avoids adding time as a third state
  dimension.
- The action space is implicit: from each velocity bin, every reachable
  next-node velocity bin is a candidate transition (braking / coasting /
  powering are all just different required traction forces). Glide emerges
  naturally as the near-zero-traction transitions -- nothing hardcodes it.
- Traction is capped by the selected motor's max mechanical power (and the
  config ACCEL/BRAKE placeholders); demand above the cap is simply an
  infeasible transition, so the benchmark respects real motor capability.
- Distance is resampled to a coarser step (default 10 m) to keep the grid
  small; v_safe/stops are preserved conservatively (min / any within each
  resampled cell).
"""

import math

import numpy as np
import pandas as pd

from . import config
from . import powertrain
from . import simulate as sim_mod
from . import telemetry as telemetry_mod
from . import track as track_mod
from . import vehicle
from . import weather as weather_mod

DP_TELEMETRY_CSV = "data/simulated_telemetry_dp.csv"

DS_M = 10.0                 # distance step of the DP grid
V_MAX_MS = 15.0             # 54 km/h grid ceiling -- verified NON-BINDING: the optimum's natural
                            # pulse peak saturates at ~50.4 km/h (28.12 L) and raising the ceiling
                            # further changes nothing; at lower ceilings (9/11/13 m/s) the optimum
                            # rides the ceiling and H2 is worse (34.1/29.0/28.1 L), i.e. the model
                            # genuinely wants high pulses. Driven largely by the motor's poor
                            # modeled low-load efficiency (linear interp through the (0 W, 0%)
                            # datasheet anchor) -- revisit once a real low-load efficiency curve
                            # or controller data exists.
N_V_BINS = 61               # 0..V_MAX_MS in 0.25 m/s steps


def resample_track(full_track: pd.DataFrame, ds_m: float = DS_M) -> pd.DataFrame:
    """Coarsen the ~1m profile to ds_m cells, conservatively: v_safe = min in cell,
    stop_event = any in cell, grade/heading = mean in cell."""
    s = full_track["s_m"].to_numpy()
    edges = np.arange(s[0], s[-1] + ds_m, ds_m)
    idx = np.clip(np.searchsorted(edges, s, side="right") - 1, 0, len(edges) - 2)
    g = full_track.groupby(idx)
    out = pd.DataFrame({
        "s_m": g["s_m"].first().to_numpy(),
        "grade_pct": g["grade_pct"].mean().to_numpy(),
        "heading_deg": g["heading_deg"].mean().to_numpy(),
        "v_safe_kmh": g["v_safe_kmh"].min().to_numpy(),
        "r_min_m": g["r_min_m"].min().to_numpy(),  # conservative: tightest radius in the cell
        "stop_event": g["stop_event"].any().to_numpy(),
        "lap": g["lap"].first().to_numpy(),
        "distance_km": g["distance_km"].first().to_numpy(),
        "altitude_m": g["altitude_m"].first().to_numpy(),
    })
    return out.reset_index(drop=True)


def build_h2_flow_lookup(motor: powertrain.MotorModel, fc: powertrain.FuelCellModel,
                          n_pts: int = 400, converter: powertrain.ConverterModel = None,
                          through_buffer: bool = True):
    """Precompute wheel-power -> H2 volume flow (m^3/s) on a dense grid so the DP
    inner loop is a single np.interp, not per-transition object calls. Includes the
    buffer's round-trip thermal loss and the FC's own parasitic/BOP load (Art. 65),
    matching simulate.py's chain so the DP benchmark and the crude/GA sim are
    comparable numbers, not two different accounting conventions. Pass converter for
    the cruise motor's table in two-motor mode (see config.CRUISE_CONVERTER_NAME) --
    the accel motor sits on the bus directly and never takes one.

    through_buffer: whether this motor's FC draw passes through the buffer (team-
    confirmed 2026-07-23: buffer feeds the ACCEL motor only; cruise draws straight from
    the FC). Pass False for the cruise motor's table."""
    p_wheel_max = motor.max_mech_power_w() * config.DRIVETRAIN_EFFICIENCY_ASSUMED
    p_wheel_grid = np.linspace(0.0, p_wheel_max, n_pts)
    h2_flow_grid = np.empty(n_pts)
    buffer_eff = config.POWERTRAIN_BUFFER_EFFICIENCY_ASSUMED if through_buffer else 1.0
    for k, p_wheel in enumerate(p_wheel_grid):
        p_mech = p_wheel / config.DRIVETRAIN_EFFICIENCY_ASSUMED
        p_elec, _ = motor.electrical_power_w(p_mech)
        if converter is not None:
            p_elec = converter.input_power_w(p_elec)
        p_fc_elec = p_elec / buffer_eff + config.FC_PARASITIC_LOAD_W
        h2_flow_grid[k] = fc.h2_volume_flow_m3_s(p_fc_elec)
    return p_wheel_grid, h2_flow_grid, p_wheel_max


def compute_accel_availability(track: pd.DataFrame,
                               relaunch_distance_m: float = config.DP_RELAUNCH_DISTANCE_M) -> np.ndarray:
    """Two-motor 'rule' mode's accel-motor availability, precomputed per position: True
    within relaunch_distance_m of the most recent stop (a DISTANCE-based approximation
    of MOTOR_ACCEL_WINDOW_S's TIME-based window -- see config.DP_RELAUNCH_DISTANCE_M for
    why) OR while climbing (grade_pct > INCLINE_GRADE_THRESHOLD_PCT). A pure function of
    position, which is what lets two-motor mode slot into DP's (distance, speed) grid
    without adding a state dimension."""
    s_m = track["s_m"].to_numpy()
    grade = track["grade_pct"].to_numpy()
    stop = track["stop_event"].to_numpy()
    stop_s = s_m[stop]
    if len(stop_s) == 0:
        dist_since_stop = np.full(len(s_m), np.inf)
    else:
        ins = np.searchsorted(stop_s, s_m, side="right")
        idx = np.clip(ins - 1, 0, len(stop_s) - 1)
        dist_since_stop = s_m - stop_s[idx]
        dist_since_stop[ins == 0] = np.inf   # before the very first stop (shouldn't occur -- s_m[0] is one)
    return (dist_since_stop <= relaunch_distance_m) | (grade > config.INCLINE_GRADE_THRESHOLD_PCT)


def solve_dp(track: pd.DataFrame, scenario: weather_mod.WeatherScenario,
             motor: powertrain.MotorModel, fc: powertrain.FuelCellModel,
             lam_per_s: float, return_policy: bool = False,
             accel_motor: powertrain.MotorModel = None,
             cruise_motor: powertrain.MotorModel = None,
             accel_active: np.ndarray = None,
             cruise_converter: powertrain.ConverterModel = None):
    """One backward-induction pass at a fixed time-price lambda (m^3 H2 per second).
    Returns (h2_m3, time_s, v_trace_ms) of the optimal trajectory from a standing
    start. If return_policy=True, also returns (choice, v_grid, s_m) -- the FULL
    backward-induction result (optimal next-velocity-bin-index for every (distance
    bin, velocity bin), not just the one path from standstill) -- see
    dp_policy.py, which uses this as a precomputed answer table so a live query
    from any actual (position, speed) is an O(1) lookup, not a re-solve.

    Two-motor mode (accel_motor + cruise_motor both given, motor ignored): at each
    distance bin i, uses whichever motor's power ceiling/H2-flow table
    accel_active[i] (see compute_accel_availability()) says is engaged there --
    precomputed once from position alone, so the backward induction structure itself
    is unchanged, just which lookup table it reads from at each step."""
    n = len(track)
    s_m = track["s_m"].to_numpy()
    grade = track["grade_pct"].to_numpy()
    heading = track["heading_deg"].to_numpy()
    r_min_m = track["r_min_m"].to_numpy()
    v_safe_ms = np.minimum(track["v_safe_kmh"].to_numpy() / 3.6, V_MAX_MS)
    stop = track["stop_event"].to_numpy()

    v_grid = np.linspace(0.0, V_MAX_MS, N_V_BINS)
    two_motor = accel_motor is not None and cruise_motor is not None
    if two_motor:
        pwg_a, hfg_a, pwm_a = build_h2_flow_lookup(accel_motor, fc)
        pwg_c, hfg_c, pwm_c = build_h2_flow_lookup(cruise_motor, fc, converter=cruise_converter,
                                                   through_buffer=False)
        if accel_active is None:
            accel_active = np.ones(n, dtype=bool)
    else:
        p_wheel_grid, h2_flow_grid, p_wheel_max = build_h2_flow_lookup(motor, fc)

    # v_pair means/dt for every (v, v') transition -- shared across steps
    v_from = v_grid[:, None]
    v_to = v_grid[None, :]
    v_avg = 0.5 * (v_from + v_to)

    J = np.zeros(N_V_BINS)                      # terminal cost-to-go
    choice = np.zeros((n - 1, N_V_BINS), dtype=np.int16)

    for i in range(n - 2, -1, -1):
        if two_motor:
            p_wheel_grid, h2_flow_grid, p_wheel_max = (pwg_a, hfg_a, pwm_a) if accel_active[i] else (pwg_c, hfg_c, pwm_c)

        ds = s_m[i + 1] - s_m[i]
        dt = np.where(v_avg > 0.05, ds / np.maximum(v_avg, 0.05), np.inf)

        a = (v_to ** 2 - v_from ** 2) / (2 * ds)
        # resistance at the segment (evaluated at v_from, consistent with simulate.py --
        # including cornering scrub drag, using the cell's tightest radius)
        f_res = np.array([vehicle.resistance_force_n(v * 3.6, grade[i], scenario, heading[i], r_min_m=r_min_m[i])
                          for v in v_grid])[:, None]
        f_trac = config.MASS_TOTAL_KG * a + f_res
        p_wheel = np.maximum(0.0, f_trac) * v_from

        feasible = (a <= config.ACCEL_MAX_MS2 + 1e-9) & (a >= -config.BRAKE_MAX_MS2 - 1e-9)
        feasible &= p_wheel <= p_wheel_max + 1e-9
        feasible &= np.isfinite(dt)

        # node constraints on the DESTINATION velocity
        v_cap_next = 0.0 if stop[i + 1] else v_safe_ms[i + 1]
        feasible &= v_to <= v_cap_next + 1e-9

        # Landing on EXACTLY 0 is only legitimate at a real mandatory stop. Without
        # this, v_to=0 stays technically feasible everywhere (0 <= any v_cap_next),
        # and the h2 cost model doesn't meaningfully distinguish it from a gentle
        # partial glide: p_wheel is evaluated at v_from (not v_to), so h2_rate is
        # driven by how hard you're decelerating FROM, barely by how far TO -- the
        # interpolated h2_rate for landing anywhere from 0 up to ~13-14 km/h off a
        # 14.4 km/h state comes out nearly flat (confirmed empirically: identical to
        # 5+ significant figures across that whole range, before the motor-efficiency
        # fix in powertrain.py; even after that fix a milder version persists). That
        # flatness means DP's choice of exactly 0 among those near-equal-cost options
        # is decided by noise in the downstream cost-to-go, not real physics -- and it
        # shows: the unconstrained solve produces ~22 points across a lap of slamming
        # to a full stop mid-straight (no corner, no mandatory stop) then immediately
        # re-accelerating, which is neither physical nor something a driver should be
        # told to do. Confirmed present in the promoted canonical DP telemetry, not an
        # artifact of any downstream consumer.
        if not stop[i + 1]:
            feasible[:, 0] = False

        h2_rate = np.interp(p_wheel, p_wheel_grid, h2_flow_grid)
        dt_safe = np.where(np.isfinite(dt), dt, 0.0)  # infeasible transitions are masked below anyway
        cost = np.where(feasible, (h2_rate + lam_per_s) * dt_safe + J[None, :], np.inf)

        choice[i] = np.argmin(cost, axis=1)
        J = np.min(cost, axis=1)

    # forward extraction from standing start (v index 0)
    v_idx = 0
    h2_total, t_total = 0.0, 0.0
    v_trace = np.empty(n)
    v_trace[0] = v_grid[0]
    for i in range(n - 1):
        if two_motor:
            p_wheel_grid, h2_flow_grid = (pwg_a, hfg_a) if accel_active[i] else (pwg_c, hfg_c)
        nxt = int(choice[i, v_idx])
        v0, v1 = v_grid[v_idx], v_grid[nxt]
        ds = s_m[i + 1] - s_m[i]
        v_avg_i = max(0.5 * (v0 + v1), 0.05)
        dt = ds / v_avg_i
        a = (v1 ** 2 - v0 ** 2) / (2 * ds)
        f_res = vehicle.resistance_force_n(v0 * 3.6, grade[i], scenario, heading[i], r_min_m=r_min_m[i])
        p_wheel = max(0.0, config.MASS_TOTAL_KG * a + f_res) * v0
        h2_total += np.interp(p_wheel, p_wheel_grid, h2_flow_grid) * dt
        t_total += dt
        v_idx = nxt
        v_trace[i + 1] = v1
    if return_policy:
        return h2_total, t_total, v_trace, choice, v_grid, s_m
    return h2_total, t_total, v_trace


def find_lambda(track, scenario, motor, fc, time_budget_s: float,
                iters: int = 12, accel_motor=None, cruise_motor=None,
                accel_active: np.ndarray = None,
                cruise_converter: powertrain.ConverterModel = None) -> tuple[float, float, float, np.ndarray]:
    """Bisection on the time-price: higher lambda -> faster trajectory. Returns the
    tightest solution whose time fits the budget. accel_motor/cruise_motor/accel_active/
    cruise_converter (see solve_dp()) pass straight through -- when both motors are
    given, motor is ignored."""
    lo, hi = 0.0, 1e-4  # m^3 H2 per second -- hi chosen well above any plausible price
    best = None
    for _ in range(iters):
        lam = 0.5 * (lo + hi)
        h2, t, v = solve_dp(track, scenario, motor, fc, lam,
                            accel_motor=accel_motor, cruise_motor=cruise_motor, accel_active=accel_active,
                            cruise_converter=cruise_converter)
        if t > time_budget_s:
            lo = lam       # too slow -> raise the price of time
        else:
            best = (lam, h2, t, v)
            hi = lam       # fits -> try cheaper time (slower, less H2)
    if best is None:
        lam = hi
        h2, t, v = solve_dp(track, scenario, motor, fc, lam,
                            accel_motor=accel_motor, cruise_motor=cruise_motor, accel_active=accel_active,
                            cruise_converter=cruise_converter)
        best = (lam, h2, t, v)
    return best


def run_dp_benchmark(scenario_name: str = "typical_january",
                     motor_name: str = config.DEFAULT_MOTOR_NAME,
                     fc_name: str = config.DEFAULT_FC_NAME,
                     save: bool = True, full_track: pd.DataFrame = None,
                     telemetry_out_path: str = None,
                     use_two_motor: bool = True):
    """use_two_motor=True (new default, matching GA/PSO/CMA-ES's convention) runs DP on
    the real two-motor hardware (config.ACCEL_MOTOR_NAME + config.CRUISE_MOTOR_NAME,
    "rule"-mode availability approximated by compute_accel_availability() -- see
    config.DP_RELAUNCH_DISTANCE_M) instead of the single reference motor_name."""
    if full_track is None:
        profile_1lap = track_mod.build_racing_line_profile(save=False)
        full_track = sim_mod.build_full_attempt_track(profile_1lap)
    track = resample_track(full_track)
    scenario = weather_mod.SCENARIOS[scenario_name]
    fc = powertrain.load_fuel_cells()[fc_name]

    accel_motor = cruise_motor = motor = cruise_converter = None
    accel_active = None
    if use_two_motor:
        motors = powertrain.load_motors()
        accel_motor = motors[config.ACCEL_MOTOR_NAME]
        cruise_motor = motors[config.CRUISE_MOTOR_NAME]
        cruise_converter = powertrain.load_converters()[config.CRUISE_CONVERTER_NAME]
        accel_active = compute_accel_availability(track)
        active_motor_name = f"{config.ACCEL_MOTOR_NAME} + {config.CRUISE_MOTOR_NAME} (two-motor, rule mode)"
    else:
        motor = powertrain.load_motors()[motor_name]
        active_motor_name = motor.name

    n_stops = int(track["stop_event"].sum())
    time_budget_s = config.MAX_ATTEMPT_TIME_MIN * 60.0 - n_stops * config.STOP_DWELL_TIME_S

    lam, h2_m3, t_moving_s, v_trace = find_lambda(track, scenario, motor, fc, time_budget_s,
                                                   accel_motor=accel_motor, cruise_motor=cruise_motor,
                                                   accel_active=accel_active, cruise_converter=cruise_converter)
    t_total_s = t_moving_s + n_stops * config.STOP_DWELL_TIME_S
    dist_km = track["s_m"].iloc[-1] / 1000.0
    # accessory battery (Instrumentasi/Lighting/Wiper, horn excluded) runs continuously
    # for the whole attempt, independent of the propulsion strategy -- see telemetry.py
    accessory_energy_j = config.ACCESSORY_LOAD_W_CONTINUOUS * t_total_s

    out = track.copy()
    out["v_kmh"] = v_trace * 3.6
    out["weather_scenario"] = scenario.name
    out["motor_name"] = active_motor_name
    out["fc_name"] = fc.name
    if use_two_motor:
        out["active_motor"] = np.where(accel_active, config.ACCEL_MOTOR_NAME, config.CRUISE_MOTOR_NAME)
    if save:
        out.to_csv(telemetry_out_path or DP_TELEMETRY_CSV, index=False)

    return {
        "lambda_m3_per_s": lam,
        "h2_m3": h2_m3,
        "accessory_energy_j": accessory_energy_j,
        "time_total_min": t_total_s / 60.0,
        "distance_km": dist_km,
        "score_km_per_m3": telemetry_mod.h2_score_km_per_m3(dist_km, h2_m3, accessory_energy_j=accessory_energy_j),
        "telemetry": out,
        "motor_name": active_motor_name,
    }


if __name__ == "__main__":
    result = run_dp_benchmark()
    tel = result["telemetry"]
    accessory_h2_equiv_l = telemetry_mod.accessory_h2_equivalent_m3(result["accessory_energy_j"]) * 1000
    print(f"DP benchmark ({result['motor_name']} + {config.DEFAULT_FC_NAME}, typical_january):")
    print(f"  Total H2 (flow meter, incl. FC parasitic load): {result['h2_m3']*1000:.2f} L")
    print(f"  Accessory battery: {result['accessory_energy_j']/1000:.1f} kJ -> {accessory_h2_equiv_l:.2f} L H2-equivalent")
    print(f"  Total time: {result['time_total_min']:.2f} min (limit {config.MAX_ATTEMPT_TIME_MIN})")
    print(f"  Avg speed:  {result['distance_km']/(result['time_total_min']/60):.2f} km/h")
    print(f"  Art. 54e net score: {result['score_km_per_m3']:.1f} km/m^3 H2")
    print(f"  time-price lambda: {result['lambda_m3_per_s']:.3e} m^3/s")

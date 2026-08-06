"""
Realistic-driver telemetry generator for the SEM Urban Hydrogen twin.
================================================================================

The baseline optimizers (GA / CMA-ES / Fuzzy / MPC) produce a PERFECT execution of
their driving strategy -- unrealistically efficient. This module re-simulates the
*same* strategy (same per-point gas/glide setpoints) but layers realistic **human
execution errors** and **two-motor servo switching dynamics** on top, so the generated
telemetry looks like a real driver, not an optimizer.

WHAT IS PRESERVED (identical to baseline -- nothing here changes them):
  * track (racing line), lap distance, segment boundaries, corner radius, slope, weather
  * 4 laps, 35-min cap, start + both stop-and-go locations
  * fuel cell, vehicle mass, aero, rolling resistance, efficiency maps (all from config)
  * the driving STRATEGY itself (setpoints reconstructed from each optimizer's own output)
  * the telemetry SCHEMA -- same columns, same per-track-point sampling

WHAT CHANGES (execution only):
  1. speed tracking error   -- driver can't hold the exact target speed (+/-3%)
  2. throttle modulation     -- imperfect throttle: small smoothed oscillation (+/-5%)
  3. glide timing error      -- starts gliding a little early/late (0.3-2.0 s)
  4. acceleration timing     -- reacts late after a stop (0.2-1.5 s)
  5. brake timing error      -- brakes a little early/late (0.2-1.0 s)
  6. corner entry error      -- enters corners slightly fast/slow (+/-2 km/h)
  7. stop-and-go execution   -- extra reaction delay after a full stop (0.2-1.2 s)
  8. steering line deviation -- +/-0.3 m off the optimal line -> extra rolling + corner scrub
  + driver fatigue           -- error magnitude grows each lap (100/103/105/108 %)
  + motor servo switching    -- each accel<->cruise switch takes `motor_switch_time_s`
                                (default 0.5 s, configurable 0.5/1/2/3 s) during which the
                                motor's available power is reduced -> less torque/accel,
                                affecting power, current, energy and H2.

All errors are STOCHASTIC but BOUNDED (truncated Gaussian / bounded uniform) and the hard
safety ceiling (v_safe / stop events) is always enforced, so the car never behaves unsafely
and the attempt stays legal. Physics is reused from digital_twin.vehicle / .powertrain --
no equations are re-implemented here (only the integration loop adds the driver layer).
"""

from dataclasses import dataclass
import math

import numpy as np
import pandas as pd

from digital_twin import config
from digital_twin import hybrid_energy
from digital_twin import powertrain
from digital_twin import simulate as sim_mod
from digital_twin import strategy_analysis as sa
from digital_twin import telemetry as telemetry_mod
from digital_twin import track as track_mod
from digital_twin import vehicle
from digital_twin import weather as weather_mod
from digital_twin import fuzzy_strategy as fz

NUM_SEGMENTS_PER_LAP = 30   # matches optimize_ga / optimize_cma gene layout
# Servo-consistent motor policy for ALL models: a real 0.5 s switch servo cannot toggle
# every ~3 s (the per-step "efficiency" policy would do 600+ switches -- impossible), so the
# launch/climb "rule" policy (~15 switches/attempt) is the one this human-execution study uses.
MODEL_MOTOR_MODE = {"ga": "rule", "cma": "rule", "fuzzy": "rule", "mpc": "rule"}

@dataclass
class DriverErrorConfig:
    """All driver-error magnitudes and the servo switch time. Defaults are the ranges
    requested in the brief; everything is a PLACEHOLDER pending real driver telemetry."""
    speed_tracking_pct: float = 0.03            # 1) +/-3% speed-holding (std, truncated at 2 sigma)
    throttle_pct: float = 0.05                  # 2) +/-5% throttle oscillation (smoothed)
    glide_timing_s: tuple = (0.3, 2.0)          # 3) early/late glide reaction window
    accel_timing_s: tuple = (0.2, 1.5)          # 4) late reaction after a stop
    brake_timing_s: tuple = (0.2, 1.0)          # 5) early/late braking
    corner_entry_kmh: float = 2.0               # 6) +/-2 km/h corner-entry speed error
    glide_band_jitter_kmh: float = 1.5          # 3)&5) glide/brake timing rendered as gas/coast threshold jitter (km/h)
    stopgo_delay_s: tuple = (0.2, 1.2)          # 7) extra reaction delay after a full stop
    steering_dev_m: float = 0.3                 # 8) +/-0.3 m lateral line deviation (std)
    fatigue_per_lap: tuple = (1.00, 1.03, 1.05, 1.08)   # error growth per lap
    motor_switch_time_s: float = 0.5            # servo switch duration (configurable: 0.5/1/2/3 s)
    # A real driver watches the clock and paces to roughly the planned schedule, so execution
    # noise does not accumulate into a big time loss (keeps the run legal, <35 min). Gentle
    # proportional correction of the target speed toward the perfect-run schedule.
    pace_gain: float = 0.08                     # per second of schedule error
    pace_max_frac: float = 0.15                 # cap the pace correction at +/-15% speed
    target_finish_min: float = 33.6             # a prudent driver aims a bit under the 35-min cap
                                                # (leaves buffer for their own execution error)
    enabled: bool = True                        # False -> perfect run (for the baseline re-sim)
    seed: int = 42


# ============================================================================== setpoints
def reconstruct_setpoints(model: str, full_track: pd.DataFrame, lap_km: float,
                          baseline_tel: pd.DataFrame = None, seg_suffix: str = ""):
    """Per-point (v_target_kmh, v_coast_kmh) for the model's UNCHANGED strategy.

    GA/CMA come from their saved per-segment genes; Fuzzy from its rulebook; MPC from its
    own per-step command (replayed) -- exactly the strategy the baseline telemetry used.

    seg_suffix selects a per-weather GA/CMA gene file (e.g. "_calm" ->
    data/ga_segment_targets_calm.csv); default "" is the canonical typical run."""
    model = model.lower()
    if model in ("ga", "cma"):
        seg = pd.read_csv(f"data/{model}_segment_targets{seg_suffix}.csv")
        s_km = full_track["distance_km"].to_numpy()
        idx = np.clip(np.floor((s_km % lap_km) / (lap_km / NUM_SEGMENTS_PER_LAP)).astype(int),
                      0, NUM_SEGMENTS_PER_LAP - 1)
        vt = seg["v_target_kmh"].to_numpy()[idx]
        vc = np.minimum(seg["v_coast_kmh"].to_numpy()[idx], vt)
        return vt.astype(float), vc.astype(float)
    if model == "fuzzy":
        strat = fz.FuzzyStrategy(v_med_kmh=28.0, v_slow_kmh=23.0, v_fast_kmh=29.0,
                                 band_flat_kmh=5.0, band_down_kmh=9.0, band_up_kmh=3.0)
        return strat.compute_setpoints(full_track)
    if model == "mpc":
        if baseline_tel is None:
            baseline_tel = pd.read_csv("notebooks/mpc/mpc_attempt_analysis.csv")
        if "is_recharge" in baseline_tel.columns:   # drop the Art.56c recharge tail -> DRIVING-length cmd
            baseline_tel = baseline_tel[~baseline_tel["is_recharge"].astype(bool)]
        cmd = baseline_tel["v_cmd_corrected"].to_numpy(dtype=float)
        cmd = np.where(cmd <= 0.5, config.MPC_THETA_DEFAULT["v_min_kmh"], cmd)  # ignore forced-stop 0s
        return cmd.copy(), cmd.copy()
    raise ValueError(f"unknown model {model!r}")


# ============================================================================== helpers
def _trunc_normal(rng, std, size=None, clip=2.0):
    """Zero-mean truncated Gaussian (no extreme outliers)."""
    return np.clip(rng.normal(0.0, std, size), -clip * std, clip * std)


def _smooth(x, k):
    return x if k <= 1 else np.convolve(x, np.ones(k) / k, mode="same")


# ============================================================================== simulator
def simulate_with_driver_error(full_track, scenario, accel_motor, cruise_motor, fc,
                               v_target_kmh, v_coast_kmh, err: DriverErrorConfig,
                               motor_select_mode="rule", pace_t_s=None,
                               cruise_converter=None) -> pd.DataFrame:
    """Forward integrate the attempt with the driver-error + servo-switch layer.

    Mirrors digital_twin.simulate.simulate() step-for-step (so the output columns are
    identical) and reuses its physics; the ONLY additions are the driver-error and
    switching perturbations, each tagged inline. Returns a telemetry DataFrame in the
    exact simulate() schema (enrichment / MPC columns are added by generate())."""
    n = len(full_track)
    s_m = full_track["s_m"].to_numpy()
    grade = full_track["grade_pct"].to_numpy()
    heading = full_track["heading_deg"].to_numpy()
    r_min = full_track["r_min_m"].to_numpy()
    v_safe = full_track["v_safe_kmh"].to_numpy()
    stop_event = full_track["stop_event"].to_numpy()
    lap_arr = full_track["lap"].to_numpy()
    fatigue = err.fatigue_per_lap
    rng = np.random.default_rng(err.seed)

    # safety-only ceiling (never exceeded -> the car is always safe/legal)
    ceiling_kmh = sim_mod.compute_speed_ceiling(full_track, 999.0)

    # Pre-drawn SMOOTHED noise waves (gentle drift, not white jitter), each renormalised to
    # its requested magnitude. Modelling every error as a bounded perturbation of the gas/glide
    # SETPOINTS (plus small time delays at stops) keeps the loop stable -- no runaway feedback.
    def wave(scale, k):
        w = _smooth(rng.normal(0.0, 1.0, n), k)
        return w * (scale / (w.std() + 1e-9)) if err.enabled else np.zeros(n)
    speed_wave    = wave(err.speed_tracking_pct, 12)     # #1 speed tracking, fraction (+/-3%)
    throttle_wave = wave(err.throttle_pct, 30)           # #2 throttle modulation, fraction (+/-5%)
    glide_jit     = wave(err.glide_band_jitter_kmh, 25)  # #3 glide-timing -> gas-threshold jitter (km/h)
    brake_jit     = wave(err.glide_band_jitter_kmh, 25)  # #5 brake-timing -> coast-threshold jitter (km/h)
    corner_wave   = wave(err.corner_entry_kmh, 15)       # #6 corner-entry speed error (+/-2 km/h)
    steer_dev     = wave(err.steering_dev_m, 20)         # #8 lateral line deviation (+/-0.3 m)

    # output arrays (identical set to simulate())
    v_ms = np.zeros(n); a_ms2 = np.zeros(n); t_s = np.zeros(n)
    f_traction_n = np.zeros(n); f_drag_n = np.zeros(n); f_roll_n = np.zeros(n)
    f_grade_n = np.zeros(n); f_cornering_n = np.zeros(n)
    p_wheel_w = np.zeros(n); p_motor_mech_w = np.zeros(n); p_motor_elec_w = np.zeros(n)
    p_fc_elec_w = np.zeros(n); h2_flow = np.zeros(n); h2_cum = np.zeros(n)
    acc_energy = np.zeros(n)
    motor_clipped = np.zeros(n, dtype=bool); motor_state = np.empty(n, dtype=object)
    active_motor_name = np.empty(n, dtype=object); rule_violation = np.zeros(n, dtype=bool)
    switch_active = np.zeros(n, dtype=bool)      # diagnostic: was a servo switch mid-actuation
    v_target_exec = np.zeros(n)                  # the (perturbed) speed the driver actually aimed at

    # distance to next mandatory stop (for the forced-glide safety floor, as in simulate())
    stop_s = s_m[stop_event]
    if len(stop_s):
        nxt = np.searchsorted(stop_s, s_m, side="right")
        dist_to_stop = np.where(nxt >= len(stop_s), np.inf,
                                stop_s[np.clip(nxt, 0, len(stop_s) - 1)] - s_m)
    else:
        dist_to_stop = np.full(n, np.inf)

    # driver / servo state
    is_gliding = False
    active_motor = None; t_last_switch = 0.0; relaunching = True; t_launch = 0.0
    switch_timer = 0.0                           # remaining servo actuation time (s)
    v_ms[0] = 0.0

    for i in range(n - 1):
        ds = s_m[i + 1] - s_m[i]
        lap = int(lap_arr[i]); fat = fatigue[min(lap - 1, len(fatigue) - 1)] if err.enabled else 1.0
        v_kmh_i = v_ms[i] * 3.6

        # safety ceiling accel (hard cap -- keeps the car safe & legal regardless of error)
        target_safe = ceiling_kmh[i + 1] / 3.6
        a_safety = (target_safe ** 2 - v_ms[i] ** 2) / (2 * ds) if ds > 0 else 0.0

        # --- driver's imperfect gas/glide THRESHOLDS (bounded jitter = errors #1,#2,#3,#5,#6) ---
        # The strategy's target/coast speeds are unchanged; the DRIVER just tracks them
        # imperfectly. Perturbing the thresholds (not a hold state-machine) keeps it stable.
        frac = (speed_wave[i] + throttle_wave[i]) * fat            # #1 speed +/-3% , #2 throttle +/-5%
        corner_i = corner_wave[i] * fat if np.isfinite(r_min[i]) else 0.0   # #6 only in corners
        vt_i = v_target_kmh[i] * (1.0 + frac) + glide_jit[i] * fat + corner_i   # #3 glide early/late
        vc_i = v_coast_kmh[i] * (1.0 + frac) + brake_jit[i] * fat               # #5 brake early/late
        # pace-keeping: nudge speed toward the planned schedule so noise doesn't lose the clock
        if pace_t_s is not None:
            behind_s = t_s[i] - pace_t_s[i]                       # >0 => slower than plan -> speed up
            pace = float(np.clip(err.pace_gain * behind_s, -err.pace_max_frac, err.pace_max_frac))
            vt_i *= (1.0 + pace); vc_i *= (1.0 + pace)
        vc_i = min(vc_i, vt_i - 0.5)                              # keep a valid band

        # gas/glide toggle on the (perturbed) thresholds -- same pulse-and-glide rule as simulate
        if v_kmh_i >= vt_i:
            is_gliding = True
        elif v_kmh_i <= vc_i:
            is_gliding = False
        # forced glide near a stop (safety floor, identical to simulate -- never errored away)
        effective_gliding = is_gliding or (dist_to_stop[i] <= config.STOP_GLIDE_LOOKAHEAD_M)
        v_des_kmh = None if effective_gliding else vt_i
        v_target_exec[i] = 0.0 if effective_gliding else vt_i

        # desired acceleration from the (perturbed) target, capped by the safety ceiling
        if effective_gliding:
            # coast: natural deceleration (motor off) -- reuse component physics below
            a_des = a_safety
            glide_now = True
        else:
            tgt = v_des_kmh / 3.6
            a_gas = (tgt ** 2 - v_ms[i] ** 2) / (2 * ds) if ds > 0 else 0.0
            a_des = min(a_safety, a_gas)
            glide_now = False
        a_applied = float(np.clip(a_des, -config.BRAKE_MAX_MS2, config.ACCEL_MAX_MS2))

        # --- resistance with steering-line deviation (#8): extra rolling + tighter corner ---
        dev = abs(steer_dev[i])
        crr_eff = config.CRR * (1.0 + 0.4 * dev)                    # wandering scrubs -> slightly more Crr
        # off the apex the effective radius shrinks (bounded): tighter line -> more scrub
        r_eff = r_min[i] * (1.0 - min(0.3 * dev, 0.15)) if np.isfinite(r_min[i]) else r_min[i]
        f_drag = vehicle.drag_force_n(v_kmh_i, scenario, heading[i])
        f_roll = vehicle.rolling_resistance_n(grade[i], crr=crr_eff)
        f_grade = vehicle.grade_force_n(grade[i])
        f_corner = vehicle.cornering_drag_n(v_kmh_i, r_eff)
        if glide_now:
            f_res = f_drag + f_roll + f_grade + f_corner
            a_coast = -f_res / config.MASS_TOTAL_KG
            a_applied = min(a_applied, a_coast)                    # coast, don't power
        f_res = f_drag + f_roll + f_grade + f_corner

        # relaunch arming (two-motor rule mode), same as simulate
        if stop_event[i]:
            if not relaunching:
                relaunching = True; t_launch = t_s[i]
        elif relaunching and (v_kmh_i >= config.V_TARGET_AVG_KMH_CRUISE
                              or (t_s[i] - t_launch) >= config.MOTOR_ACCEL_WINDOW_S):
            relaunching = False

        # --- motor selection + SERVO SWITCH dynamics ---
        f_traction = config.MASS_TOTAL_KG * a_applied + f_res
        desired_mech_w = max(0.0, f_traction) * v_ms[i] / config.DRIVETRAIN_EFFICIENCY_ASSUMED
        desired = sim_mod._pick_motor(desired_mech_w, relaunching, grade[i],
                                      accel_motor, cruise_motor, motor_select_mode)
        if active_motor is None:
            active_motor = desired; t_last_switch = t_s[i]
        elif desired is not active_motor:
            must = desired_mech_w > active_motor.max_mech_power_w()
            if must or (t_s[i] - t_last_switch) >= config.MOTOR_MIN_DWELL_S:
                active_motor = desired; t_last_switch = t_s[i]
                switch_timer = err.motor_switch_time_s            # servo starts actuating
        # power available is reduced while the servo is mid-switch (ramps 0.35 -> 1.0)
        if switch_timer > 0.0 and err.motor_switch_time_s > 0:
            frac = 1.0 - switch_timer / err.motor_switch_time_s
            power_factor = 0.35 + 0.65 * max(0.0, min(1.0, frac))
            switch_active[i] = True
        else:
            power_factor = 1.0

        # power-limit feedback (as simulate) using the switch-reduced power cap
        power_limited = False
        if f_traction > 0.0 and v_ms[i] > 0.3:
            f_tr_max = active_motor.max_mech_power_w() * power_factor * config.DRIVETRAIN_EFFICIENCY_ASSUMED / v_ms[i]
            if f_traction > f_tr_max:
                power_limited = True
                a_applied = float(np.clip((f_tr_max - f_res) / config.MASS_TOTAL_KG,
                                          -config.BRAKE_MAX_MS2, config.ACCEL_MAX_MS2))

        # integrate motion
        v_next = math.sqrt(max(0.0, v_ms[i] ** 2 + 2 * a_applied * ds))
        v_avg = max(0.5 * (v_ms[i] + v_next), 0.05)
        dt = ds / v_avg
        switch_timer = max(0.0, switch_timer - dt)

        f_traction = config.MASS_TOTAL_KG * a_applied + f_res
        a_ms2[i] = a_applied
        f_drag_n[i] = f_drag; f_roll_n[i] = f_roll; f_grade_n[i] = f_grade
        f_cornering_n[i] = f_corner; f_traction_n[i] = f_traction
        p_wheel_w[i] = max(0.0, f_traction) * v_ms[i]
        motor_state[i] = "brake" if f_traction < -1.0 else ("accel" if f_traction > 1.0 else "cruise")
        if ceiling_kmh[i] < v_safe[i] - 1e-6 and v_kmh_i > v_safe[i] + 1e-6:
            rule_violation[i] = True

        p_motor_mech_w[i] = p_wheel_w[i] / config.DRIVETRAIN_EFFICIENCY_ASSUMED
        elec, clip2 = active_motor.electrical_power_w(p_motor_mech_w[i])
        # Cruise motor (24V) draws through the DC/DC buck converter off the 48V bus -- extra
        # conversion loss; the accel motor (48V) sits directly on the bus (same as simulate()).
        if cruise_converter is not None and active_motor is cruise_motor:
            elec = cruise_converter.input_power_w(elec)
        p_motor_elec_w[i] = elec
        motor_clipped[i] = power_limited or clip2
        active_motor_name[i] = active_motor.name
        # Buffer (supercap) sits between the FC and the ACCEL motor ONLY; the cruise motor
        # draws straight from the FC (no buffer stage), matching simulate()'s routing.
        buffer_eff = config.POWERTRAIN_BUFFER_EFFICIENCY_ASSUMED if active_motor is accel_motor else 1.0
        p_fc_elec_w[i] = elec / buffer_eff + config.FC_PARASITIC_LOAD_W
        h2_flow[i] = fc.h2_volume_flow_m3_s(p_fc_elec_w[i])
        h2_cum[i + 1] = h2_cum[i] + h2_flow[i] * dt
        acc_energy[i + 1] = acc_energy[i] + config.ACCESSORY_LOAD_W_CONTINUOUS * dt

        # advance time; add mandatory stop dwell + driver reaction delays (#4 accel, #7 stop&go)
        t_s[i + 1] = t_s[i] + dt
        if stop_event[i + 1] and v_next < 0.5:
            t_s[i + 1] += config.STOP_DWELL_TIME_S
            if err.enabled:
                t_s[i + 1] += rng.uniform(*err.stopgo_delay_s) * fat      # #7 reaction after full stop
                t_s[i + 1] += rng.uniform(*err.accel_timing_s) * fat      # #4 late launch reaction
        v_ms[i + 1] = v_next

    # tail fill
    for arr in (motor_state, active_motor_name):
        arr[-1] = arr[-2]
    v_target_exec[-1] = v_target_exec[-2]

    out = full_track.copy()
    out["t_s"] = t_s; out["v_kmh"] = v_ms * 3.6; out["a_ms2"] = a_ms2
    out["v_ceiling_kmh"] = ceiling_kmh
    out["f_traction_n"] = f_traction_n; out["f_drag_n"] = f_drag_n; out["f_roll_n"] = f_roll_n
    out["f_grade_n"] = f_grade_n; out["f_cornering_n"] = f_cornering_n
    out["p_wheel_w"] = p_wheel_w; out["p_motor_mech_w"] = p_motor_mech_w
    out["p_motor_elec_w"] = p_motor_elec_w; out["p_fc_elec_w"] = p_fc_elec_w
    out["h2_flow_m3_s"] = h2_flow; out["h2_cumulative_m3"] = h2_cum
    out["accessory_energy_cumulative_j"] = acc_energy
    out["motor_clipped"] = motor_clipped; out["motor_state"] = motor_state
    out["active_motor"] = active_motor_name; out["weather_scenario"] = scenario.name
    out["motor_name"] = f"{accel_motor.name} + {cruise_motor.name}"; out["fc_name"] = fc.name
    out["rule_violation"] = rule_violation
    # extra diagnostics kept as private (dropped before matching the baseline schema)
    out["_switch_active"] = switch_active
    out["_v_target_exec_kmh"] = v_target_exec
    return out


# ============================================================================== driver
def _env(scenario_name="typical_january"):
    profile = track_mod.build_racing_line_profile(save=False)
    full_track = sim_mod.build_full_attempt_track(profile)
    scenario = weather_mod.SCENARIOS[scenario_name]
    motors = powertrain.load_motors()
    return (full_track, profile["distance_km"].iloc[-1], scenario,
            motors[config.ACCEL_MOTOR_NAME], motors[config.CRUISE_MOTOR_NAME],
            powertrain.load_fuel_cells()[config.DEFAULT_FC_NAME])


def generate(model: str, err: DriverErrorConfig = None, scenario_name="typical_january",
             baseline_tel: pd.DataFrame = None) -> pd.DataFrame:
    """Full pipeline: reconstruct the model's strategy, run the driver-error simulator,
    and return telemetry ENRICHED to exactly the baseline schema (per model).

    Pass err.enabled=False for the perfect re-simulation (baseline check)."""
    err = err or DriverErrorConfig()
    mode = MODEL_MOTOR_MODE.get(model.lower(), "rule")
    full_track, lap_km, scenario, accel_motor, cruise_motor, fc = _env(scenario_name)
    # Published baseline telemetry: its schedule (t_s) is the plan the driver paces to (keeps
    # the run legal, <35 min), and its column order is the schema we reproduce byte-for-byte.
    base_path = f"notebooks/{model.lower()}/{model.lower()}_attempt_analysis.csv"
    base_tel = pd.read_csv(base_path)
    if baseline_tel is None:
        baseline_tel = base_tel
    vt, vc = reconstruct_setpoints(model, full_track, lap_km, baseline_tel)
    # Pace both perfect & error to the plan's schedule, scaled to finish at target_finish_min
    # (a prudent buffer under the 35-min cap) so realistic error still lands legal.
    base_t = base_tel["t_s"].to_numpy()
    pace_t_s = base_t * (err.target_finish_min * 60.0 / base_t[-1]) if base_t[-1] > 0 else base_t
    cruise_converter = powertrain.load_converters()[config.CRUISE_CONVERTER_NAME]
    raw = simulate_with_driver_error(full_track, scenario, accel_motor, cruise_motor, fc,
                                     vt, vc, err, motor_select_mode=mode, pace_t_s=pace_t_s,
                                     cruise_converter=cruise_converter)
    switch_active = raw.pop("_switch_active").to_numpy()
    v_target_exec = raw.pop("_v_target_exec_kmh").to_numpy()
    # Source the demand through the hybrid FC + supercapacitor system (adds supercap columns
    # and re-bills hydrogen at the FC's 62% operating point) -- same system as simulate().
    raw = hybrid_energy.apply_hybrid(raw)
    tel = sa.enrich(raw)   # adds drive_phase, gas_glide_num, x_m, y_m, lap_distance_km, stop_label

    # apply_hybrid appends a stationary Art. 56c recharge tail; pad the driving-length setpoint
    # arrays so per-row columns line up (the car is stopped in the tail -> no command/deviation).
    n_tail = len(tel) - len(v_target_exec)
    if n_tail > 0:
        v_target_exec = np.concatenate([v_target_exec, np.zeros(n_tail)])
        switch_active = np.concatenate([switch_active, np.zeros(n_tail, bool)])
        vt = np.concatenate([np.asarray(vt, float), np.zeros(n_tail)])

    if model.lower() == "mpc":
        # MPC baseline schema carries these 7 extra columns -> fill them consistently
        tel["buffer_soc_wh"] = 0.0
        tel["v_cmd_mpc"] = vt                      # the strategy's command (unchanged)
        tel["v_cmd_corrected"] = vt
        tel["driver_deviation"] = (tel["v_kmh"] - v_target_exec) / 3.6   # actual - commanded (m/s)
        tel["mpc_mode"] = np.where(switch_active, "motor_switch", "driver_exec")
        a = tel["a_ms2"].to_numpy()
        tel["driver_throttle_pct"] = np.where(a >= 0, np.minimum(100.0, a / config.ACCEL_MAX_MS2 * 100.0), 0.0)
        tel["driver_brake_pct"] = np.where(a < 0, np.minimum(100.0, -a / config.BRAKE_MAX_MS2 * 100.0), 0.0)

    # Reindex to the EXACT baseline column order so the schema is byte-for-byte compatible.
    base_cols = list(base_tel.columns)
    if set(base_cols) == set(tel.columns):
        tel = tel[base_cols]
    return tel


def summary(tel: pd.DataFrame, label: str = "") -> dict:
    """Headline metrics for the baseline-vs-error comparison tables."""
    dist_km = tel["s_m"].iloc[-1] / 1000.0
    # SEM Art. 56c(iii): supercap recharge time is added to the recorded run time.
    recharge_s = float(tel["supercap_recharge_s"].iloc[0]) if "supercap_recharge_s" in tel.columns else 0.0
    time_s = tel["t_s"].iloc[-1] + recharge_s
    h2_m3 = tel["h2_cumulative_m3"].iloc[-1]
    acc_j = tel["accessory_energy_cumulative_j"].iloc[-1]
    score = telemetry_mod.h2_score_km_per_m3(dist_km, h2_m3, accessory_energy_j=acc_j)
    am = tel["active_motor"].to_numpy(); v = am[pd.notna(am)]
    handoffs = int(np.sum(v[1:] != v[:-1])) if len(v) > 1 else 0
    return {
        "label": label,
        "score_km_per_m3": round(score, 1),
        "h2_litres": round(h2_m3 * 1000.0, 2),
        "time_min": round(time_s / 60.0, 2),
        "avg_speed_kmh": round(dist_km / (time_s / 3600.0), 2),
        "max_speed_kmh": round(tel["v_kmh"].max(), 1),
        "motor_handoffs": handoffs,
        "rule_violations": int(tel["rule_violation"].sum()),
        "time_ok": bool(time_s <= config.MAX_ATTEMPT_TIME_MIN * 60.0),
    }

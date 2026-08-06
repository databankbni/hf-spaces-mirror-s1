"""
Predictive + Adaptive + Driver-Aware Model Predictive Control for the SEM hydrogen
strategy (blueprint: MPC_SPEC.md). This is the INNER-LOOP controller; the GA/PSO
OUTER loop (optimize_ga.optimize_mpc_hyperparams) tunes its hyperparameters `theta`.

At each track step the controller looks a receding horizon of N steps ahead, and via
grid enumeration over candidate target speeds picks the one whose N-step rollout has
the lowest cost (H2 + time + track-safety + smoothness + driver penalties). It then
applies that command for ONE step and slides the horizon forward.

Three things make it more than a fixed strategy:
  * Predictive  -- explicit N-step rollout using the exact simulate.step() physics.
  * Adaptive    -- every physics parameter (Crr, drivetrain eff, motor/FC curves,
                   weather) is injected, so an EP re-estimate changes behaviour with
                   no code edit (MPC_SPEC section 4).
  * Driver-Aware-- reads the driver's actual deviation from setpoint and, guided by a
                   deep-learning driver-intent predictor (dl_predictor.DLPredictor),
                   corrects the next command (MPC_SPEC section 6).

run_closed_loop() returns telemetry with the SAME columns as simulate() plus the MPC
diagnostic columns, so telemetry.py scoring and the notebooks work unchanged.
"""

import numpy as np
import pandas as pd

from . import config
from . import hybrid_energy
from . import powertrain
from . import simulate as sim_mod
from . import telemetry as telemetry_mod
from . import track as track_mod
from . import weather as weather_mod
from .dl_predictor import DLPredictor

SEGMENT_TARGETS_CSV = "data/mpc_segment_targets.csv"
TELEMETRY_CSV = "data/simulated_telemetry_mpc.csv"

# The validated, competition-legal hyperparameters (notebooks/mpc/mpc_analyze.ipynb's
# feasibility sweep) -- NOT config.MPC_THETA_DEFAULT. The raw defaults (w_time=1.0,
# horizon_n=25, alpha_drv=0.3, v_min_kmh=18.0) under-penalize time and finish in
# ~49 min, over the 35-min Art. 227 cap (time_ok=False) -- a real run, but not a legal
# one. This is the theta actually used for the rank-1 entry in result of analysis/
# strategy_comparison.csv (278.5 km/m^3, 34.58 min, time_ok=True): w_time raised to
# 2.0, horizon shortened to 20, alpha_drv=0 (pure optimal setpoints, driver-awareness
# demoed separately), and v_min_kmh swept over {24, 26, 28} km/h with 26.0 winning as
# the most efficient FEASIBLE floor. Anything that builds "the winning MPC strategy"
# offline (driver_advisory.build_advisory_table()'s default source) or live
# (driver_advisory_bridge.py's MPCController) should use this, not plain resolve_theta(None).
BEST_THETA = {
    "horizon_n": 20, "w_h2": 6000.0, "w_time": 2.0, "w_track": 60.0,
    "w_du": 2.0, "w_drv": 0.0, "alpha_drv": 0.0,
    "v_min_kmh": 26.0, "v_max_kmh": 33.0,
}
BEST_N_CANDIDATES = 9


def resolve_theta(theta: dict = None) -> dict:
    """Fill any missing keys from config.MPC_THETA_DEFAULT and coerce types."""
    t = dict(config.MPC_THETA_DEFAULT)
    if theta:
        t.update({k: theta[k] for k in theta if k in config.MPC_THETA_DEFAULT})
    t["horizon_n"] = int(round(t["horizon_n"]))
    return t


class MPCController:
    """
    Receding-horizon controller. Construct once per attempt with a resolved `theta`,
    then call solve_step() as the closed loop advances. All physics parameters are
    constructor arguments (adaptive re-parameterization, MPC_SPEC 4.1).
    """

    def __init__(self, full_track, scenario, motor, fc, theta=None,
                 crr=config.CRR, drivetrain_eff=config.DRIVETRAIN_EFFICIENCY_ASSUMED,
                 dl_predictor: DLPredictor = None, adaptive: bool = False,
                 n_candidates: int = config.MPC_N_CANDIDATES,
                 accel_motor: powertrain.MotorModel = None,
                 cruise_motor: powertrain.MotorModel = None,
                 motor_select_mode: str = config.MOTOR_SELECT_MODE_DEFAULT):
        self.scenario = scenario
        self.motor = motor
        self.fc = fc
        # Two-motor Urban-Concept split: when both are supplied the MPC also decides
        # WHICH motor drives each step (via simulate.step) and reports it -- the
        # "which motor where" strategy layer. Single `motor` path is unchanged.
        self.accel_motor = accel_motor
        self.cruise_motor = cruise_motor
        self.motor_select_mode = motor_select_mode
        self.two_motor = accel_motor is not None and cruise_motor is not None
        self.theta = resolve_theta(theta)
        self.crr = crr                      # injected EP estimate (see update_estimates)
        self.drivetrain_eff = drivetrain_eff
        self.dl = dl_predictor if dl_predictor is not None else DLPredictor()
        self.adaptive = adaptive
        self.n_candidates = n_candidates

        # Precompute track arrays (numpy) for fast horizon rollout.
        self.n = len(full_track)
        self.s_m = full_track["s_m"].to_numpy()
        self.ds = np.diff(self.s_m, append=self.s_m[-1])
        self.grade = full_track["grade_pct"].to_numpy()
        self.heading = full_track["heading_deg"].to_numpy()
        self.r_min = full_track["r_min_m"].to_numpy()
        self.stop_event = full_track["stop_event"].to_numpy()
        self.v_safe_kmh = full_track["v_safe_kmh"].to_numpy()
        # safety-only ceiling (unbounded cruise) -- MPC chooses the speed within it
        self.ceiling_ms = sim_mod.compute_speed_ceiling(full_track, 999.0) / 3.6
        # only needed by recommend() (live driver-advisory queries), not the closed loop
        self.latitude = full_track["latitude"].to_numpy() if "latitude" in full_track.columns else None
        self.longitude = full_track["longitude"].to_numpy() if "longitude" in full_track.columns else None

        self.v_min_ms = self.theta["v_min_kmh"] / 3.6
        self.v_max_ms = self.theta["v_max_kmh"] / 3.6

    # --- horizon rollout cost (MPC_SPEC 3.3) ------------------------------
    def _rollout_cost(self, i: int, v_cmd_ms: float, v0_ms: float) -> float:
        w_h2 = self.theta["w_h2"]
        w_time = self.theta["w_time"]
        w_track = self.theta["w_track"]
        end = min(i + self.theta["horizon_n"], self.n - 1)
        v = v0_ms
        J_h2 = J_time = J_track = 0.0
        use_surrogate = self.dl.h2_available
        for k in range(i, end):
            ds = self.ds[k]
            v_ceil = self.ceiling_ms[k + 1]
            a_safety = (v_ceil ** 2 - v ** 2) / (2 * ds) if ds > 0 else 0.0
            # gas toward the target while below it; glide (motor off) once at/above it --
            # the same pulse-and-glide the closed loop actuates (see run_closed_loop).
            if v_cmd_ms > v:
                v_gas = min(v_cmd_ms, v_ceil)
                a_des = (v_gas ** 2 - v ** 2) / (2 * ds) if ds > 0 else 0.0
                glide = False
            else:
                a_des, glide = a_safety, True
            res = sim_mod.step(v, ds, self.grade[k], self.heading[k], self.r_min[k],
                               a_des, self.scenario, self.motor, self.fc,
                               accel_motor=self.accel_motor, cruise_motor=self.cruise_motor,
                               motor_select_mode=self.motor_select_mode,
                               relaunching=bool(self.stop_event[k]), glide=glide)
            if use_surrogate:
                h2_gs = self.dl.predict_h2_flow_gs({
                    "speed_kmh": v * 3.6, "acceleration_ms2": res.a,
                    "motor_power_w": res.p_motor_elec,
                    "ambient_temp_c": self.scenario.temperature_c})
                dh2_g = (h2_gs or 0.0) * res.dt
            else:
                # m3/s -> g/s : *1000 L/m3 * density g/L
                dh2_g = res.h2_flow_m3_s * 1000.0 * config.H2_DENSITY_G_PER_L_STP * res.dt
            J_h2 += dh2_g
            J_time += res.dt
            over = max(0.0, res.v_next - v_ceil)
            J_track += over * over
            v = res.v_next
        return w_h2 * J_h2 + w_time * J_time + w_track * J_track

    # --- one control decision (MPC_SPEC 3.5 + 6.3) ------------------------
    def solve_step(self, i: int, v0_ms: float, driver_state: dict, last_cmd_ms: float):
        """Return (v_cmd_ms, v_cmd_corrected_ms, mpc_mode). v_cmd is the raw optimizer
        setpoint; v_cmd_corrected folds in the driver-deviation response."""
        v_ceil = self.ceiling_ms[min(i + 1, self.n - 1)]
        v_hi = min(self.v_max_ms, v_ceil)
        if v_hi <= 1e-3:                       # forced stop (stop zone / hard corner)
            return 0.0, 0.0, "tracking"
        v_lo = min(self.v_min_ms, v_hi)
        candidates = np.linspace(v_lo, v_hi, self.n_candidates)

        w_du = self.theta["w_du"]
        w_drv = self.theta["w_drv"]
        # deep-learning driver-intent prediction for THIS step (km/h -> m/s)
        drv_pred_ms = self.dl.predict_next_state({
            "speed_kmh": v0_ms * 3.6,
            "acceleration_ms2": driver_state.get("a_actual_ms2", 0.0),
            "throttle_pct": driver_state.get("throttle_pct", 0.0),
            "brake_pct": driver_state.get("brake_pct", 0.0),
            "steering_angle_deg": 0.0,
            "ambient_temp_c": self.scenario.temperature_c,
            "wind_speed_ms": self.scenario.wind_speed_kmh / 3.6,
        }) / 3.6

        best_J, best_cmd = np.inf, float(candidates[0])
        for vc in candidates:
            J = self._rollout_cost(i, float(vc), v0_ms)
            J += w_du * (vc - last_cmd_ms) ** 2
            J += w_drv * (vc - drv_pred_ms) ** 2
            if J < best_J:
                best_J, best_cmd = J, float(vc)

        # driver-awareness modes (MPC_SPEC 6.3)
        dev = driver_state.get("deviation_ms", 0.0)
        cum = driver_state.get("deviation_cumsum_ms", 0.0)
        alpha = self.theta["alpha_drv"]
        mode = "tracking"
        v_corr = best_cmd
        if abs(cum) > config.MPC_DRIVER_BIAS_THRESHOLD_MS:
            mode = "bias_detected"
            v_corr = best_cmd + alpha * dev
        elif abs(dev) >= config.MPC_DRIVER_DEVIATION_THRESHOLD_MS:
            mode = "correction"
            v_corr = best_cmd + alpha * dev
        v_corr = float(np.clip(v_corr, 0.0, v_ceil))
        return best_cmd, v_corr, mode

    # --- live single-shot query (driver_advisory_bridge.py) ----------------
    def recommend(self, s_query_m: float, v_now_kmh: float, driver_state: dict,
                  last_cmd_ms: float) -> dict:
        """One-off version of the run_closed_loop() inner step, for a LIVE
        telemetry snapshot instead of an offline full-attempt rollout: solve
        a single control decision at whatever station is nearest s_query_m,
        using the driver's ACTUAL current speed as v0 -- this is what makes
        it genuinely adaptive (see the module docstring), as opposed to
        driver_advisory.current_strategy()'s table lookup, which only ever
        answers "what did the pre-baked run do at this station" regardless
        of whether the live driver is actually tracking that run's speed.

        Caller (driver_advisory_bridge.py) owns driver_state/last_cmd_ms
        persistence across snapshots -- this method is stateless per call."""
        i = min(int(np.searchsorted(self.s_m, s_query_m, side="left")), self.n - 2)
        v0_ms = v_now_kmh / 3.6
        v_cmd, v_corr, mode = self.solve_step(i, v0_ms, driver_state, last_cmd_ms)

        v_ceil = self.ceiling_ms[min(i + 1, self.n - 1)]
        v_hi = min(self.v_max_ms, v_ceil)
        if v_hi <= 1e-3:
            action = "brake"
        elif v_corr > v0_ms + 1e-3:
            action = "gas"
        else:
            action = "glide"

        result = {
            "action": action,
            "target_speed_kmh": v_corr * 3.6,
            "v_cmd_kmh": v_cmd * 3.6,
            "mode": mode,
            "s_m": float(self.s_m[i]),
        }
        if self.latitude is not None:
            result["latitude"] = float(self.latitude[i])
            result["longitude"] = float(self.longitude[i])
        return result

    def dynamic_glide_distance(self, s_now_m: float, v_now_kmh: float, target_s_m: float, target_v_kmh: float) -> float:
        """
        Dynamically calculate how far BEFORE target_s_m the car must lift off and start
        gliding from v_now_kmh to naturally coast down to target_v_kmh by target_s_m,
        using the SAME natural-coast physics as compute_glide_ceiling() (drag + rolling
        resistance only, motor off) -- the real driving technique this whole module's
        docstring describes (telemetry: only 18/2936 points ever brake). Returns distance
        from s_now_m to the required lift-off point.

        Deliberately NEVER assumes active-braking-capable deceleration, even close to a
        stop (previously it switched to BRAKE_MAX_MS2 inside STOP_GLIDE_LOOKAHEAD_M,
        which -- because that whole 150m window is exactly the range real glide-start
        points fall in -- made the returned distance answer "how late could I leave it
        and still brake", not "where should I actually lift off for an efficient glide";
        confirmed on real telemetry, it was returning single-digit-metre gaps to the stop
        line for a 26 km/h approach, discarding nearly the whole coast-down opportunity).
        If pure natural coast genuinely can't shed enough speed before reaching s_now_m
        (loop exhausts without reaching v_now_ms), that's an honest "0 -- you're already
        past the ideal lift-off point, act now" rather than a fabricated brake-based number.
        """
        v_target_ms = target_v_kmh / 3.6
        v_now_ms = v_now_kmh / 3.6
        if v_now_ms <= v_target_ms + 1e-3:
            return float(max(0.0, target_s_m - s_now_m))  # Already slow enough, glide starts at the target

        i_target = min(int(np.searchsorted(self.s_m, target_s_m, side="left")), self.n - 1)
        i_now = max(0, min(int(np.searchsorted(self.s_m, s_now_m, side="left")), self.n - 1))

        if i_target <= i_now:
            return 0.0

        v = v_target_ms
        import math
        from . import vehicle
        for k in range(i_target - 1, i_now - 1, -1):
            ds = self.s_m[k + 1] - self.s_m[k]
            f_res = vehicle.resistance_force_n(v * 3.6, self.grade[k], self.scenario, self.heading[k], r_min_m=self.r_min[k])
            a_coast = max(0.0, f_res) / config.MASS_TOTAL_KG

            v = math.sqrt(max(0.0, v**2 + 2 * a_coast * ds))

            if v >= v_now_ms:
                return float(max(0.0, self.s_m[k] - s_now_m))

        return 0.0  # Need to act immediately -- pure coast alone can't make it from here

    def dynamic_target_speed_kmh(self, s_now_m: float, v_now_kmh: float,
                                 target_s_m: float, v_safe_kmh: float) -> float:
        """
        Dynamically recompute the speed to CARRY INTO an upcoming turn/stop, given the
        driver's ACTUAL current speed and the fixed remaining distance -- instead of
        repeating the same static offline-table target regardless of how the live
        driver is actually doing.

        Forward-integrates natural coast-down (motor off, drag + rolling resistance
        only -- same physics as dynamic_glide_distance()/compute_glide_ceiling(), no new
        model) from v_now_kmh over the fixed distance to target_s_m, to find what speed
        is genuinely achievable by lift-off alone. Returns min(achievable, v_safe_kmh):
        - If natural coast alone already gets below v_safe_kmh, there's slack -- the
          honest target is v_safe_kmh itself (no need to shed more speed than required).
        - If the driver is going too fast for natural coast alone to reach v_safe_kmh in
          the distance left, achievable > v_safe_kmh; the target is still v_safe_kmh (the
          safety-mandated entry speed), it just means active braking, not only lift-off,
          will be needed to actually hit it -- this function doesn't hide that by
          reporting a higher, more "comfortable" number.
        """
        if v_now_kmh <= v_safe_kmh + 1e-6:
            # Already at or under the safe entry speed -- there's no excess speed to
            # shed, so there's nothing for a coast-down forecast to usefully add here.
            # Returning the coast-forward value anyway would keep reducing it the
            # further out the query runs (down toward 0 given enough distance), which
            # reads as "brake to a stop" advice for a driver who is already fine --
            # confirmed on real track data: a driver already at 20 km/h approaching a
            # 26 km/h corner 170 m out got told to bring 0.00 km/h. v_safe_kmh itself
            # is the honest target: there's slack, not a deficit.
            return float(v_safe_kmh)

        i_now = max(0, min(int(np.searchsorted(self.s_m, s_now_m, side="left")), self.n - 1))
        i_target = min(int(np.searchsorted(self.s_m, target_s_m, side="left")), self.n - 1)
        if i_target <= i_now:
            return float(v_safe_kmh)

        import math
        from . import vehicle
        v = v_now_kmh / 3.6
        for k in range(i_now, i_target):
            ds = self.s_m[k + 1] - self.s_m[k]
            f_res = vehicle.resistance_force_n(v * 3.6, self.grade[k], self.scenario, self.heading[k], r_min_m=self.r_min[k])
            a_coast = max(0.0, f_res) / config.MASS_TOTAL_KG
            v = math.sqrt(max(0.0, v**2 - 2 * a_coast * ds))

        return float(min(v * 3.6, v_safe_kmh))

    def update_estimates(self, actual_state: dict, i: int):
        """Level-2 online estimation hook (MPC_SPEC 4.2). PLACEHOLDER -- wire onboard
        sensor corrections (Crr_eff, aero bias, SOC sync) here when available."""
        # PLACEHOLDER -- online estimation (needs onboard sensors)
        return


def run_closed_loop(full_track, scenario, motor, fc, theta=None,
                    dl_predictor: DLPredictor = None,
                    driver_deviation_fn=None,
                    adaptive: bool = False,
                    n_candidates: int = config.MPC_N_CANDIDATES,
                    accel_motor: powertrain.MotorModel = None,
                    cruise_motor: powertrain.MotorModel = None,
                    motor_select_mode: str = config.MOTOR_SELECT_MODE_DEFAULT,
                    cruise_converter: powertrain.ConverterModel = None) -> pd.DataFrame:
    """
    Drive the MPC controller over the whole attempt and return telemetry.

    `driver_deviation_fn(i, v_cmd_corrected_ms, v0_ms) -> v_actual_target_ms` optionally
    injects a real/synthetic driver that deviates from the setpoint; default None means
    the driver follows the corrected command exactly (deviation 0). Output columns match
    simulate() plus: v_cmd_mpc, v_cmd_corrected, driver_deviation, mpc_mode,
    driver_throttle_pct, driver_brake_pct.
    """
    mpc = MPCController(full_track, scenario, motor, fc, theta=theta,
                        dl_predictor=dl_predictor, adaptive=adaptive,
                        n_candidates=n_candidates, accel_motor=accel_motor,
                        cruise_motor=cruise_motor, motor_select_mode=motor_select_mode)
    n = mpc.n

    v_ms = np.zeros(n); a_ms2 = np.zeros(n); t_s = np.zeros(n)
    f_traction_n = np.zeros(n); f_drag_n = np.zeros(n); f_roll_n = np.zeros(n)
    f_grade_n = np.zeros(n); f_cornering_n = np.zeros(n)
    p_wheel_w = np.zeros(n); p_motor_mech_w = np.zeros(n); p_motor_elec_w = np.zeros(n)
    p_fc_elec_w = np.zeros(n); h2_flow_m3_s = np.zeros(n); h2_cumulative_m3 = np.zeros(n)
    accessory_energy_cumulative_j = np.zeros(n)
    motor_clipped = np.zeros(n, dtype=bool); motor_state = np.empty(n, dtype=object)
    rule_violation = np.zeros(n, dtype=bool)
    active_motor_name = np.empty(n, dtype=object)   # which of the two motors is engaged
    soc_wh = np.zeros(n)  # kept always-zero for output schema stability (matches margin/driver_sim.py) --
                          # the generic placeholder buffer model this once tracked was removed 2026-07-25;
                          # the real energy-storage system is the FC+supercap hybrid (hybrid_energy.py)
    # MPC diagnostics
    v_cmd_mpc = np.zeros(n); v_cmd_corr = np.zeros(n); driver_dev = np.zeros(n)
    mpc_mode = np.empty(n, dtype=object)
    driver_throttle = np.zeros(n); driver_brake = np.zeros(n)

    v_ms[0] = 0.0
    last_cmd_ms = 0.0
    dev_cumsum = 0.0
    a_prev = 0.0
    # two-motor relaunch state (armed at each stop, cleared once back up to cruise or the
    # accel window elapses) -- drives which motor simulate.step() engages, same as simulate()
    relaunching = True
    t_launch = 0.0
    cruise_ms = config.V_TARGET_AVG_KMH_CRUISE / 3.6
    # dwell-hysteresis state (MOTOR_MIN_DWELL_S) -- mirrors simulate()'s own loop; without
    # this, step()'s per-call _pick_motor() has no memory and chatters near the two motors'
    # efficiency-curve crossover (see step()'s current_motor/dwell_elapsed_s docstring).
    active_motor = None
    t_last_switch = 0.0

    for i in range(n - 1):
        ds = mpc.ds[i]
        driver_state = {
            "a_actual_ms2": a_prev,
            "deviation_ms": driver_dev[i - 1] if i > 0 else 0.0,
            "deviation_cumsum_ms": dev_cumsum,
            "throttle_pct": driver_throttle[i - 1] if i > 0 else 0.0,
            "brake_pct": driver_brake[i - 1] if i > 0 else 0.0,
        }
        v_cmd, v_corr, mode = mpc.solve_step(i, v_ms[i], driver_state, last_cmd_ms)

        # driver's actual target speed for the next step
        if driver_deviation_fn is not None:
            v_drv_target = float(driver_deviation_fn(i, v_corr, v_ms[i]))
        else:
            v_drv_target = v_corr
        # gas toward the target while below it; glide (motor off) once at/above it, so the
        # MPC pulse-and-glides instead of accelerate-then-brake (glide handled in sim.step).
        v_ceil_next = mpc.ceiling_ms[min(i + 1, mpc.n - 1)]
        a_safety = (v_ceil_next ** 2 - v_ms[i] ** 2) / (2 * ds) if ds > 0 else 0.0
        if v_drv_target > v_ms[i]:
            v_gas = min(v_drv_target, v_ceil_next)
            a_des = (v_gas ** 2 - v_ms[i] ** 2) / (2 * ds) if ds > 0 else 0.0
            glide_step = False
        else:
            a_des, glide_step = a_safety, True

        # relaunch arming (two-motor): armed at a stop row, cleared once back to cruise
        # speed or after the accel window -- ties the accel motor to real departures.
        if mpc.stop_event[i]:
            if not relaunching:
                relaunching = True
                t_launch = t_s[i]
        elif relaunching and (v_ms[i] >= cruise_ms or (t_s[i] - t_launch) >= config.MOTOR_ACCEL_WINDOW_S):
            relaunching = False

        res = sim_mod.step(v_ms[i], ds, mpc.grade[i], mpc.heading[i], mpc.r_min[i],
                           a_des, scenario, motor, fc,
                           accel_motor=mpc.accel_motor, cruise_motor=mpc.cruise_motor,
                           motor_select_mode=mpc.motor_select_mode, relaunching=relaunching,
                           glide=glide_step, current_motor=active_motor,
                           dwell_elapsed_s=(t_s[i] - t_last_switch),
                           cruise_converter=cruise_converter)

        # dwell-hysteresis bookkeeping: only reset the switch clock when the ENGAGED
        # motor (res.active_motor_id, post-hysteresis) actually changed, not the raw
        # per-step preference -- that's what makes the dwell timer mean anything.
        if mpc.two_motor:
            new_active = mpc.accel_motor if res.active_motor_id == 1 else mpc.cruise_motor
            if active_motor is None or new_active is not active_motor:
                t_last_switch = t_s[i]
            active_motor = new_active

        # record physics
        a_ms2[i] = res.a
        f_traction_n[i] = res.f_traction; f_drag_n[i] = res.f_drag
        f_roll_n[i] = res.f_roll; f_grade_n[i] = res.f_grade
        f_cornering_n[i] = res.f_cornering
        p_wheel_w[i] = res.p_wheel; p_motor_mech_w[i] = res.p_motor_mech
        p_motor_elec_w[i] = res.p_motor_elec; p_fc_elec_w[i] = res.p_fc_elec
        h2_flow_m3_s[i] = res.h2_flow_m3_s
        h2_cumulative_m3[i + 1] = h2_cumulative_m3[i] + res.h2_flow_m3_s * res.dt
        motor_clipped[i] = res.motor_clipped; motor_state[i] = res.motor_state
        active_motor_name[i] = res.active_motor_name
        accessory_energy_cumulative_j[i + 1] = (accessory_energy_cumulative_j[i]
                                                + config.ACCESSORY_LOAD_W_CONTINUOUS * res.dt)

        # MPC diagnostics + driver deviation bookkeeping
        v_cmd_mpc[i] = v_cmd * 3.6
        v_cmd_corr[i] = v_corr * 3.6
        deviation = res.v_next - v_corr           # actual - commanded (m/s)
        driver_dev[i] = deviation
        dev_cumsum += deviation
        mpc_mode[i] = mode
        # throttle/brake ESTIMATED FROM ACCELERATION -- replace with sensor data when available
        if res.a >= 0:
            driver_throttle[i] = min(100.0, res.a / config.ACCEL_MAX_MS2 * 100.0)
        else:
            driver_brake[i] = min(100.0, abs(res.a) / config.BRAKE_MAX_MS2 * 100.0)

        if mpc.ceiling_ms[i] * 3.6 < mpc.v_safe_kmh[i] - 1e-6 and v_ms[i] * 3.6 > mpc.v_safe_kmh[i] + 1e-6:
            rule_violation[i] = True

        # advance time + stop dwell (Art. 227)
        t_s[i + 1] = t_s[i] + res.dt
        if mpc.stop_event[i + 1] and res.v_next < 0.5:
            t_s[i + 1] += config.STOP_DWELL_TIME_S
        v_ms[i + 1] = res.v_next
        last_cmd_ms = v_corr
        a_prev = res.a

    motor_state[-1] = motor_state[-2]
    mpc_mode[-1] = mpc_mode[-2]
    active_motor_name[-1] = active_motor_name[-2]

    out = full_track.copy()
    out["t_s"] = t_s
    out["v_kmh"] = v_ms * 3.6
    out["a_ms2"] = a_ms2
    out["v_ceiling_kmh"] = mpc.ceiling_ms * 3.6
    out["f_traction_n"] = f_traction_n
    out["f_drag_n"] = f_drag_n
    out["f_roll_n"] = f_roll_n
    out["f_grade_n"] = f_grade_n
    out["f_cornering_n"] = f_cornering_n
    out["p_wheel_w"] = p_wheel_w
    out["p_motor_mech_w"] = p_motor_mech_w
    out["p_motor_elec_w"] = p_motor_elec_w
    out["p_fc_elec_w"] = p_fc_elec_w
    out["h2_flow_m3_s"] = h2_flow_m3_s
    out["h2_cumulative_m3"] = h2_cumulative_m3
    out["accessory_energy_cumulative_j"] = accessory_energy_cumulative_j
    out["buffer_soc_wh"] = soc_wh
    out["motor_clipped"] = motor_clipped
    out["motor_state"] = motor_state
    out["active_motor"] = active_motor_name
    out["weather_scenario"] = scenario.name
    if mpc.two_motor:
        out["motor_name"] = f"{accel_motor.name} + {cruise_motor.name}"
    else:
        out["motor_name"] = motor.name if motor is not None else None
    out["fc_name"] = fc.name if fc is not None else None
    out["rule_violation"] = rule_violation
    # MPC-specific diagnostics (MPC_SPEC 6.4)
    out["v_cmd_mpc"] = v_cmd_mpc
    out["v_cmd_corrected"] = v_cmd_corr
    out["driver_deviation"] = driver_dev
    out["mpc_mode"] = mpc_mode
    out["driver_throttle_pct"] = driver_throttle
    out["driver_brake_pct"] = driver_brake
    # Source the demand through the hybrid FC + supercapacitor system (FC held at 62%, supercap
    # buffers transients, hydrogen re-billed via the joulemeter formula) -- same as simulate().
    out = hybrid_energy.apply_hybrid(out)
    return out


def score_telemetry(tel: pd.DataFrame) -> dict:
    """Art. 54e net score + audit for an MPC closed-loop telemetry frame."""
    total_dist_km = tel["s_m"].iloc[-1] / 1000.0
    total_time_s = tel["t_s"].iloc[-1]
    total_h2_m3 = tel["h2_cumulative_m3"].iloc[-1]
    accessory_j = tel["accessory_energy_cumulative_j"].iloc[-1]
    score = telemetry_mod.h2_score_km_per_m3(total_dist_km, total_h2_m3, accessory_energy_j=accessory_j)
    return {
        "distance_km": total_dist_km,
        "time_min": total_time_s / 60.0,
        "h2_l": total_h2_m3 * 1000.0,
        "score_km_per_m3": score,
        "time_ok": total_time_s <= config.MAX_ATTEMPT_TIME_MIN * 60.0,
        "rule_violations": int(tel["rule_violation"].sum()),
    }


def optimize_strategy(scenario_name="typical_january",
                      accel_motor_name=config.ACCEL_MOTOR_NAME,
                      cruise_motor_name=config.CRUISE_MOTOR_NAME,
                      motor_name=config.DEFAULT_MOTOR_NAME,
                      fc_name=config.DEFAULT_FC_NAME, theta=None, laps=config.TOTAL_LAPS,
                      use_two_motor=True, motor_select_mode=config.MOTOR_SELECT_MODE_DEFAULT,
                      use_racing_line=True, save=True, n_candidates=None):
    """Run one MPC closed loop end-to-end with a fixed theta (no GA); returns
    (telemetry, score).

    Defaults to the REAL current digital-twin configuration -- the two-motor Urban-Concept
    split on the RACING-LINE profile -- so this matches optimize_ga/optimize_cma exactly.
    (Previously this convenience entry point silently ran single-motor on the raw GPS
    backbone, which did NOT reflect the validated hardware config.) Set use_two_motor=False
    for a single `motor_name` run, or use_racing_line=False for the raw centerline profile.
    GA/PSO tuning of theta lives in optimize_ga/optimize_pso.

    theta/n_candidates default to BEST_THETA/BEST_N_CANDIDATES (the validated,
    competition-legal hyperparameters), NOT resolve_theta(None)'s raw
    config.MPC_THETA_DEFAULT -- the raw defaults under-penalize time and finish
    around 49 min, over the 35-min cap (time_ok=False); see BEST_THETA's comment
    for where the tuned values came from. Pass theta=config.MPC_THETA_DEFAULT
    explicitly if you actually want the untuned baseline."""
    if theta is None:
        theta = BEST_THETA
    if n_candidates is None:
        n_candidates = BEST_N_CANDIDATES
    if use_racing_line:
        profile_1lap = track_mod.build_racing_line_profile(save=False)
    else:
        profile_1lap = track_mod.build_track_profile(save=False)
    full_track = sim_mod.build_full_attempt_track(profile_1lap, laps=laps)
    scenario = weather_mod.SCENARIOS[scenario_name]
    fc = powertrain.load_fuel_cells()[fc_name]
    motors = powertrain.load_motors()
    if use_two_motor:
        accel_motor = motors[accel_motor_name]
        cruise_motor = motors[cruise_motor_name]
        tel = run_closed_loop(full_track, scenario, None, fc, theta=theta,
                              n_candidates=n_candidates,
                              accel_motor=accel_motor, cruise_motor=cruise_motor,
                              motor_select_mode=motor_select_mode)
    else:
        tel = run_closed_loop(full_track, scenario, motors[motor_name], fc,
                              theta=theta, n_candidates=n_candidates)
    result = score_telemetry(tel)
    if save:
        tel.to_csv(TELEMETRY_CSV, index=False)
    return tel, result


if __name__ == "__main__":
    print("Running MPC closed loop (BEST_THETA, 1 lap for a quick check)...")
    tel, result = optimize_strategy(laps=1, save=False)
    print(f"  DL predictor: {DLPredictor()}")
    for k, v in result.items():
        print(f"  {k:18} = {v}")

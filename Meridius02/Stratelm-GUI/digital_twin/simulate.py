"""
Digital twin forward simulator. Days 2-3 milestone proved the physics
end-to-end with an idealized unlimited-power powertrain; Days 3-4 wires in
the real motor efficiency lookup, FC efficiency curve, and Art. 54e H2
scoring (this file). The strategy is still "constant-speed-with-turn/stop-
slowdowns", not the actual gas/glide optimizer output -- that's Days 5-7's
GA, sitting on top of this same simulate() function as its fitness
evaluator.

FC+supercapacitor hybrid energy accounting (real Maxwell BMOD0058-E016-C02
hardware) is applied as a post-processing pass over this file's raw H2/power
output -- see hybrid_energy.apply_hybrid(), called near the end of simulate().

Output columns match the schema in the project plan so later refinement is
additive, not a redesign.
"""

import math
from dataclasses import dataclass

import numpy as np
import pandas as pd

from . import config
from . import hybrid_energy
from . import powertrain
from . import telemetry as telemetry_mod
from . import track as track_mod
from . import vehicle
from . import weather as weather_mod

TELEMETRY_CSV = "data/simulated_telemetry_crude.csv"


@dataclass
class StepResult:
    """One integrated physics step (see step()). Pure data -- no side effects."""
    v_next: float          # speed at the end of the step (m/s)
    a: float               # REALIZED acceleration after the power-limit clip (m/s^2)
    dt: float              # time to traverse the step (s)
    f_traction: float      # net traction force at the wheel (N); <0 = braking
    f_drag: float
    f_roll: float
    f_grade: float
    f_cornering: float
    p_wheel: float         # mechanical power at the wheel (W)
    p_motor_mech: float    # motor shaft power (W)
    p_motor_elec: float    # motor electrical input (W)
    p_fc_elec: float       # FC electrical output incl. parasitic BOP load (W)
    h2_flow_m3_s: float    # instantaneous H2 volume flow (m^3/s)
    motor_clipped: bool    # motor maxed out (couldn't meet the demanded acceleration)
    motor_state: str       # "accel" (gas) / "cruise" (glide/coast) / "brake"
    active_motor_id: int   # 0 = single motor, 1 = accel motor, 2 = cruise motor
    active_motor_name: str


def step(v0_ms: float, ds: float, grade_pct: float, heading_deg: float, r_min_m: float,
         a_des: float, scenario: weather_mod.WeatherScenario,
         motor: powertrain.MotorModel, fc: powertrain.FuelCellModel,
         accel_motor: powertrain.MotorModel = None,
         cruise_motor: powertrain.MotorModel = None,
         motor_select_mode: str = "efficiency", relaunching: bool = False,
         glide: bool = False,
         drivetrain_eff: float = config.DRIVETRAIN_EFFICIENCY_ASSUMED,
         accel_cap_ms2: float = config.ACCEL_MAX_MS2,
         cruise_converter: powertrain.ConverterModel = None,
         current_motor: powertrain.MotorModel = None,
         dwell_elapsed_s: float = None) -> StepResult:
    """
    Pure single-step forward integration used by the MPC horizon rollout and closed
    loop (MPC_SPEC section 9). Given a DESIRED acceleration, it applies the same
    power-limit feedback and motor-selection logic as simulate() and returns the
    REALIZED state -- all physics comes from vehicle.py / powertrain.py, no new
    equations here (MPC_SPEC 12.2).

    Pass accel_motor + cruise_motor for the two-motor Urban-Concept split (the
    controller then also reports WHICH motor drives each step); otherwise the single
    `motor` is used, so existing single-motor callers are unchanged.

    glide=True actuates a COAST (motor off): the applied acceleration is the gentler of
    the natural coast-down (-f_res/m) and the passed `a_des` (used as a safety brake cap),
    so shedding speed never burns fuel or brakes harder than the road demands -- the same
    gas/glide semantics simulate() uses, so the MPC pulse-and-glides instead of
    accelerate-then-brake.

    current_motor + dwell_elapsed_s: same MOTOR_MIN_DWELL_S hysteresis simulate()'s own
    loop applies, threaded through here instead of duplicated, since mpc.run_closed_loop()
    calls this function per-step rather than simulate()'s inline loop. Without it, a
    stateless _pick_motor() call every step just returns whichever motor is more efficient
    for THAT exact instant's power demand, and once the demand sits near the two motors'
    efficiency-curve crossover, tiny step-to-step power wobble flips the choice every
    step (confirmed: 1617/2936 rows in an MPC run). Passing the previously-engaged motor
    + how long it's been engaged lets the same "stay put unless dwell elapsed or the
    current motor physically can't supply the demand" rule apply here too. Omit both
    (default None) to get the old stateless behavior (e.g. horizon-rollout cost evaluation,
    which doesn't track a real timeline).
    """
    v_kmh_i = v0_ms * 3.6
    f_res = vehicle.resistance_force_n(v_kmh_i, grade_pct, scenario, heading_deg, r_min_m=r_min_m)
    if glide:
        a_coast = -f_res / config.MASS_TOTAL_KG          # motor-off natural deceleration
        a_des = min(a_des, a_coast)                       # brake only if safety cap is steeper
    a_applied = float(np.clip(a_des, -config.BRAKE_MAX_MS2, accel_cap_ms2))
    f_traction = config.MASS_TOTAL_KG * a_applied + f_res
    desired_mech_w = max(0.0, f_traction) * v0_ms / drivetrain_eff

    two_motor = accel_motor is not None and cruise_motor is not None
    if two_motor:
        desired = _pick_motor(desired_mech_w, relaunching, grade_pct,
                              accel_motor, cruise_motor, motor_select_mode)
        if current_motor is None or desired is current_motor:
            active = desired
        else:
            must_switch = desired_mech_w > current_motor.max_mech_power_w()
            dwell_ok = dwell_elapsed_s is not None and dwell_elapsed_s >= config.MOTOR_MIN_DWELL_S
            active = desired if (must_switch or dwell_ok) else current_motor
    else:
        active = motor

    # Power-limit feedback (identical rule to simulate()): a motor can exert at most
    # P_max*eta/v of wheel force; if the target needs more, the car accelerates less.
    power_limited = False
    if active is not None and f_traction > 0.0 and v0_ms > 0.3:
        f_traction_max = active.max_mech_power_w() * drivetrain_eff / v0_ms
        if f_traction > f_traction_max:
            power_limited = True
            a_applied = float(np.clip((f_traction_max - f_res) / config.MASS_TOTAL_KG,
                                      -config.BRAKE_MAX_MS2, accel_cap_ms2))

    v_next = math.sqrt(max(0.0, v0_ms ** 2 + 2 * a_applied * ds))
    v_avg = max(0.5 * (v0_ms + v_next), 0.05)
    dt = ds / v_avg if ds > 0 else 0.0
    f_traction = config.MASS_TOTAL_KG * a_applied + f_res  # consistent with realized a

    f_drag = vehicle.drag_force_n(v_kmh_i, scenario, heading_deg)
    f_roll = vehicle.rolling_resistance_n(grade_pct)
    f_grade = vehicle.grade_force_n(grade_pct)
    f_corner = vehicle.cornering_drag_n(v_kmh_i, r_min_m)
    p_wheel = max(0.0, f_traction) * v0_ms
    motor_state = "brake" if f_traction < -1.0 else ("accel" if f_traction > 1.0 else "cruise")

    p_motor_mech = p_wheel / drivetrain_eff
    p_motor_elec = p_fc_elec = h2_flow = 0.0
    clipped = power_limited
    if active is not None and fc is not None:
        p_motor_elec, clip2 = active.electrical_power_w(p_motor_mech)
        clipped = power_limited or clip2
        # Cruise motor (24V) draws through a buck converter off the 48V bus -- that
        # conversion loss is on top of the motor's own electrical draw. The accel
        # motor (48V) sits directly on the bus, so it's untouched. See
        # config.CRUISE_CONVERTER_NAME.
        if two_motor and cruise_converter is not None and active is cruise_motor:
            p_motor_elec = cruise_converter.input_power_w(p_motor_elec)
        # Buffer (3x BMOD0058 supercap, team-confirmed 2026-07-23) sits between the FC
        # and the ACCEL motor ONLY -- the cruise motor draws straight from the FC, no
        # buffer stage, so it doesn't pay the buffer's conversion loss. Single-motor mode
        # (no accel/cruise split) keeps the original FC->buffer->motor assumption.
        through_buffer = (not two_motor) or (active is accel_motor)
        buffer_eff = config.POWERTRAIN_BUFFER_EFFICIENCY_ASSUMED if through_buffer else 1.0
        p_fc_elec = p_motor_elec / buffer_eff + config.FC_PARASITIC_LOAD_W
        h2_flow = fc.h2_volume_flow_m3_s(p_fc_elec)

    if two_motor:
        active_id = 1 if active is accel_motor else 2
    else:
        active_id = 0
    return StepResult(v_next, a_applied, dt, f_traction, f_drag, f_roll, f_grade, f_corner,
                      p_wheel, p_motor_mech, p_motor_elec, p_fc_elec, h2_flow, clipped,
                      motor_state, active_id, active.name if active is not None else None)


def build_full_attempt_track(profile_1lap: pd.DataFrame, laps: int = config.TOTAL_LAPS) -> pd.DataFrame:
    """Tile the single-lap profile to the full attempt, with continuous distance and a lap column."""
    lap_len_km = profile_1lap["distance_km"].iloc[-1]
    tiles = []
    for lap in range(laps):
        tile = profile_1lap.copy()
        tile["distance_km"] = tile["distance_km"] + lap * lap_len_km
        tile["distance_m"] = tile["distance_km"] * 1000.0
        tile["lap"] = lap + 1
        tiles.append(tile)
    full = pd.concat(tiles, ignore_index=True)
    full["s_m"] = full["distance_m"]
    return full


def compute_speed_ceiling(full_track: pd.DataFrame, cruise_kmh: float = config.V_TARGET_AVG_KMH_CRUISE,
                           brake_max_ms2: float = config.BRAKE_MAX_MS2) -> np.ndarray:
    """
    Backward pass: max speed at each point such that the vehicle can still
    decelerate (at brake_max_ms2) down to every upcoming v_safe / stop-event
    constraint. This is what makes the crude milestone's simple forward
    controller physically feasible (no "instant" braking required), without
    yet being the actual energy-optimal strategy (that's the DP/GA phase).
    """
    n = len(full_track)
    v_safe_kmh = full_track["v_safe_kmh"].to_numpy(copy=True)
    v_safe_kmh[full_track["stop_event"].to_numpy()] = 0.0
    s_m = full_track["s_m"].to_numpy()

    ceiling_ms = np.empty(n)
    cruise_ms = cruise_kmh / 3.6
    ceiling_ms[-1] = min(cruise_ms, v_safe_kmh[-1] / 3.6)
    for i in range(n - 2, -1, -1):
        ds = s_m[i + 1] - s_m[i]
        max_given_next = math.sqrt(max(0.0, ceiling_ms[i + 1] ** 2 + 2 * brake_max_ms2 * ds))
        ceiling_ms[i] = min(cruise_ms, v_safe_kmh[i] / 3.6, max_given_next)
    return ceiling_ms * 3.6  # back to km/h


def _pick_motor(mech_power_w: float, relaunching: bool, grade_pct: float,
                accel_motor: powertrain.MotorModel, cruise_motor: powertrain.MotorModel,
                mode: str) -> powertrain.MotorModel:
    """Which of the two motors is engaged for this operating point (ignores dwell
    hysteresis -- the caller applies that).

    STRATEGY LAYER ONLY: this decides motor usage for the efficiency simulation /
    optimizer fitness, producing guidance that surfaces in the dashboard. It is NOT
    the real car's firmware and does not actuate hardware.

    mode="efficiency" (Design B): pick the most-efficient motor that can physically
    supply the demand -- maximises instantaneous efficiency and, because the BG
    dominates at low cruise power and the BLDC at high launch/climb power, reproduces
    the accel/cruise split automatically. mode="rule" (Design A): engage the accel
    motor while relaunching from a stop-and-go or climbing, else the cruise motor --
    the switch a simple physical controller would actually implement."""
    if mode == "stopgo":
        # Trial 1 (2026-07-24): engage the accel motor ONLY while relaunching from a
        # stop-and-go -- no mid-lap climbing switch -- so the powertrain toggles motors
        # only at the 2 stop-and-go points per lap (minimum switching).
        return accel_motor if relaunching else cruise_motor
    if mode == "rule":
        climbing = grade_pct > config.INCLINE_GRADE_THRESHOLD_PCT
        return accel_motor if (relaunching or climbing) else cruise_motor
    # "efficiency"
    if mech_power_w <= 0:
        return cruise_motor  # coasting: no load, keep the low-idle cruise motor
    capable = [m for m in (accel_motor, cruise_motor) if mech_power_w <= m.max_mech_power_w()]
    if not capable:
        # neither can meet it without clipping -> the higher-ceiling motor clips least
        return max((accel_motor, cruise_motor), key=lambda m: m.max_mech_power_w())
    return max(capable, key=lambda m: m.efficiency_at_power(mech_power_w))


def simulate(full_track: pd.DataFrame, scenario: weather_mod.WeatherScenario,
             cruise_kmh: float = config.V_TARGET_AVG_KMH_CRUISE,
             motor: powertrain.MotorModel = None,
             fc: powertrain.FuelCellModel = None,
             v_target_kmh: np.ndarray = None,
             v_coast_kmh: np.ndarray = None,
             accel_motor: powertrain.MotorModel = None,
             cruise_motor: powertrain.MotorModel = None,
             motor_select_mode: str = None,
             accel_window_s: float = None,
             accel_cap_ms2: float = None,
             cruise_converter: powertrain.ConverterModel = None,
             brake_avoid_lookahead_m: float = 0.0) -> pd.DataFrame:
    n = len(full_track)
    s_m = full_track["s_m"].to_numpy()
    grade_pct = full_track["grade_pct"].to_numpy()
    heading_deg = full_track["heading_deg"].to_numpy()
    r_min_m = full_track["r_min_m"].to_numpy()
    stop_event = full_track["stop_event"].to_numpy()

    # Distance from each point to the NEXT mandatory stop ahead (inf if none
    # left). s_m is monotonically increasing across the whole tiled attempt,
    # so this is a single sorted search, not a per-lap one.
    #
    # side="right", not "left": at the exact row OF a stop (the departure point),
    # side="left" matches the stop to ITSELF, giving dist_to_stop_m=0 there -- which
    # forces effective_gliding=True (0 <= STOP_GLIDE_LOOKAHEAD_M) at the exact moment
    # the car should be launching, not gliding. Confirmed empirically (2026-07-21):
    # this silently starved every relaunch under gas/glide, invisible before because
    # the old, much stronger single motor could power through a one-step glide hiccup;
    # with the 156W two-motor cruise motor it meant the accel motor barely engaged at
    # all (8/2936 points vs 104/2936 under the crude strategy on an identical run).
    # side="right" matches a stop to the NEXT one ahead instead of itself, so a point
    # actually approaching a stop (not sitting exactly on one) is unaffected.
    stop_s = s_m[stop_event]
    if len(stop_s) > 0:
        next_stop_idx = np.searchsorted(stop_s, s_m, side="right")
        no_more_stops = next_stop_idx >= len(stop_s)
        next_stop_idx_clipped = np.clip(next_stop_idx, 0, len(stop_s) - 1)
        dist_to_stop_m = stop_s[next_stop_idx_clipped] - s_m
        dist_to_stop_m[no_more_stops] = np.inf
    else:
        dist_to_stop_m = np.full(n, np.inf)

    if v_target_kmh is not None:
        ceiling_kmh = compute_speed_ceiling(full_track, 999.0) # unbound cruise, ceiling only for safety/stops
    else:
        ceiling_kmh = compute_speed_ceiling(full_track, cruise_kmh)

    v_ms = np.zeros(n)
    a_ms2 = np.zeros(n)
    t_s = np.zeros(n)
    f_traction_n = np.zeros(n)
    f_drag_n = np.zeros(n)
    f_roll_n = np.zeros(n)
    f_grade_n = np.zeros(n)
    f_cornering_n = np.zeros(n)
    p_wheel_w = np.zeros(n)
    p_motor_mech_w = np.zeros(n)
    p_motor_elec_w = np.zeros(n)
    p_fc_elec_w = np.zeros(n)
    h2_flow_m3_s = np.zeros(n)
    h2_cumulative_m3 = np.zeros(n)
    accessory_energy_cumulative_j = np.zeros(n)
    motor_clipped = np.zeros(n, dtype=bool)
    motor_state = np.empty(n, dtype=object)
    rule_violation = np.zeros(n, dtype=bool)
    active_motor_name = np.empty(n, dtype=object)

    # Two-motor (Urban Concept) mode is active only when BOTH motors are supplied;
    # otherwise the single `motor` path is used, unchanged, so every existing caller
    # (optimizers, backend, run_crude_milestone) keeps working. STRATEGY layer only.
    two_motor = accel_motor is not None and cruise_motor is not None
    if motor_select_mode is None:
        motor_select_mode = config.MOTOR_SELECT_MODE_DEFAULT
    if accel_window_s is None:
        accel_window_s = config.MOTOR_ACCEL_WINDOW_S
    if accel_cap_ms2 is None:
        accel_cap_ms2 = config.ACCEL_MAX_MS2
    active_motor = None       # the motor engaged this step (with dwell hysteresis applied)
    t_last_switch = 0.0       # sim-time of the last motor switch, for MOTOR_MIN_DWELL_S
    switch_timer = 0.0        # remaining servo actuation time (s); traction is reduced while > 0
    relaunching = True        # accelerating away from a stop-and-go (the standing start counts)
    t_launch = 0.0            # sim-time the current relaunch began, for the accel-window cap

    is_gliding = False
    v_ms[0] = 0.0  # standing start, Art. 14/226
    for i in range(n - 1):
        ds = s_m[i + 1] - s_m[i]

        # track limit for safety
        target_ms_safety = ceiling_kmh[i + 1] / 3.6
        a_safety = (target_ms_safety ** 2 - v_ms[i] ** 2) / (2 * ds) if ds > 0 else 0.0

        if v_target_kmh is not None and v_coast_kmh is not None:
            # Gas and glide logic
            if v_ms[i] * 3.6 >= v_target_kmh[i]:
                is_gliding = True
            elif v_ms[i] * 3.6 <= v_coast_kmh[i]:
                is_gliding = False

            # Safety floor: within STOP_GLIDE_LOOKAHEAD_M of a mandatory stop,
            # glide regardless of the segment's own gas/glide gene -- the
            # optimizer's per-segment control has no visibility into exactly
            # where a stop sits inside a segment, so without this override it
            # can (and does) keep commanding "gas" until physics forces a
            # last-second BRAKE_MAX_MS2 slam a few meters out. This does NOT
            # touch is_gliding itself (so the persistent toggle still resumes
            # its normal state right after the stop) -- only this step's
            # branch decision.
            effective_gliding = is_gliding or (dist_to_stop_m[i] <= config.STOP_GLIDE_LOOKAHEAD_M)

            # Trial 2 (2026-07-24): MINIMIZE BRAKING away from stops. If a slower zone (corner)
            # is coming up within brake_avoid_lookahead_m, start coasting NOW so the car sheds
            # speed on drag/gravity and reaches the corner speed without a late brake slam. The
            # hard safety ceiling still clips v_next, so braking only happens if coasting can't
            # hold the limit -- i.e. braking is minimised, not disabled (safety preserved).
            if brake_avoid_lookahead_m > 0.0 and not effective_gliding \
                    and dist_to_stop_m[i] > config.STOP_GLIDE_LOOKAHEAD_M:
                j = np.searchsorted(s_m, s_m[i] + brake_avoid_lookahead_m)
                if j > i + 1 and ceiling_kmh[i + 1:j].min() < v_ms[i] * 3.6 - 0.5:
                    effective_gliding = True

            if effective_gliding:
                # coasting: natural deceleration
                f_res = vehicle.resistance_force_n(v_ms[i]*3.6, grade_pct[i], scenario, heading_deg[i], r_min_m=r_min_m[i])
                a_coast = -f_res / config.MASS_TOTAL_KG
                a_applied = min(a_safety, a_coast)
            else:
                # gas: accelerate to v_target
                target_ms_gas = v_target_kmh[i] / 3.6
                a_gas = (target_ms_gas ** 2 - v_ms[i] ** 2) / (2 * ds) if ds > 0 else 0.0
                a_applied = min(a_safety, a_gas)
        else:
            # crude strategy
            a_applied = a_safety

        a_applied = float(np.clip(a_applied, -config.BRAKE_MAX_MS2, accel_cap_ms2))  # DESIRED accel

        v_kmh_i = v_ms[i] * 3.6
        f_res = vehicle.resistance_force_n(v_kmh_i, grade_pct[i], scenario, heading_deg[i], r_min_m=r_min_m[i])

        # Relaunch state (two-motor "rule" mode): armed True at a stop-and-go, cleared
        # once the car reaches cruise speed OR the accel window (e.g. 15 s to 30 km/h)
        # elapses -- the cap matters on a climb where 30 km/h may not be reached in
        # time. Ties the accel motor to the real STOP_LOCATIONS_KM relaunches rather
        # than a bare speed cut -- stop-and-go 2 is on a descent, so grade alone misses it.
        # Computed BEFORE motor selection (which it drives) and independent of acceleration.
        #
        # Arming on stop_event[i] alone, NOT "and v_ms[i] < 0.5": the gas/glide
        # controller approaches a stop via forced glide (natural coast-down, see
        # STOP_GLIDE_LOOKAHEAD_M above), not the crude branch's hard-braking-capable
        # ceiling, so it doesn't reliably land under 0.5 km/h at the exact flagged
        # row -- confirmed empirically (2026-07-21): with the v_ms<0.5 condition, the
        # accel motor engaged only 8/2936 points under gas/glide vs 104/2936 under
        # crude on an identical two-motor "rule" run, starving gas/glide strategies of
        # the accel-motor launches they need to meet the time budget. stop_event is
        # only True at the 2 STOP_LOCATIONS_KM rows per lap, so arming on it alone is
        # still tightly scoped to real departures, not a broad trigger.
        if stop_event[i]:
            if not relaunching:
                relaunching = True
                t_launch = t_s[i]
        elif relaunching and (v_kmh_i >= cruise_kmh or (t_s[i] - t_launch) >= accel_window_s):
            relaunching = False

        # DESIRED traction/power to hit this step's target acceleration, then select the
        # active motor from that demand.
        f_traction = config.MASS_TOTAL_KG * a_applied + f_res
        desired_mech_w = max(0.0, f_traction) * v_ms[i] / config.DRIVETRAIN_EFFICIENCY_ASSUMED
        powertrain_on = fc is not None and (motor is not None or two_motor)
        power_limited = False
        if powertrain_on:
            if two_motor:
                desired = _pick_motor(desired_mech_w, relaunching, grade_pct[i],
                                      accel_motor, cruise_motor, motor_select_mode)
                if active_motor is None:
                    active_motor = desired
                    t_last_switch = t_s[i]
                elif desired is not active_motor:
                    # dwell hysteresis, overridden when the current motor physically
                    # can't supply the demand (a clip-forced switch)
                    must_switch = desired_mech_w > active_motor.max_mech_power_w()
                    if must_switch or (t_s[i] - t_last_switch) >= config.MOTOR_MIN_DWELL_S:
                        active_motor = desired
                        t_last_switch = t_s[i]
                        switch_timer = config.MOTOR_SWITCH_TIME_S   # servo starts actuating
            else:
                active_motor = motor

            # SERVO SWITCH PENALTY: while the servo is mid-swap the powertrain can only deliver
            # a fraction of full traction, ramping MOTOR_SWITCH_MIN_POWER_FRAC -> 1.0 as it completes.
            # This makes every accel<->cruise handoff cost a little speed, time and hydrogen.
            if switch_timer > 0.0 and config.MOTOR_SWITCH_TIME_S > 0.0:
                frac = 1.0 - switch_timer / config.MOTOR_SWITCH_TIME_S
                switch_power_factor = config.MOTOR_SWITCH_MIN_POWER_FRAC + \
                    (1.0 - config.MOTOR_SWITCH_MIN_POWER_FRAC) * min(1.0, max(0.0, frac))
            else:
                switch_power_factor = 1.0

            # POWER-LIMIT FEEDBACK (fixes the "fake speed" bug): a motor delivering at most
            # max_mech_power_w can only exert force = P_max * drivetrain_eff / v at the wheel.
            # If the target acceleration would need more traction than that, the car only gets
            # what the motor can give -- it accelerates less, or on a climb it can't hold, it
            # slows down. Below ~1 km/h the limit is torque (not power); we skip it there
            # (F = P/v blows up and the launch is torque-bound, governed by accel_cap instead).
            if f_traction > 0.0 and v_ms[i] > 0.3:
                f_traction_max = active_motor.max_mech_power_w() * switch_power_factor * config.DRIVETRAIN_EFFICIENCY_ASSUMED / v_ms[i]
                if f_traction > f_traction_max:
                    power_limited = True
                    a_applied = float(np.clip((f_traction_max - f_res) / config.MASS_TOTAL_KG,
                                              -config.BRAKE_MAX_MS2, accel_cap_ms2))

        # Finalize the motion with the REALIZED (possibly power-limited) acceleration.
        v_next_sq = max(0.0, v_ms[i] ** 2 + 2 * a_applied * ds)
        v_next = math.sqrt(v_next_sq)
        v_avg = max(0.5 * (v_ms[i] + v_next), 0.05)  # floor avoids div-by-zero at a standing start
        dt = ds / v_avg
        switch_timer = max(0.0, switch_timer - dt)   # advance the servo actuation clock

        f_traction = config.MASS_TOTAL_KG * a_applied + f_res  # consistent with realized a_applied
        a_ms2[i] = a_applied
        f_drag_n[i] = vehicle.drag_force_n(v_kmh_i, scenario, heading_deg[i])
        f_roll_n[i] = vehicle.rolling_resistance_n(grade_pct[i])
        f_grade_n[i] = vehicle.grade_force_n(grade_pct[i])
        f_cornering_n[i] = vehicle.cornering_drag_n(v_kmh_i, r_min_m[i])
        f_traction_n[i] = f_traction
        p_wheel_w[i] = max(0.0, f_traction) * v_ms[i]
        # +-1.0 N tolerance on f_traction for BOTH branches (not a bare < 0, and
        # not a_applied's sign for "accel"): f_traction nets out to +-1e-15 from
        # floating-point roundoff whenever traction is genuinely ~zero, and a
        # strict < 0 check mislabeled about half of those as "brake". Using
        # a_applied's sign for "accel" had a second, separate bug: gliding
        # downhill can show a_applied > 0 from gravity alone with f_traction
        # still exactly 0 (zero motor engagement) -- confirmed in telemetry, a
        # forced-glide approach to a stop on a downhill grade was labeling
        # genuine zero-power coasting as "accel". f_traction (actual delivered/
        # drawn force) is the one physically meaningful signal for both.
        motor_state[i] = "brake" if f_traction < -1.0 else ("accel" if f_traction > 1.0 else "cruise")
        if ceiling_kmh[i] < full_track["v_safe_kmh"].iloc[i] - 1e-6 and v_kmh_i > full_track["v_safe_kmh"].iloc[i] + 1e-6:
            rule_violation[i] = True

        if powertrain_on:
            p_motor_mech_w[i] = p_wheel_w[i] / config.DRIVETRAIN_EFFICIENCY_ASSUMED
            elec_w, clipped = active_motor.electrical_power_w(p_motor_mech_w[i])
            # Cruise motor (24V) draws through a buck converter off the 48V bus -- that
            # conversion loss is on top of the motor's own electrical draw. The accel
            # motor (48V) sits directly on the bus, so it's untouched. See
            # config.CRUISE_CONVERTER_NAME.
            if two_motor and cruise_converter is not None and active_motor is cruise_motor:
                elec_w = cruise_converter.input_power_w(elec_w)
            p_motor_elec_w[i] = elec_w
            # clipped now means "motor maxed out and the car couldn't accelerate as desired"
            # -- the motion was actually held back (no more free speed), so power_limited is
            # the meaningful signal; the electrical clip is kept as a fallback.
            motor_clipped[i] = power_limited or clipped
            active_motor_name[i] = active_motor.name
            # buffer thermal loss on the motor's share, plus the FC's own BOP load (Art. 65:
            # FC must power its own auxiliary loads), which bypasses the buffer entirely.
            # Buffer sits between FC and the ACCEL motor ONLY (team-confirmed 2026-07-23) --
            # cruise draws straight from the FC, no buffer stage/loss. Single-motor mode
            # (no accel/cruise split) keeps the original FC->buffer->motor assumption.
            through_buffer = (not two_motor) or (active_motor is accel_motor)
            buffer_eff = config.POWERTRAIN_BUFFER_EFFICIENCY_ASSUMED if through_buffer else 1.0
            p_fc_elec_w[i] = elec_w / buffer_eff + config.FC_PARASITIC_LOAD_W
            h2_flow_m3_s[i] = fc.h2_volume_flow_m3_s(p_fc_elec_w[i])
            h2_cumulative_m3[i + 1] = h2_cumulative_m3[i] + h2_flow_m3_s[i] * dt

        # separate accessory battery (Instrumentasi/Lighting/Wiper) -- NOT the FC/H2 path,
        # horn excluded per Art. 56(c)(iii) joulemeter exemption
        accessory_energy_cumulative_j[i + 1] = accessory_energy_cumulative_j[i] + config.ACCESSORY_LOAD_W_CONTINUOUS * dt

        t_s[i + 1] = t_s[i] + dt
        if stop_event[i + 1] and v_next < 0.5:
            t_s[i + 1] += config.STOP_DWELL_TIME_S
        v_ms[i + 1] = v_next

    motor_state[-1] = motor_state[-2]
    active_motor_name[-1] = active_motor_name[-2]

    out = full_track.copy()
    out["t_s"] = t_s
    out["v_kmh"] = v_ms * 3.6
    out["a_ms2"] = a_ms2
    out["v_ceiling_kmh"] = ceiling_kmh
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
    out["motor_clipped"] = motor_clipped
    out["motor_state"] = motor_state
    out["active_motor"] = active_motor_name   # which of the two motors is engaged (two-motor runs)
    out["weather_scenario"] = scenario.name
    if two_motor:
        out["motor_name"] = f"{accel_motor.name} + {cruise_motor.name}"
    else:
        out["motor_name"] = motor.name if motor is not None else None
    out["fc_name"] = fc.name if fc is not None else None
    out["rule_violation"] = rule_violation
    # Source the DC-bus demand through the hybrid FC + supercapacitor system: holds the FC at
    # its 62% operating point, buffers transients on the supercap, and re-bills hydrogen off
    # the FC energy (Art. 54e joulemeter formula). No-op if USE_HYBRID_SUPERCAP is False.
    out = hybrid_energy.apply_hybrid(out)
    return out


def run_crude_milestone(scenario_name: str = "typical_january", save: bool = True,
                         motor_name: str = config.DEFAULT_MOTOR_NAME,
                         fc_name: str = config.DEFAULT_FC_NAME) -> pd.DataFrame:
    profile_1lap = track_mod.build_track_profile(save=False)
    full_track = build_full_attempt_track(profile_1lap)
    scenario = weather_mod.SCENARIOS[scenario_name]
    motor = powertrain.load_motors()[motor_name]
    fc = powertrain.load_fuel_cells()[fc_name]
    telemetry = simulate(full_track, scenario, motor=motor, fc=fc)
    if save:
        telemetry.to_csv(TELEMETRY_CSV, index=False)
    return telemetry


if __name__ == "__main__":
    telemetry = run_crude_milestone()

    total_time_s = telemetry["t_s"].iloc[-1]
    total_dist_km = telemetry["s_m"].iloc[-1] / 1000.0
    avg_speed_kmh = total_dist_km / (total_time_s / 3600.0)
    max_speed_kmh = telemetry["v_kmh"].max()
    total_wheel_energy_wh = np.trapezoid(telemetry["p_wheel_w"], telemetry["t_s"]) / 3600.0
    total_h2_m3 = telemetry["h2_cumulative_m3"].iloc[-1]
    total_accessory_j = telemetry["accessory_energy_cumulative_j"].iloc[-1]
    accessory_h2_equiv_m3 = telemetry_mod.accessory_h2_equivalent_m3(total_accessory_j)
    h2_score = telemetry_mod.h2_score_km_per_m3(total_dist_km, total_h2_m3, accessory_energy_j=total_accessory_j)

    print(f"Built {TELEMETRY_CSV}: {len(telemetry)} points over {config.TOTAL_LAPS} laps")
    print(f"Motor: {config.DEFAULT_MOTOR_NAME} | Fuel cell: {config.DEFAULT_FC_NAME}")
    print(f"Total distance: {total_dist_km:.3f} km (rule requires {config.TOTAL_DISTANCE_KM} km)")
    print(f"Total time: {total_time_s/60:.2f} min (limit {config.MAX_ATTEMPT_TIME_MIN} min)")
    print(f"Average speed: {avg_speed_kmh:.2f} km/h (rule-derived min {config.V_TARGET_AVG_KMH_MIN:.2f} km/h)")
    print(f"Max speed reached: {max_speed_kmh:.2f} km/h")
    print(f"Total wheel energy: {total_wheel_energy_wh:.1f} Wh")
    print(f"Total H2 consumed (flow meter, incl. FC parasitic load): {total_h2_m3*1000:.4f} L ({total_h2_m3:.6f} m^3)")
    print(f"Accessory battery energy (joulemeter, excl. horn): {total_accessory_j/1000:.1f} kJ "
          f"-> {accessory_h2_equiv_m3*1000:.4f} L H2-equivalent")
    print(f"Art. 54e net score: {h2_score:.1f} km/m^3 H2")
    print(f"Motor power clipped (undersized for demand): {telemetry['motor_clipped'].sum()} points")
    print(f"Rule violations (speed > v_safe): {telemetry['rule_violation'].sum()}")
    print(f"Stop events: {telemetry['stop_event'].sum()} (rule requires {config.STOPS_PER_LAP * config.TOTAL_LAPS})")

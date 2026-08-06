"""Live driver-recommendation bridge: turns the live telemetry snapshot's
(distance, speed) into a query against digital_twin's precomputed "dynamic
strategy" tables -- digital_twin.driver_advisory's glide-ceiling table (real
driving technique: lift-and-coast into corners, active braking only near the
2 mandatory stops; also answers "next turn" -- see that module's
next_turn() docstring) and digital_twin.dp_policy's full DP backward-induction
table (state-aware re-plan from wherever the driver actually is, not just the
nominal standing-start path).

"Current strategy" (gas/glide/brake right now) prefers a third source when
available: a LIVE call into digital_twin.mpc.MPCController.recommend() --
unlike the precomputed tables above (which only ever answer "what did the
winning offline run do at this station"), MPC re-solves a fresh receding-
horizon decision from the driver's ACTUAL current speed every call, which is
the whole point of an MPC-based strategy (see mpc.py's module docstring).
Falls back to driver_advisory.current_strategy()'s table lookup if the MPC
controller fails to load or errors on a given call.

All three are precompute-once/construct-once-cheap-lookup-at-runtime by
design -- this module builds them once, lazily, and reuses them for every
snapshot.
"""

import time

import pandas as pd

# /ws/telemetry pushes one snapshot per second (main.py's websocket loop is a
# fixed 1.0 s sleep, not a measured delta-time), so a recommendation computed
# for the driver's position AT COMPUTE TIME is already stale by the time it's
# received, rendered, and read. Querying LOOKAHEAD_S ahead (dead-reckoned from
# current speed, since there's no finer-grained timing to work from) keeps the
# instruction valid for the moment the driver actually acts on it instead of
# the instant it was computed.
LOOKAHEAD_S = 0.5

# A live session's position can jump backward by more than this in one tick
# only at a genuine restart (new attempt, simulator relaunch, lap wraparound)
# -- never from normal forward driving -- so it's the signal to reset the MPC
# session state below rather than carry stale deviation/command history into
# an unrelated run.
_MPC_SESSION_RESET_JUMP_M = 500.0

_policy = None
_advisory_table = None
_attempt_length_m = None
_load_failed = False

_mpc_controller = None
_mpc_load_failed = False
_mpc_state = {
    "last_cmd_ms": None, "last_v_ms": None, "last_t": None,
    "dev_cumsum_ms": 0.0, "throttle_pct": 0.0, "brake_pct": 0.0,
    "last_s_now_m": None,
}


def _ensure_loaded():
    global _policy, _advisory_table, _attempt_length_m, _load_failed
    if _policy is not None or _load_failed:
        return
    try:
        from digital_twin import dp_policy, driver_advisory
        _policy = dp_policy.load_policy()
        _advisory_table = pd.read_csv(driver_advisory.ADVISORY_CSV)
        # Both tables cover exactly one 4-lap attempt (0 -> ~14500 m), but the
        # simulator's own Distance field is cumulative since MCU boot and never
        # resets -- over a long-running session it keeps climbing well past one
        # attempt's length. Wrap it back into the table's range the same way
        # mqtt/simulate_field.py's GpsReplay already wraps distance for GPS
        # (dist_m % lap_len_m), otherwise a long session looks permanently
        # "stuck at the finish line" to both lookups.
        _attempt_length_m = float(_policy["s_m"][-1])
    except Exception:
        _load_failed = True


def _ensure_mpc_loaded():
    """Builds the live MPCController once. Kept independent of _ensure_loaded()
    (own flag, own try/except) so a problem constructing MPC -- a missing
    motor/FC config, a slow DL-predictor import, whatever -- degrades to the
    table-based current_strategy() instead of taking down next_action/
    next_turn/dp_segment too."""
    global _mpc_controller, _mpc_load_failed
    if _mpc_controller is not None or _mpc_load_failed:
        return
    try:
        from digital_twin import config, mpc, powertrain, simulate as sim_mod, track as track_mod, weather as weather_mod
        profile_1lap = track_mod.build_racing_line_profile(save=False)
        full_track = sim_mod.build_full_attempt_track(profile_1lap)
        scenario = weather_mod.SCENARIOS["typical_january"]
        fc = powertrain.load_fuel_cells()[config.DEFAULT_FC_NAME]
        motors = powertrain.load_motors()
        accel_motor = motors[config.ACCEL_MOTOR_NAME]
        cruise_motor = motors[config.CRUISE_MOTOR_NAME]
        # BEST_THETA/BEST_N_CANDIDATES -- NOT theta=None/config defaults, which
        # under-penalize time and produce an over-the-35-min-cap (illegal) plan.
        # See mpc.py's BEST_THETA docstring: these are the exact hyperparameters
        # behind the validated MPC result this bridge tracks (253.1 km/m^3, 2026-07-24,
        # hybrid FC+supercap, 30 km/h cap; was 278.5 pre-hybrid/pre-cap).
        _mpc_controller = mpc.MPCController(
            full_track, scenario, None, fc, theta=mpc.BEST_THETA,
            n_candidates=mpc.BEST_N_CANDIDATES,
            accel_motor=accel_motor, cruise_motor=cruise_motor,
            motor_select_mode=config.MOTOR_SELECT_MODE_DEFAULT)
    except Exception:
        _mpc_load_failed = True


def _mpc_recommend(s_query_m: float, v_now_kmh: float, s_now_m: float) -> dict:
    """Live current_strategy() via MPCController.recommend(), threading the
    session state (last command, cumulative driver deviation) across calls
    the same way run_closed_loop() threads it across steps within one offline
    attempt -- reset whenever s_now_m jumps backward (new attempt/session)
    rather than carrying stale history into an unrelated run. Returns None on
    any failure so the caller can fall back to the precomputed table."""
    _ensure_mpc_loaded()
    if _mpc_load_failed:
        return None

    st = _mpc_state
    now = time.time()
    fresh = (st["last_cmd_ms"] is None or st["last_s_now_m"] is None
             or s_now_m < st["last_s_now_m"] - _MPC_SESSION_RESET_JUMP_M)
    v_now_ms = v_now_kmh / 3.6
    if fresh:
        st.update(last_cmd_ms=v_now_ms, last_v_ms=v_now_ms, last_t=now,
                   dev_cumsum_ms=0.0, throttle_pct=0.0, brake_pct=0.0)

    dt = max(now - st["last_t"], 1e-3)
    a_actual_ms2 = (v_now_ms - st["last_v_ms"]) / dt
    deviation_ms = v_now_ms - st["last_cmd_ms"]
    dev_cumsum_ms = st["dev_cumsum_ms"] + deviation_ms

    driver_state = {
        "a_actual_ms2": a_actual_ms2,
        "deviation_ms": deviation_ms,
        "deviation_cumsum_ms": dev_cumsum_ms,
        "throttle_pct": st["throttle_pct"],
        "brake_pct": st["brake_pct"],
    }

    try:
        result = _mpc_controller.recommend(s_query_m, v_now_kmh, driver_state, st["last_cmd_ms"])
    except Exception:
        return None

    st["last_cmd_ms"] = result["v_cmd_kmh"] / 3.6
    st["last_v_ms"] = v_now_ms
    st["last_t"] = now
    st["dev_cumsum_ms"] = dev_cumsum_ms
    st["last_s_now_m"] = s_now_m
    from digital_twin import config
    if a_actual_ms2 >= 0:
        st["throttle_pct"], st["brake_pct"] = min(100.0, a_actual_ms2 / config.ACCEL_MAX_MS2 * 100.0), 0.0
    else:
        st["throttle_pct"], st["brake_pct"] = 0.0, min(100.0, abs(a_actual_ms2) / config.BRAKE_MAX_MS2 * 100.0)
    return result


def _extract(latest: dict, *keys):
    for k in keys:
        if k in latest and isinstance(latest[k], (int, float)) and not isinstance(latest[k], bool):
            return float(latest[k])
    return None


def _compute_line_deviation(lat: float, lon: float, s_raw: float) -> dict:
    """Driving-LINE advisory (steering), independent of the speed advisory
    above: needs a real GPS fix (latitude/longitude from the gps topic), which
    the constant-cruise flat sim's own coordinates never provide on their own
    -- see racing_line.lateral_deviation_m's docstring. Kept decoupled from
    _load_failed/_attempt_length_m (DP-policy concerns) so a missing GPS fix
    or a DP-policy load failure can't take down the other."""
    if lat is None or lon is None or s_raw is None or s_raw < 0.0:
        return {"available": False}
    try:
        from digital_twin import racing_line
        deviation_m = racing_line.lateral_deviation_m(lat, lon, s_raw)
    except Exception:
        return {"available": False}
    return {
        "available": True,
        "deviation_m": round(float(deviation_m), 2),
        "lookahead_m": racing_line.LOOKAHEAD_M_DEFAULT,
    }


# Two selectable advisory modes (2026-07-24):
#   "dynamic"  -- current strategy prefers a LIVE MPC re-solve (_mpc_recommend()),
#                 adapting every call to the driver's actual speed/position. This is
#                 the prototype -- MPC's own known blind spot (no stop-spacing
#                 awareness, ~100m horizon) still applies to it.
#   "ga_strict" -- current strategy NEVER calls MPC at all; it's a pure static lookup
#                 against the GA-sourced advisory table (data/driver_advisory.csv),
#                 i.e. literally "follow GA's recorded gas/glide plan for wherever the
#                 table says you are," station by station, with no live adaptation.
#                 Chosen as the safe/validated baseline: GA's plan is whole-lap and
#                 stop-spacing aware (see the STOP_GLIDE_LOOKAHEAD_M test earlier),
#                 unlike MPC's live rollout.
# next_turn()/next_stop() are UNAFFECTED by this switch either way -- they were
# already made GA-sourced/static for both modes (see compute_advisory() below).
_VALID_MODES = ("dynamic", "ga_strict")
_advisory_mode = "dynamic"


def get_advisory_mode() -> str:
    return _advisory_mode


def set_advisory_mode(mode: str) -> str:
    global _advisory_mode
    if mode not in _VALID_MODES:
        raise ValueError(f"mode must be one of {_VALID_MODES}, got {mode!r}")
    _advisory_mode = mode
    return _advisory_mode


def compute_advisory(latest: dict) -> dict:
    _ensure_loaded()

    s_now_m_raw = _extract(latest, "Distance", "distance")
    v_now_kmh = _extract(latest, "Velocity", "velocity")
    lat_now = _extract(latest, "latitude")
    lon_now = _extract(latest, "longitude")
    line_deviation = _compute_line_deviation(lat_now, lon_now, s_now_m_raw)

    if _load_failed:
        return {"available": False, "line_deviation": line_deviation}

    if s_now_m_raw is None or v_now_kmh is None:
        return {"available": False, "line_deviation": line_deviation}

    # Sanitize inputs: ignore sensor spikes (e.g. 999.9 km/h or negative values)
    if v_now_kmh > 80.0 or v_now_kmh < 0.0 or s_now_m_raw < 0.0:
        return {"available": False, "line_deviation": line_deviation}

    s_now_m = s_now_m_raw % _attempt_length_m if _attempt_length_m else s_now_m_raw

    lookahead_m = (v_now_kmh / 3.6) * LOOKAHEAD_S
    s_query_m = ((s_now_m + lookahead_m) % _attempt_length_m
                 if _attempt_length_m else s_now_m + lookahead_m)

    try:
        from digital_twin import dp_policy, driver_advisory
        action = driver_advisory.next_action(_advisory_table, s_query_m, v_now_kmh)
        turn = driver_advisory.next_turn(_advisory_table, s_query_m)
        stop = driver_advisory.next_stop(_advisory_table, s_query_m)
        segment = dp_policy.recommend_segment(_policy, s_query_m, v_now_kmh)
    except Exception:
        return {"available": False}

    # "dynamic" mode tries a live MPC re-solve first (adaptive, but inherits MPC's own
    # stop-blindspot); "ga_strict" never calls MPC at all -- straight to the static
    # GA-sourced table lookup, on purpose, every time.
    strategy = _mpc_recommend(s_query_m, v_now_kmh, s_now_m) if _advisory_mode == "dynamic" else None
    strategy_is_live = strategy is not None
    if strategy is None:
        strategy = driver_advisory.current_strategy(_advisory_table, s_query_m)

    # Turn/stop advisory: mode-gated (2026-07-24 revision).
    #
    # "ga_strict" mode: next_turn()/next_stop()'s STATIC values are used as-is -- sourced
    # from data/simulated_telemetry_ga.csv via driver_advisory.build_advisory_table(),
    # which is whole-lap/stop-spacing aware because simulate()'s forced-glide-within-150m
    # rule plus GA's own (validated, whole-lap-optimized) choice of a LOWER cruise target
    # for the tight ~950m inter-stop stretch together produce a real, scored pattern
    # (confirmed: GA starts gliding ~220m before this stop at ~22 km/h, not a blind
    # full-cruise approach). No live recompute layered on top in this mode.
    #
    # "dynamic" mode: layers the live, per-query MPC physics back on top --
    # mpc.MPCController.dynamic_target_speed_kmh() (turn) / dynamic_glide_distance()
    # (stop), BOTH already hardened this session: dynamic_glide_distance() uses pure
    # natural coast-down (no longer assumes active-braking-capable deceleration for the
    # whole approach, which used to squeeze the glide window to single-digit metres),
    # and dynamic_target_speed_kmh() no longer drags the target below v_safe_kmh when
    # the driver is already under it (previously could recommend "bring 0 km/h" to a
    # driver already comfortably under the limit). These stay a per-query overlay on
    # top of the SAME GA-sourced static baseline -- they adjust for the driver's actual
    # live speed, they don't invent an independent plan -- so the whole-lap stop-spacing
    # awareness from the static values underneath is never lost, only refined.
    if turn.get("s_m") is not None:
        turn_s = turn["s_m"]
        if _attempt_length_m and _attempt_length_m > 0:
            turn["distance_m"] = float((turn_s - s_now_m) % _attempt_length_m)
        else:
            turn["distance_m"] = float(turn_s - s_now_m) if turn_s >= s_now_m else float(turn_s - s_now_m + 3630.0)

        if _advisory_mode == "dynamic" and _mpc_controller is not None:
            v_safe = turn.get("v_safe_kmh")
            static_target = turn.get("target_speed_kmh")
            if isinstance(v_safe, (int, float)) and v_safe > 0:
                # Cap the ceiling fed into the live recompute at GA's OWN validated
                # target for this turn, not the raw physics v_safe_kmh. v_safe_kmh is
                # an unbounded cornering-friction limit (sqrt(mu*g*R)) that can be far
                # beyond anything this car actually does on a wide/gentle turn (seen:
                # 75.5 km/h) -- dynamic_target_speed_kmh()'s "already under the limit,
                # no need to slow further" guard would return that raw number as-is.
                # Capping at GA's target means live mode can only refine DOWNWARD from
                # the validated plan (if the driver's actual speed genuinely can't make
                # it safely), never suggest going faster than GA already decided was
                # the efficient, safe choice.
                ceiling = min(float(v_safe), float(static_target)) if isinstance(static_target, (int, float)) else float(v_safe)
                try:
                    turn["target_speed_kmh"] = _mpc_controller.dynamic_target_speed_kmh(
                        s_now_m, v_now_kmh, s_now_m + turn["distance_m"], ceiling)
                except Exception:
                    pass  # leave the static GA-sourced target_speed_kmh in place

    if stop.get("s_m") is not None and stop.get("stop_line_distance_m") is not None:
        # Recompute stop_line_distance_m relative to s_now_m (next_stop() computed it
        # relative to s_query_m, the lookahead-shifted query position, not the driver's
        # actual current position). BUG FIXED 2026-07-24: this used to reuse stop["s_m"]
        # as if it were the stop line's own station -- it isn't. next_stop() sets "s_m"
        # to whichever station it's telling the driver to target (the GLIDE-START
        # station once one exists, only falling back to the stop line itself if the car
        # is already past glide-start) -- see next_stop()'s target_idx logic. Reusing it
        # here silently collapsed stop_line_distance_m down to nearly distance_m
        # (glide-start and "stop line" a few metres apart), which is exactly the kind
        # of falsely-tight gap already fixed once this session for a different reason.
        # The correct stop-line station is derived from next_stop()'s own (correct,
        # s_query_m-relative) stop_line_distance_m before anything overwrites it.
        true_stop_line_s = s_query_m + stop["stop_line_distance_m"]
        if _attempt_length_m and _attempt_length_m > 0:
            stop["stop_line_distance_m"] = float((true_stop_line_s - s_now_m) % _attempt_length_m)
        else:
            stop["stop_line_distance_m"] = (float(true_stop_line_s - s_now_m)
                                             if true_stop_line_s >= s_now_m
                                             else float(true_stop_line_s - s_now_m + 3630.0))

        if _advisory_mode == "dynamic" and _mpc_controller is not None:
            static_distance_m = stop.get("distance_m")
            try:
                target_s = s_now_m + stop["stop_line_distance_m"]
                dyn_distance_m = _mpc_controller.dynamic_glide_distance(
                    s_now_m, v_now_kmh, target_s, 0.0)
                # A SMALLER distance_m means "start gliding SOONER" (more conservative,
                # more time in low-power glide). dyn_distance_m > 0 is a genuine,
                # physics-computed MINIMUM -- GA's own (larger) distance is provably
                # still sufficient at that point (more margin, not less), so it's safe
                # to prefer GA's number there and avoid gliding earlier than its already
                # time-validated plan (34.99 min, under the 35-min cap) needs -- found
                # exactly this case: 54.5m vs GA's 224m, gliding ~4x sooner than
                # necessary for no efficiency reason, just this stretch's terrain making
                # coast-down locally effective.
                #
                # dyn_distance_m == 0.0 is a DIFFERENT thing -- dynamic_glide_distance()
                # overloads 0 as a sentinel for "no valid trigger point exists in the
                # search range at all" (target already behind s_now, OR even coasting
                # the ENTIRE remaining distance can't shed enough speed), not a literal
                # "zero metres is the safe minimum." Confirmed: at 35-45 km/h (faster
                # than GA's plan assumed here), this returns 0 meaning "not enough road
                # left AT ALL", and capping that up to GA's 227m would hide a real
                # safety warning behind a false sense of security from a plan that never
                # anticipated this speed at this position. So the cap only applies when
                # dyn_distance_m is a genuine positive minimum; the 0 sentinel always
                # passes through uncapped.
                if dyn_distance_m > 0.0 and isinstance(static_distance_m, (int, float)):
                    stop["distance_m"] = max(dyn_distance_m, float(static_distance_m))
                else:
                    stop["distance_m"] = dyn_distance_m
            except Exception:
                pass  # leave the static GA-sourced distance_m in place

    if action.get("s_m") is not None:
        is_stop_act = (action["action"] == "brake")
        if is_stop_act and stop.get("s_m") is not None:
            action["distance_m"] = stop.get("distance_m") or stop["stop_line_distance_m"]
        elif not is_stop_act and turn.get("s_m") is not None:
            action["distance_m"] = turn["distance_m"]

    return {
        "available": True,
        "advisory_mode": _advisory_mode,
        "s_now_m": s_now_m,
        "v_now_kmh": v_now_kmh,
        "next_action": {
            "action": action["action"],
            "distance_m": action["distance_m"],
            "target_speed_kmh": action["target_speed_kmh"],
            "s_m": action["s_m"],
            "latitude": action.get("latitude"),
            "longitude": action.get("longitude"),
        },
        "next_turn": {
            "turn_no": turn["turn_no"],
            "distance_m": turn["distance_m"],
            "target_speed_kmh": turn["target_speed_kmh"],
            "v_safe_kmh": turn.get("v_safe_kmh"),
            "s_m": turn["s_m"],
            "latitude": turn.get("latitude"),
            "longitude": turn.get("longitude"),
        },
        "next_stop": {
            "stop_no": stop.get("stop_no"),
            "distance_m": stop.get("distance_m"),
            "stop_line_distance_m": stop.get("stop_line_distance_m"),
            "target_speed_kmh": stop.get("target_speed_kmh"),
            "s_m": stop.get("s_m"),
            "latitude": stop.get("latitude"),
            "longitude": stop.get("longitude"),
        },
        "current_strategy": {
            "action": strategy["action"],
            "target_speed_kmh": strategy["target_speed_kmh"],
            "s_m": strategy["s_m"],
            "latitude": strategy.get("latitude"),
            "longitude": strategy.get("longitude"),
            "live": strategy_is_live,
        },
        "dp_segment": {
            "v_target_kmh": segment["v_target_kmh"],
            "v_coast_kmh": segment["v_coast_kmh"],
            "s_start_m": segment["s_start_m"],
            "s_end_m": segment["s_end_m"],
        },
        "line_deviation": line_deviation,
    }

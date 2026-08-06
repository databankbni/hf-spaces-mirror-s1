"""Real-time driver advisory: "how far to your next action, and what speed should
you be at" -- built on top of the racing line (track.build_racing_line_profile())
and the SAME physics simulate.py uses, but answering a different question than
compute_speed_ceiling() in simulate.py does.

compute_speed_ceiling() assumes the vehicle can brake (BRAKE_MAX_MS2) anywhere --
that's the right assumption for a safety backstop, but it is NOT the team's actual
driving technique: corners are approached by lifting off and coasting down
naturally (drag + rolling resistance + grade + cornering scrub), never by active
braking. Real braking is reserved for the mandatory stop-and-go points only
(confirmed in telemetry: of 2936 points in the current GA strategy, only 18 are
ever labelled "brake", and all but 4 numerical-noise points are within 30 m of a
stop). So the ceiling a driver-facing "start gliding here" instruction needs to
respect is the GLIDE ceiling -- the highest speed you can be at and still coast
(not brake) down to every upcoming corner's v_safe -- with braking only assumed
available in the final approach to a stop (STOP_GLIDE_LOOKAHEAD_M, same constant
simulate.py already uses for the mirror-image "force glide near a stop" rule).

Precompute-once-cheap-lookup-at-runtime by design: everything in this module runs
offline. The car only ever does an O(1) nearest-row lookup against the saved table
(next_action()), never re-solves anything live -- see the plan discussion for why
this matters for latency.
"""

import math

import numpy as np
import pandas as pd

from . import config
from . import simulate as sim_mod
from . import track as track_mod
from . import vehicle
from . import weather as weather_mod

ADVISORY_CSV = "data/driver_advisory.csv"


def compute_glide_ceiling(full_track: pd.DataFrame, scenario: weather_mod.WeatherScenario,
                          cruise_kmh: float = 60.0,
                          brake_lookahead_m: float = config.STOP_GLIDE_LOOKAHEAD_M) -> np.ndarray:
    """Backward pass, mirroring simulate.compute_speed_ceiling()'s structure, but
    the deceleration available at each step is NOT a constant brake rate -- it's
    the natural coast deceleration (resistance_force_n / mass, clamped at 0 so a
    net-downhill-aided stretch correctly contributes zero cushioning rather than
    an unphysical "coast accelerates you so the ceiling is unlimited"), except
    within brake_lookahead_m of a mandatory stop, where real braking is assumed
    available -- the one place the driving technique actually uses it.

    cruise_kmh default (60.0) is NOT a pacing target like simulate.py's cruise_kmh
    (that's the crude-milestone's flat-speed strategy choice, wrong here) -- it's
    just a generous cap above anything any real strategy asks for (GA/PSO/CMA-ES
    cap at 45 km/h, DP pulses to ~50), so gentle straights don't report the raw
    v_safe's absurd values (racing_line.csv has points over 10,000 km/h on nearly-
    straight stations) while never actually constraining a real strategy speed.
    """
    n = len(full_track)
    v_safe_kmh = full_track["v_safe_kmh"].to_numpy(copy=True)
    stop_event = full_track["stop_event"].to_numpy()
    v_safe_kmh = v_safe_kmh.copy()
    v_safe_kmh[stop_event] = 0.0
    s_m = full_track["s_m"].to_numpy()
    grade_pct = full_track["grade_pct"].to_numpy()
    heading_deg = full_track["heading_deg"].to_numpy()
    r_min_m = full_track["r_min_m"].to_numpy()

    stop_s = s_m[stop_event]
    if len(stop_s) > 0:
        dist_to_stop_m = np.abs(s_m[:, None] - stop_s[None, :]).min(axis=1)
    else:
        dist_to_stop_m = np.full(n, np.inf)

    ceiling_ms = np.empty(n)
    cruise_ms = cruise_kmh / 3.6
    ceiling_ms[-1] = min(cruise_ms, v_safe_kmh[-1] / 3.6)

    for i in range(n - 2, -1, -1):
        ds = s_m[i + 1] - s_m[i]
        v_eval = ceiling_ms[i + 1]  # explicit/backward-Euler: evaluate decel at the known downstream speed
        if dist_to_stop_m[i + 1] <= brake_lookahead_m:
            a_avail = config.BRAKE_MAX_MS2
        else:
            f_res = vehicle.resistance_force_n(v_eval * 3.6, grade_pct[i], scenario, heading_deg[i],
                                                r_min_m=r_min_m[i])
            a_avail = max(f_res, 0.0) / config.MASS_TOTAL_KG  # never negative: downhill-aided stretches
                                                               # give zero coast-down cushioning, not "free" accel
        max_given_next = math.sqrt(max(0.0, v_eval ** 2 + 2 * a_avail * ds))
        ceiling_ms[i] = min(cruise_ms, v_safe_kmh[i] / 3.6, max_given_next)

    return ceiling_ms * 3.6


STRATEGY_TELEMETRY_CSV = "data/simulated_telemetry_mpc.csv"
# The winning strategy run (MPC as of 2026-07-22: 278.5 km/m^3 in result of
# analysis/strategy_comparison.csv, ahead of GA's 272.5 -- see mpc.py) -- its
# per-station motor_state/v_kmh are what current_strategy() and next_turn()'s
# recommended speed answer with, since a driver's real target is "what the
# optimal plan says to do here," not the generic physics coast-down ceiling
# (compute_glide_ceiling's docstring explains why that ceiling alone is a
# poor stand-in: real corner v_safe values dwarf any realistic cruise speed,
# so it never binds on a turn).
#
# For current_strategy() specifically, driver_advisory_bridge.py prefers a
# LIVE call into mpc.MPCController.recommend() (genuinely adaptive to the
# real driver's actual speed/position) over this precomputed table when the
# MPC controller is available -- this table is the fallback for that call,
# and remains the only source for next_turn()'s forward-looking waypoint
# speeds (recommending a future turn doesn't need re-solving the controller).
#
# Re-point this at a different strategy's simulated_telemetry_*.csv if a later
# run overtakes MPC -- it shares the exact same station grid (same s_m values,
# same row count) as this module's own table by construction (both come from
# the same racing-line profile), so no interpolation/tolerance is needed.

_STRATEGY_ACTION_LABELS = {"accel": "gas", "cruise": "glide", "brake": "brake"}


def build_advisory_table(full_track: pd.DataFrame = None, scenario_name: str = "typical_january",
                          save: bool = True, strategy_csv: str = STRATEGY_TELEMETRY_CSV) -> pd.DataFrame:
    """Builds and saves the full-attempt advisory table (racing line, 4 laps) used
    by next_action()/next_turn()/current_strategy(). Re-run whenever the racing
    line, track profile, vehicle config, or the winning strategy changes -- this
    is offline precompute, not something the car ever runs."""
    if full_track is None:
        profile_1lap = track_mod.build_racing_line_profile(save=False)
        turns = track_mod.load_turns()
        profile_1lap = track_mod.assign_turn_zones(profile_1lap, turns)
        full_track = sim_mod.build_full_attempt_track(profile_1lap)
    scenario = weather_mod.SCENARIOS[scenario_name]

    glide_ceiling_kmh = compute_glide_ceiling(full_track, scenario)

    cols = ["s_m", "distance_km", "latitude", "longitude", "v_safe_kmh", "r_min_m", "stop_event"]
    cols += [c for c in ("zone_type", "zone_id") if c in full_track.columns]
    out = full_track[cols].copy()
    out["glide_ceiling_kmh"] = glide_ceiling_kmh

    strategy = pd.read_csv(strategy_csv)[["s_m", "motor_state", "v_kmh"]].rename(
        columns={"motor_state": "strategy_state", "v_kmh": "strategy_v_kmh"})
    out = pd.merge_asof(out.sort_values("s_m"), strategy.sort_values("s_m"),
                         on="s_m", direction="nearest")

    if "zone_type" in out.columns:
        # First row of each turn zone only (not every row inside it) -- this is
        # what next_turn() scans for. Scanning "any row tagged turn" instead
        # would mean a car currently INSIDE a turn's zone keeps matching that
        # SAME turn (distance_m pinned near 0) for as long as it's in there,
        # never advancing to the next one until fully clear of the zone --
        # exactly the "stuck recommending turn 1 the whole way through it"
        # bug this column exists to avoid. Once s_now_m is past a turn's
        # entry station, next_turn() should already be answering with
        # whatever turn comes after it, even while still inside turn 1's zone.
        is_turn = (out["zone_type"] == "turn").to_numpy()
        zone_id_arr = out["zone_id"].to_numpy()
        entry = np.zeros(len(out), dtype=bool)
        entry[0] = is_turn[0]
        entry[1:] = is_turn[1:] & (~is_turn[:-1] | (zone_id_arr[1:] != zone_id_arr[:-1]))
        out["turn_entry"] = entry

    if save:
        out.to_csv(ADVISORY_CSV, index=False)
    return out


def next_action(advisory: pd.DataFrame, s_now_m: float, v_now_kmh: float) -> dict:
    """Given the driver's actual live position and speed, find the next point
    where the glide ceiling drops below the current speed -- that's "you need to
    have started lifting off (or braking, if it's a stop) by here." Returns
    {"distance_m", "target_speed_kmh", "action", "s_m"} or a "no upcoming
    constraint within this table" marker if none is found ahead (shouldn't happen
    over a full lap, but the table is finite).
    """
    s = advisory["s_m"].to_numpy()
    ceiling = advisory["glide_ceiling_kmh"].to_numpy()
    stop_event = advisory["stop_event"].to_numpy()

    idx0 = int(np.searchsorted(s, s_now_m, side="left"))
    ahead = ceiling[idx0:] < v_now_kmh - 1e-6
    if not ahead.any():
        return {"distance_m": None, "target_speed_kmh": None, "action": "ok", "s_m": None}

    action_idx = idx0 + int(np.argmax(ahead))
    # A target of exactly 0 always means "come to a stop by here" even if this
    # particular row isn't itself the one flagged stop_event=True -- the ceiling
    # can reach 0 a point or two before the flagged row at a lap-seam duplicate-
    # distance value, and a 0 km/h target is never a "glide" instruction.
    is_stop = bool(stop_event[action_idx]) or ceiling[action_idx] <= 0.0
    result = {
        "distance_m": float(s[action_idx] - s_now_m),
        "target_speed_kmh": float(ceiling[action_idx]),
        "action": "brake" if is_stop else "glide",
        "s_m": float(s[action_idx]),
    }
    if "latitude" in advisory.columns:
        result["latitude"] = float(advisory["latitude"].to_numpy()[action_idx])
        result["longitude"] = float(advisory["longitude"].to_numpy()[action_idx])
    return result


def next_turn(advisory: pd.DataFrame, s_now_m: float) -> dict:
    """Nearest upcoming turn ENTRY, independent of current speed -- unlike
    next_action()'s glide-ceiling trigger (which in practice only ever fires
    near the two mandatory stops: real corner v_safe values so dwarf any
    achievable cruise speed that the ceiling never binds on a turn, see
    compute_glide_ceiling's docstring), this always answers "where's the next
    corner" from the actual turn-zone geometry in turns.csv, with the
    recommended speed (what to be at BY the entry point) taken from the
    winning strategy's own plan rather than the raw physics limit.

    Scans turn_entry rows only (the first station of each turn zone), not
    every row tagged zone_type=="turn" -- a car currently INSIDE a turn's
    zone would otherwise keep matching that SAME turn (distance_m pinned
    near 0) for as long as it's in there, never advancing to the next turn
    until fully clear of the current one. Using entry rows means the answer
    switches to the following turn as soon as s_now_m passes the current
    turn's entry station, even while still physically inside its zone.

    Returns a None-turn marker if the table predates the turn_entry column,
    or if no turn entry lies ahead within this table."""
    if "turn_entry" not in advisory.columns:
        return {"turn_no": None, "distance_m": None, "target_speed_kmh": None, "s_m": None}

    s = advisory["s_m"].to_numpy()
    is_entry = advisory["turn_entry"].to_numpy()
    zone_id = advisory["zone_id"].to_numpy()
    strategy_v = advisory["strategy_v_kmh"].to_numpy()

    idx0 = int(np.searchsorted(s, s_now_m, side="left"))
    ahead_entry = is_entry[idx0:]
    if not ahead_entry.any():
        if is_entry.any():
            turn_idx = int(np.argmax(is_entry))
        else:
            return {"turn_no": None, "distance_m": None, "target_speed_kmh": None, "s_m": None}
    else:
        turn_idx = idx0 + int(np.argmax(ahead_entry))

    lap_len = float(s[-1]) if len(s) > 0 else 3630.0
    turn_s = float(s[turn_idx])
    dist_m = float((turn_s - s_now_m) % lap_len) if turn_s < s_now_m else float(turn_s - s_now_m)
    v_safe = float(advisory["v_safe_kmh"].to_numpy()[turn_idx]) if "v_safe_kmh" in advisory.columns else float(strategy_v[turn_idx])

    result = {
        "turn_no": int(zone_id[turn_idx]),
        "distance_m": dist_m,
        "target_speed_kmh": float(strategy_v[turn_idx]),
        "v_safe_kmh": v_safe,
        "s_m": turn_s,
    }
    if "latitude" in advisory.columns:
        result["latitude"] = float(advisory["latitude"].to_numpy()[turn_idx])
        result["longitude"] = float(advisory["longitude"].to_numpy()[turn_idx])
    return result


def next_stop(advisory: pd.DataFrame, s_now_m: float) -> dict:
    """Nearest upcoming mandatory STOP event: locates the optimum station BEFORE
    the stop line where the driver should cut throttle and start gliding down to
    the stop line.

    Returns distance to GLIDE START point (if ahead of car), target entry speed to carry into that point,
    and total distance to the stop line. If the car is ALREADY past the glide start point, distance_m is 0 (GLIDE NOW!).
    """
    if "stop_event" not in advisory.columns:
        return {"stop_no": None, "distance_m": None, "stop_line_distance_m": None, "target_speed_kmh": None, "s_m": None}

    s = advisory["s_m"].to_numpy()
    is_stop = advisory["stop_event"].to_numpy()
    strategy_v = advisory["strategy_v_kmh"].to_numpy()
    strategy_st = advisory["strategy_state"].to_numpy() if "strategy_state" in advisory.columns else None

    # Search for the IMMEDIATE next stop station ahead of current position
    idx0 = int(np.searchsorted(s, s_now_m, side="left"))
    ahead_stop = is_stop[idx0:]
    if not ahead_stop.any():
        return {"stop_no": None, "distance_m": None, "stop_line_distance_m": None, "target_speed_kmh": None, "s_m": None}

    stop_idx = idx0 + int(np.argmax(ahead_stop))
    stop_line_dist = float(s[stop_idx] - s_now_m)

    # Trace backward from the stop line to find where the deceleration/glide transition begins
    # i.e., find the cruise station before velocity drops down to 0 at the stop
    glide_start_idx = max(0, stop_idx - 1)
    for i in range(stop_idx, max(0, stop_idx - 300), -1):
        v = strategy_v[i]
        st = str(strategy_st[i]) if strategy_st is not None else ""
        if st in ("accel", "gas") or (i > 0 and v > strategy_v[i - 1] + 0.1):
            glide_start_idx = i
            break

    entry_v = float(strategy_v[glide_start_idx])
    if entry_v <= 1.0 and glide_start_idx > 0:
        # Fall back to max speed in the approach window if local station is 0
        entry_v = float(np.max(strategy_v[max(0, glide_start_idx - 50):glide_start_idx + 1]))

    # Check if the car is currently BEFORE or AFTER the glide-start point
    if s_now_m < s[glide_start_idx]:
        # Car hasn't reached the glide start point yet -> target the glide start station
        target_idx = glide_start_idx
        glide_dist = float(s[glide_start_idx] - s_now_m)
    else:
        # Car is ALREADY in the glide/deceleration zone for this stop line
        target_idx = stop_idx
        glide_dist = 0.0  # Must be gliding/braking NOW

    result = {
        "stop_no": 1 if (stop_idx % 2 == 0) else 2,
        "stop_line_distance_m": stop_line_dist,
        "distance_m": glide_dist,
        "target_speed_kmh": entry_v,
        "s_m": float(s[target_idx]),
    }
    if "latitude" in advisory.columns:
        result["latitude"] = float(advisory["latitude"].to_numpy()[target_idx])
        result["longitude"] = float(advisory["longitude"].to_numpy()[target_idx])
    return result


def current_strategy(advisory: pd.DataFrame, s_now_m: float) -> dict:
    """What the winning strategy says the driver should be doing RIGHT NOW at
    s_now_m -- gas/glide/brake -- distinct from next_action()'s "what's the
    next upcoming event ahead" framing. Sourced from simulate.py's per-station
    motor_state label (accel/cruise/brake) for the winning strategy run,
    joined onto this table in build_advisory_table(); "cruise" is relabelled
    "glide" here since that's what it actually means for this car (lift off
    and coast down, never hold constant speed under power -- see this
    module's docstring on the burn-and-coast driving technique)."""
    s = advisory["s_m"].to_numpy()
    idx = min(int(np.searchsorted(s, s_now_m, side="left")), len(s) - 1)
    state = str(advisory["strategy_state"].to_numpy()[idx])
    result = {
        "action": _STRATEGY_ACTION_LABELS.get(state, state),
        "target_speed_kmh": float(advisory["strategy_v_kmh"].to_numpy()[idx]),
        "s_m": float(s[idx]),
    }
    if "latitude" in advisory.columns:
        result["latitude"] = float(advisory["latitude"].to_numpy()[idx])
        result["longitude"] = float(advisory["longitude"].to_numpy()[idx])
    return result


if __name__ == "__main__":
    table = build_advisory_table()
    print(f"Built {ADVISORY_CSV}: {len(table)} points")
    print(f"glide_ceiling_kmh min: {table['glide_ceiling_kmh'].min():.1f}, "
          f"max finite: {table.loc[np.isfinite(table['glide_ceiling_kmh']), 'glide_ceiling_kmh'].max():.1f}")
    if "zone_type" in table.columns:
        print(f"turn zones: {(table['zone_type'] == 'turn').sum()} rows across "
              f"{table.loc[table['zone_type'] == 'turn', 'zone_id'].nunique()} distinct turns/lap x4 laps")

    for s_now, v_now in [(500.0, 30.0), (2500.0, 40.0), (100.0, 25.0)]:
        act = next_action(table, s_now, v_now)
        turn = next_turn(table, s_now)
        strat = current_strategy(table, s_now)
        print(f"at s={s_now:.0f}m v={v_now:.0f}km/h -> next_action={act} next_turn={turn} current_strategy={strat}")

"""
Fuzzy-logic driving-strategy controller for the SEM hydrogen digital twin.

Where the MPC controller (mpc.py) plans by explicit receding-horizon rollout, this
module encodes the *same* eco-driving intuition as a small Mamdani fuzzy inference
system -- no per-step optimisation, just human-readable rules over the terrain ahead:

    "IF the road ahead climbs THEN hold a SLOWER target (don't burn H2 fighting gravity)"
    "IF it's flat            THEN cruise at the ECO target"
    "IF it descends          THEN cut the motor early and GLIDE (gravity is free speed)"
    "IF a corner/stop is near THEN the safety ceiling already caps us -- glide in"

The fuzzy system outputs, for every track point, a gas target speed `v_target_kmh`
(motor cuts out above it) and a glide-resume floor `v_coast_kmh` (motor kicks back in
below it). Those two arrays are exactly the pulse-and-glide interface simulate() already
consumes, so the validated two-motor physics, stop-glide safety floor, motor selection
and Art. 54e H2 accounting are all reused unchanged -- this file only decides the
*setpoints*, never re-implements physics (project convention: one method per file).

    from digital_twin import fuzzy_strategy as fz
    tel, score = fz.optimize_strategy()          # tuned run, saves telemetry CSV

No third-party fuzzy dependency: the triangular membership + centroid defuzzification
is ~20 lines of numpy, kept transparent so the rulebook is auditable.
"""

import numpy as np
import pandas as pd

from . import config
from . import powertrain
from . import simulate as sim_mod
from . import telemetry as telemetry_mod
from . import track as track_mod
from . import weather as weather_mod

SEGMENT_TARGETS_CSV = "data/fuzzy_segment_targets.csv"
TELEMETRY_CSV = "data/simulated_telemetry_fuzzy.csv"


# --- Membership functions -----------------------------------------------------
def _tri(x, a, b, c):
    """Triangular membership: 0 at a and c, 1 at the peak b. Vectorised over x."""
    x = np.asarray(x, dtype=float)
    left = (x - a) / (b - a) if b > a else np.where(x <= b, 1.0, 0.0)
    right = (c - x) / (c - b) if c > b else np.where(x >= b, 1.0, 0.0)
    return np.clip(np.minimum(left, right), 0.0, 1.0)


class FuzzyStrategy:
    """
    Mamdani fuzzy controller mapping (grade-ahead, corner-tightness) -> (gas target,
    glide floor) per track point. All numbers are tunable design knobs (PLACEHOLDER --
    no measured optimum yet); tune_grid()/optimize_strategy() search them for the best
    feasible Art. 54e score.

    Antecedent -- grade averaged over `lookahead_m` metres ahead, fuzzified into
    DOWN / FLAT / UP. Consequent -- a target cruise speed (km/h), one crisp value per
    fuzzy set, blended by centroid defuzzification. The glide band width is itself
    terrain-dependent (wider glides on descents, tighter on climbs).
    """

    def __init__(self,
                 v_slow_kmh: float = 24.0,   # UP-hill target: accept a slower climb
                 v_med_kmh: float = 29.0,    # FLAT eco-cruise target
                 v_fast_kmh: float = 30.0,   # DOWN-hill target (glide carries speed past it)
                 grade_scale_pct: float = 3.0,   # grade at which DOWN/UP memberships peak
                 band_flat_kmh: float = 6.0,     # pulse-and-glide band width on the flat
                 band_down_kmh: float = 10.0,    # wider glide band on descents (ride gravity)
                 band_up_kmh: float = 4.0,       # tighter band on climbs (steadier power)
                 lookahead_m: float = 30.0):
        self.v_slow, self.v_med, self.v_fast = v_slow_kmh, v_med_kmh, v_fast_kmh
        self.g = grade_scale_pct
        self.band_flat, self.band_down, self.band_up = band_flat_kmh, band_down_kmh, band_up_kmh
        self.lookahead_m = lookahead_m

    def _memberships(self, grade_ahead):
        """DOWN / FLAT / UP membership degrees for the grade-ahead signal."""
        g = self.g
        mu_down = _tri(grade_ahead, -3 * g, -g, 0.0)
        mu_flat = _tri(grade_ahead, -g, 0.0, g)
        mu_up = _tri(grade_ahead, 0.0, g, 3 * g)
        return mu_down, mu_flat, mu_up

    def compute_setpoints(self, full_track: pd.DataFrame):
        """Return (v_target_kmh, v_coast_kmh) arrays for the whole attempt."""
        s_m = full_track["s_m"].to_numpy()
        grade = full_track["grade_pct"].to_numpy()

        # grade averaged over the look-ahead window (what the driver "sees" coming)
        grade_ahead = np.empty_like(grade)
        for i in range(len(s_m)):
            j = np.searchsorted(s_m, s_m[i] + self.lookahead_m)
            grade_ahead[i] = grade[i:max(i + 1, j)].mean()

        mu_down, mu_flat, mu_up = self._memberships(grade_ahead)
        wsum = mu_down + mu_flat + mu_up
        wsum = np.where(wsum <= 1e-9, 1.0, wsum)

        # centroid defuzzification of the target speed
        v_target = (mu_down * self.v_fast + mu_flat * self.v_med + mu_up * self.v_slow) / wsum
        # terrain-dependent glide band -> coast floor
        band = (mu_down * self.band_down + mu_flat * self.band_flat + mu_up * self.band_up) / wsum
        v_coast = v_target - band
        return v_target, np.clip(v_coast, 5.0, v_target - 1.0)


def run(full_track, scenario, accel_motor, cruise_motor, fc,
        strat: FuzzyStrategy = None, motor_select_mode: str = "efficiency",
        cruise_converter=None) -> pd.DataFrame:
    """Compute fuzzy setpoints, then run them through the validated two-motor simulate()."""
    strat = strat or FuzzyStrategy()
    v_target, v_coast = strat.compute_setpoints(full_track)
    return sim_mod.simulate(full_track, scenario, accel_motor=accel_motor,
                            cruise_motor=cruise_motor, fc=fc,
                            v_target_kmh=v_target, v_coast_kmh=v_coast,
                            motor_select_mode=motor_select_mode,
                            cruise_converter=cruise_converter,
                            # Trial 2: Fuzzy minimises braking away from stops by gliding into corners.
                            brake_avoid_lookahead_m=config.BRAKE_AVOID_LOOKAHEAD_M)


def score_telemetry(tel: pd.DataFrame) -> dict:
    """Art. 54e net score + audit for a fuzzy-strategy telemetry frame (mirrors mpc.score_telemetry)."""
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


def tune_grid(full_track, scenario, accel_motor, cruise_motor, fc,
              v_med_grid=(27, 28, 29, 30), band_grid=(5, 6, 8), verbose=True,
              cruise_converter=None):
    """
    Coarse coordinate search over the two knobs that most move the H2/time trade-off:
    the flat-cruise eco target and the base glide-band width. Returns
    (best_strategy, best_result, all_rows). "Best" = highest Art. 54e score among the
    FEASIBLE runs (<= 35 min, zero rule violations) -- an infeasible run is never chosen
    however low its H2, so the winner is the most-efficient strategy that still legally
    completes the attempt.
    """
    rows, best = [], None
    for v_med in v_med_grid:
        for band in band_grid:
            strat = FuzzyStrategy(v_med_kmh=float(v_med), v_slow_kmh=float(v_med) - 5.0,
                                  v_fast_kmh=float(v_med) + 1.0, band_flat_kmh=float(band),
                                  band_down_kmh=float(band) + 4.0, band_up_kmh=max(3.0, float(band) - 2.0))
            tel = run(full_track, scenario, accel_motor, cruise_motor, fc, strat,
                      cruise_converter=cruise_converter)
            r = score_telemetry(tel)
            r.update({"v_med": v_med, "band": band})
            rows.append(r)
            feasible = r["time_ok"] and r["rule_violations"] == 0
            if verbose:
                flag = "OK " if feasible else "XX "
                print(f"  {flag} v_med={v_med} band={band}: score={r['score_km_per_m3']:.1f} "
                      f"time={r['time_min']:.2f}min H2={r['h2_l']:.2f}L viol={r['rule_violations']}")
            if feasible and (best is None or r["score_km_per_m3"] > best[1]["score_km_per_m3"]):
                best = (strat, r)
    return best[0], best[1], pd.DataFrame(rows)


def optimize_strategy(scenario_name="typical_january",
                      accel_motor_name=config.ACCEL_MOTOR_NAME,
                      cruise_motor_name=config.CRUISE_MOTOR_NAME,
                      fc_name=config.DEFAULT_FC_NAME, laps=config.TOTAL_LAPS,
                      use_racing_line=True, save=True, verbose=True):
    """End-to-end: build the attempt, tune the fuzzy knobs, return (telemetry, result)
    for the best feasible strategy. Two-motor + new SZFC-1000 fuel cell on the RACING-LINE
    profile by default, to match optimize_ga/optimize_cma (set use_racing_line=False for
    the raw centerline backbone)."""
    if use_racing_line:
        profile_1lap = track_mod.build_racing_line_profile(save=False)
    else:
        profile_1lap = track_mod.build_track_profile(save=False)
    full_track = sim_mod.build_full_attempt_track(profile_1lap, laps=laps)
    scenario = weather_mod.SCENARIOS[scenario_name]
    motors = powertrain.load_motors()
    accel_motor, cruise_motor = motors[accel_motor_name], motors[cruise_motor_name]
    fc = powertrain.load_fuel_cells()[fc_name]
    cruise_converter = powertrain.load_converters()[config.CRUISE_CONVERTER_NAME]
    strat, result, _ = tune_grid(full_track, scenario, accel_motor, cruise_motor, fc, verbose=verbose,
                                 cruise_converter=cruise_converter)
    tel = run(full_track, scenario, accel_motor, cruise_motor, fc, strat,
              cruise_converter=cruise_converter)
    if save:
        tel.to_csv(TELEMETRY_CSV, index=False)
    return tel, result


if __name__ == "__main__":
    print("Tuning fuzzy driving strategy (two-motor, SZFC-1000)...")
    tel, result = optimize_strategy()
    print("Best feasible fuzzy strategy:")
    for k, v in result.items():
        print(f"  {k:18} = {v}")

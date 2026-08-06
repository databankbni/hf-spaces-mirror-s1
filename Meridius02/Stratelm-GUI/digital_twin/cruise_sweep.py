"""
Constant-cruise-speed duration sweep, requested by the Electrical sub-team for
component duty-cycle/thermal sizing.

Important distinction from the GA gas/glide optimum: this sweep forces a
single HELD speed the whole attempt (the crude constant-speed-with-turn/stop-
slowdown controller in simulate.py, cruise_kmh fixed, v_target_kmh/v_coast_kmh
left None). The GA optimum has no such single held speed -- it pulses between
a per-segment v_target (peak, "gas") and v_coast (floor, "glide"), so its
reported ~29.7 km/h is a DISTANCE-WEIGHTED AVERAGE of an oscillating trace,
not a sustained value. Both numbers are legitimate, they just answer
different questions -- see optimize_ga.py's telemetry for the actual pulse
pattern (segment_speed_profile() below summarizes it).
"""

import numpy as np
import pandas as pd

from . import config
from . import powertrain
from . import simulate as sim_mod
from . import telemetry as telemetry_mod
from . import track as track_mod
from . import weather as weather_mod


def cruise_duration_sweep(cruise_speeds_kmh, scenario_name: str = "typical_january",
                           motor_name: str = config.DEFAULT_MOTOR_NAME,
                           fc_name: str = config.DEFAULT_FC_NAME) -> pd.DataFrame:
    profile_1lap = track_mod.build_track_profile(save=False)
    full_track = sim_mod.build_full_attempt_track(profile_1lap)
    scenario = weather_mod.SCENARIOS[scenario_name]
    motor = powertrain.load_motors()[motor_name]
    fc = powertrain.load_fuel_cells()[fc_name]

    rows = []
    for v_cruise in cruise_speeds_kmh:
        tel = sim_mod.simulate(full_track, scenario, cruise_kmh=v_cruise, motor=motor, fc=fc)
        total_time_s = tel["t_s"].iloc[-1]
        total_h2_m3 = tel["h2_cumulative_m3"].iloc[-1]
        accessory_j = tel["accessory_energy_cumulative_j"].iloc[-1]
        score = telemetry_mod.h2_score_km_per_m3(
            tel["s_m"].iloc[-1] / 1000.0, total_h2_m3, accessory_energy_j=accessory_j)
        rows.append({
            "cruise_kmh_target": v_cruise,
            "actual_avg_kmh": (tel["s_m"].iloc[-1] / 1000.0) / (total_time_s / 3600.0),
            "duration_min": total_time_s / 60.0,
            "within_35min_limit": total_time_s <= config.MAX_ATTEMPT_TIME_MIN * 60.0,
            "motor_clipped_points": int(tel["motor_clipped"].sum()),
            "h2_liters": total_h2_m3 * 1000.0,
            "art54e_score_km_per_m3": score,
        })
    return pd.DataFrame(rows)


def ga_pulse_summary(ga_telemetry_csv: str = "data/simulated_telemetry_ga.csv") -> dict:
    """Characterize the GA optimum's ACTUAL speed trace -- it's a pulse pattern, not a
    held cruise speed, so this reports what electrical actually needs: peak/floor
    speeds and time spent in each motor_state."""
    tel = pd.read_csv(ga_telemetry_csv)
    dt = tel["t_s"].diff().fillna(0.0)
    time_by_state_s = tel.groupby("motor_state")["t_s"].apply(
        lambda idx: dt.loc[idx.index].sum())
    total_time_s = tel["t_s"].iloc[-1]
    return {
        "distance_weighted_avg_kmh": (tel["s_m"].iloc[-1] / 1000.0) / (total_time_s / 3600.0),
        "peak_kmh": tel["v_kmh"].max(),
        "min_moving_kmh": tel.loc[tel["v_kmh"] > 0.5, "v_kmh"].min(),
        "total_duration_min": total_time_s / 60.0,
        "time_by_motor_state_min": (time_by_state_s / 60.0).to_dict(),
    }


if __name__ == "__main__":
    sweep = cruise_duration_sweep(list(range(30, 41)))
    pd.set_option("display.width", 140)
    print(sweep.to_string(index=False))
    sweep.to_csv("data/cruise_speed_sweep.csv", index=False)
    print("\nSaved data/cruise_speed_sweep.csv")

    print("\n--- GA gas/glide optimum: actual pulse pattern (not a held cruise speed) ---")
    summary = ga_pulse_summary()
    for k, v in summary.items():
        print(f"{k}: {v}")

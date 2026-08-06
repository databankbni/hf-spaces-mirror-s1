"""
Two-motor (Urban Concept) driving-STRATEGY comparison. STRATEGY/analysis only --
this evaluates how the acceleration-motor + cruise-motor split affects the Art. 54e
H2 efficiency score; it is not the physical car's controller.

Runs, on the same track/weather:
  - single-motor baseline (the default cruise-efficient motor alone)
  - Design A "rule" (hardware-realistic: accel motor on relaunch-from-stop / climb,
    cruise motor otherwise incl. downhill) at a 10 s vs 15 s acceleration window
  - Design B "efficiency" ceiling (free per-step switch -- NOT achievable with the
    real clutch/transmission, shown only as an upper bound)

Also writes data/track_for_motor.csv: per track position on lap 1, which motor is
engaged and why -- so the accel/cruise zones are easy to eyeball against the track.
"""

import numpy as np

from . import config
from . import powertrain
from . import simulate as sim
from . import telemetry as telem
from . import track as track_mod
from . import weather as weather_mod

TRACK_FOR_MOTOR_CSV = "data/track_for_motor.csv"
CRUISE_MS = config.V_TARGET_AVG_KMH_CRUISE / 3.6


def _summary(tel) -> dict:
    dist_km = tel["s_m"].iloc[-1] / 1000.0
    time_s = tel["t_s"].iloc[-1]
    h2_m3 = tel["h2_cumulative_m3"].iloc[-1]
    acc_j = tel["accessory_energy_cumulative_j"].iloc[-1]
    score = telem.h2_score_km_per_m3(dist_km, h2_m3, accessory_energy_j=acc_j)
    return {
        "score_km_per_m3": score,
        "time_min": time_s / 60.0,
        "avg_kmh": dist_km / (time_s / 3600.0),
        "h2_L": h2_m3 * 1000.0,
        "clipped_pts": int(tel["motor_clipped"].sum()),
    }


def run():
    profile_1lap = track_mod.build_track_profile(save=False)
    full_track = sim.build_full_attempt_track(profile_1lap)
    scenario = weather_mod.SCENARIOS["typical_january"]
    motors = powertrain.load_motors()
    fc = powertrain.load_fuel_cells()[config.DEFAULT_FC_NAME]
    accel = motors[config.ACCEL_MOTOR_NAME]
    cruise = motors[config.CRUISE_MOTOR_NAME]

    def cap_for(seconds):  # acceleration rate that reaches 30 km/h in `seconds`
        return CRUISE_MS / seconds

    runs = {
        "baseline (cruise motor only)":
            dict(motor=cruise),
        "A rule, 10s accel":
            dict(accel_motor=accel, cruise_motor=cruise, motor_select_mode="rule",
                 accel_window_s=10.0, accel_cap_ms2=cap_for(10.0)),
        "A rule, 15s accel":
            dict(accel_motor=accel, cruise_motor=cruise, motor_select_mode="rule",
                 accel_window_s=15.0, accel_cap_ms2=cap_for(15.0)),
        "B efficiency ceiling":
            dict(accel_motor=accel, cruise_motor=cruise, motor_select_mode="efficiency",
                 accel_window_s=15.0, accel_cap_ms2=cap_for(15.0)),
    }

    results = {}
    for name, kw in runs.items():
        tel = sim.simulate(full_track, scenario, fc=fc, **kw)
        results[name] = (tel, _summary(tel), telem.motor_usage_breakdown(tel))

    # ---- report ----
    print(f"Track: {full_track['s_m'].iloc[-1]/1000:.2f} km over {config.TOTAL_LAPS} laps | "
          f"FC: {config.DEFAULT_FC_NAME}")
    print(f"Motors: accel={config.ACCEL_MOTOR_NAME} ({accel.max_mech_power_w():.0f}W)  "
          f"cruise={config.CRUISE_MOTOR_NAME} ({cruise.max_mech_power_w():.0f}W)\n")
    hdr = f"{'strategy':<30}{'H2 score':>11}{'time':>9}{'avg':>8}{'H2':>9}{'clip':>6}{'switch':>8}"
    print(hdr); print("-" * len(hdr))
    base_score = results["baseline (cruise motor only)"][1]["score_km_per_m3"]
    for name, (tel, s, bd) in results.items():
        delta = (s["score_km_per_m3"] / base_score - 1) * 100 if np.isfinite(base_score) else 0
        print(f"{name:<30}{s['score_km_per_m3']:>9.1f}  {s['time_min']:>6.2f}m {s['avg_kmh']:>6.1f} "
              f"{s['h2_L']:>7.2f}L {s['clipped_pts']:>5} {bd.get('handoffs',0):>7}"
              f"   ({delta:+.1f}% vs base)")

    # per-motor split for the recommended 15 s rule run
    print("\nPer-motor split -- A rule, 15s accel:")
    tel15, _, bd15 = results["A rule, 15s accel"]
    for m, d in bd15["per_motor"].items():
        print(f"  {m:<20} energy {d['energy_wh']:>7.1f} Wh | H2 {d['h2_m3']*1000:>6.2f} L | "
              f"engaged {d['engaged_time_s']/60:>5.2f} min | {d['engaged_dist_m']/1000:>5.2f} km")
    loss = telem.estimated_handoff_loss_wh(tel15)
    print(f"  estimated clutch/rpm-sync handoff loss (0.5s coast x {bd15['handoffs']} switches): "
          f"{loss:.2f} Wh  -- not added to score (instantaneous-switch model)")

    # ---- track_for_motor.csv: lap 1, which motor & why ----
    lap1 = tel15[tel15["lap"] == 1].copy()
    active = lap1["active_motor"].to_numpy()
    grade = lap1["grade_pct"].to_numpy()
    phase = np.where(active == config.ACCEL_MOTOR_NAME,
                     np.where(grade > config.INCLINE_GRADE_THRESHOLD_PCT, "accel:climb", "accel:launch"),
                     "cruise")
    out = lap1[["distance_km", "grade_pct", "zone_type", "stop_event", "v_kmh", "active_motor"]].copy()
    out["motor_phase"] = phase
    out.to_csv(TRACK_FOR_MOTOR_CSV, index=False)
    n_accel = int(np.sum(active == config.ACCEL_MOTOR_NAME))
    print(f"\nWrote {TRACK_FOR_MOTOR_CSV}: {len(out)} points/lap, "
          f"accel motor on {n_accel} ({100*n_accel/len(out):.0f}%), cruise on the rest.")


if __name__ == "__main__":
    run()

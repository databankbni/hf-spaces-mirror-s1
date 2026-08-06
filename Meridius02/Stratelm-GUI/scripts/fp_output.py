"""
FP minimal outputs: turn a telemetry run into the four deliverables the FP report
needs -- two track heatmaps, a final efficiency report, and per-segment energy.

    python3 scripts/fp_output.py                       # auto-picks best telemetry in data/
    python3 scripts/fp_output.py --telemetry data/simulated_telemetry_ga.csv
    python3 scripts/fp_output.py --segments 15

Auto-pick order (best strategy first): MPC -> GA -> PSO -> CMA -> crude. Works with any
telemetry frame that has the standard simulate()/mpc columns (latitude, longitude,
distance_km, v_kmh, motor_state, stop_event, h2_cumulative_m3, p_wheel_w, t_s).

Outputs (data/):
    fp_speed_heatmap.png        v_kmh painted on the track map
    fp_gasglide_heatmap.png     gas / glide / stop painted on the track map
    fp_efficiency_report.json   distance, time, H2, Art. 54e km/m^3 score
    fp_energy_per_segment.csv   H2 + wheel/electrical energy aggregated per segment
"""

import argparse
import json
import os
import sys

# allow `python3 scripts/fp_output.py` from the repo root to import the package
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import numpy as np
import pandas as pd

import matplotlib
matplotlib.use("Agg")   # headless: write PNGs, never open a window
import matplotlib.pyplot as plt

from digital_twin import config
from digital_twin import telemetry as telemetry_mod

CANDIDATES = [
    "data/simulated_telemetry_mpc.csv",
    "data/simulated_telemetry_ga.csv",
    "data/simulated_telemetry_pso.csv",
    "data/simulated_telemetry_cma.csv",
    "data/simulated_telemetry_crude.csv",
]


def autodetect_telemetry():
    for p in CANDIDATES:
        if os.path.exists(p):
            return p
    raise SystemExit("No telemetry CSV found in data/. Run a simulate/optimize/mpc first.")


def speed_heatmap(tel, out_path):
    fig, ax = plt.subplots(figsize=(9, 7))
    sc = ax.scatter(tel["longitude"], tel["latitude"], c=tel["v_kmh"],
                    cmap="viridis", s=6, linewidths=0)
    cb = fig.colorbar(sc, ax=ax)
    cb.set_label("Speed (km/h)")
    ax.set_title("Speed heatmap over track (blue = slow, yellow = fast)")
    ax.set_xlabel("Longitude"); ax.set_ylabel("Latitude")
    ax.set_aspect("equal", adjustable="datalim")
    fig.tight_layout(); fig.savefig(out_path, dpi=130); plt.close(fig)
    return out_path


def classify_gasglide(tel):
    """gas = powering/accelerating, glide = coasting/braking, stop = compulsory stop."""
    state = np.where(tel["stop_event"].to_numpy() & (tel["v_kmh"].to_numpy() < 1.0), "stop",
                     np.where(tel["motor_state"].to_numpy() == "accel", "gas", "glide"))
    return state


def gasglide_heatmap(tel, out_path):
    state = classify_gasglide(tel)
    colors = {"gas": "#2ca02c", "glide": "#1f77b4", "stop": "#d62728"}
    fig, ax = plt.subplots(figsize=(9, 7))
    for label in ["glide", "gas", "stop"]:
        m = state == label
        ax.scatter(tel["longitude"][m], tel["latitude"][m], c=colors[label],
                   s=8, linewidths=0, label=f"{label} ({int(m.sum())})")
    ax.set_title("Gas / Glide / Stop over track")
    ax.set_xlabel("Longitude"); ax.set_ylabel("Latitude")
    ax.set_aspect("equal", adjustable="datalim")
    ax.legend(loc="best", framealpha=0.9)
    fig.tight_layout(); fig.savefig(out_path, dpi=130); plt.close(fig)
    return out_path


def efficiency_report(tel, out_path, source):
    total_dist_km = tel["s_m"].iloc[-1] / 1000.0
    total_time_s = tel["t_s"].iloc[-1]
    total_h2_m3 = tel["h2_cumulative_m3"].iloc[-1]
    accessory_j = tel["accessory_energy_cumulative_j"].iloc[-1]
    accessory_equiv_m3 = telemetry_mod.accessory_h2_equivalent_m3(accessory_j)
    score = telemetry_mod.h2_score_km_per_m3(total_dist_km, total_h2_m3, accessory_energy_j=accessory_j)
    _trapz = getattr(np, "trapezoid", None) or np.trapz   # numpy 2.0 renamed trapz
    wheel_energy_wh = float(_trapz(tel["p_wheel_w"], tel["t_s"]) / 3600.0)
    report = {
        "source_telemetry": source,
        "distance_km": round(total_dist_km, 3),
        "time_min": round(total_time_s / 60.0, 2),
        "time_limit_min": config.MAX_ATTEMPT_TIME_MIN,
        "time_ok": bool(total_time_s <= config.MAX_ATTEMPT_TIME_MIN * 60.0),
        "avg_speed_kmh": round(total_dist_km / (total_time_s / 3600.0), 2) if total_time_s else 0.0,
        "h2_flowmeter_l": round(total_h2_m3 * 1000.0, 4),
        "accessory_h2_equiv_l": round(accessory_equiv_m3 * 1000.0, 4),
        "net_h2_l": round((total_h2_m3 + accessory_equiv_m3) * 1000.0, 4),
        "wheel_energy_wh": round(wheel_energy_wh, 1),
        "art54e_score_km_per_m3": round(score, 1),
        "stops": int(tel["stop_event"].sum()),
        "rule_violations": int(tel["rule_violation"].sum()) if "rule_violation" in tel else None,
    }
    with open(out_path, "w") as f:
        json.dump(report, f, indent=2)
    return report


def energy_per_segment(tel, out_path, n_segments):
    """Aggregate H2 + energy into n_segments per lap (segment index shared across laps).
    Mirrors the GA gene layout so an operator can line these up with ga_segment_targets."""
    lap_len_km = config.LAP_DISTANCE_KM
    dist_km = tel["distance_km"].to_numpy()
    seg_width = lap_len_km / n_segments
    seg_idx = np.clip(np.floor((dist_km % lap_len_km) / seg_width).astype(int), 0, n_segments - 1)

    # per-step increments
    dt = np.diff(tel["t_s"].to_numpy(), prepend=tel["t_s"].to_numpy()[0])
    dh2 = np.diff(tel["h2_cumulative_m3"].to_numpy(), prepend=0.0)
    wheel_wh = tel["p_wheel_w"].to_numpy() * dt / 3600.0
    elec_wh = tel["p_motor_elec_w"].to_numpy() * dt / 3600.0 if "p_motor_elec_w" in tel else np.zeros_like(dt)

    df = pd.DataFrame({"segment": seg_idx, "dh2_m3": dh2, "wheel_wh": wheel_wh,
                       "elec_wh": elec_wh, "v_kmh": tel["v_kmh"].to_numpy()})
    agg = df.groupby("segment").agg(
        h2_m3=("dh2_m3", "sum"),
        wheel_energy_wh=("wheel_wh", "sum"),
        elec_energy_wh=("elec_wh", "sum"),
        mean_speed_kmh=("v_kmh", "mean"),
    ).reset_index()
    agg["dist_start_km"] = agg["segment"] * seg_width
    agg["dist_end_km"] = (agg["segment"] + 1) * seg_width
    agg["h2_l"] = agg["h2_m3"] * 1000.0
    agg = agg[["segment", "dist_start_km", "dist_end_km", "mean_speed_kmh",
               "h2_l", "wheel_energy_wh", "elec_energy_wh"]]
    agg.to_csv(out_path, index=False)
    return agg


def tag_from_path(path: str) -> str:
    """Derive a per-algorithm tag from a telemetry filename, so every output is written
    to its OWN file and different algorithms never overwrite each other.
    e.g. data/simulated_telemetry_ga.csv -> 'ga'."""
    base = os.path.splitext(os.path.basename(path))[0]
    return base.replace("simulated_telemetry_", "") or "telemetry"


def generate_outputs(path: str, segments: int = 15, tag: str = None):
    """Write the 4 FP outputs for one telemetry file, each suffixed with the algorithm
    tag: fp_speed_heatmap_<tag>.png, fp_gasglide_heatmap_<tag>.png,
    fp_efficiency_report_<tag>.json, fp_energy_per_segment_<tag>.csv."""
    tag = tag or tag_from_path(path)
    tel = pd.read_csv(path)
    p1 = speed_heatmap(tel, f"data/fp_speed_heatmap_{tag}.png")
    p2 = gasglide_heatmap(tel, f"data/fp_gasglide_heatmap_{tag}.png")
    rep_path = f"data/fp_efficiency_report_{tag}.json"
    report = efficiency_report(tel, rep_path, path)
    seg = energy_per_segment(tel, f"data/fp_energy_per_segment_{tag}.csv", segments)
    print(f"[{tag}] {path}")
    print(f"  speed heatmap -> {p1}")
    print(f"  gas/glide     -> {p2}")
    print(f"  efficiency    -> {rep_path}  (score {report['art54e_score_km_per_m3']} km/m^3, "
          f"{report['time_min']} min, viol {report['rule_violations']})")
    print(f"  energy/seg    -> data/fp_energy_per_segment_{tag}.csv ({len(seg)} segments)")
    return tag, report


def main():
    ap = argparse.ArgumentParser(description="Generate FP minimal outputs from telemetry.")
    ap.add_argument("--telemetry", default=None, help="telemetry CSV (default: auto-detect)")
    ap.add_argument("--all", action="store_true", help="run for every telemetry CSV found in data/")
    ap.add_argument("--tag", default=None, help="override the per-algorithm output tag")
    ap.add_argument("--segments", type=int, default=15, help="segments per lap for energy aggregation")
    args = ap.parse_args()

    if args.all:
        paths = [p for p in CANDIDATES if os.path.exists(p)]
        if not paths:
            raise SystemExit("No telemetry CSVs found in data/.")
        print(f"Generating per-algorithm outputs for {len(paths)} telemetry files:")
        for p in paths:
            generate_outputs(p, args.segments)
    else:
        path = args.telemetry or autodetect_telemetry()
        generate_outputs(path, args.segments, tag=args.tag)


if __name__ == "__main__":
    main()

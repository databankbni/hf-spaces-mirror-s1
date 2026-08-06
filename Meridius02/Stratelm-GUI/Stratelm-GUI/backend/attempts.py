"""
Attempts registry -- every run the team wants to look back at later, whether
it came from the Sandbox's physics twin (source_type="simulated", tagged with
the algorithm used: cruise / ga / pso / cma) or from a real car over MQTT
(source_type="real", captured + cleaned in Live Telemetry). One JSON document
per attempt in data/attempts.json; each attempt's own telemetry/segment CSVs
live under data/attempts/<id>/ (except the three original GA/PSO/CMA-ES
benchmark runs, seeded in place from the existing top-level CSVs so nothing
gets duplicated).

has_gps matters because a real recording is very often car-electrical-only
(the GPS fix is a separate MQTT publisher, per mqtt/log.py's TOPICS list) --
the Strategy tab must say so plainly instead of drawing an empty/wrong map.
"""

import json
import os
import threading
import uuid
from datetime import datetime, timezone

DATA_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..', 'data'))
ATTEMPTS_JSON = os.path.join(DATA_DIR, "attempts.json")
ATTEMPTS_DIR = os.path.join(DATA_DIR, "attempts")

# This repo's own root (GUI state -- attempts.json, attempts/<id>/*.csv from
# real MQTT recordings or GUI-triggered optimizer jobs). digital_twin now
# lives in a separate repo (installed editable), and the three original
# seeded GA/PSO/CMA-ES/DP benchmark CSVs still live there too, so seed-*
# attempts need paths resolved against THAT repo's root instead -- see
# resolve_attempt_path()/_physics_root() below.
PROJECT_ROOT = os.path.dirname(DATA_DIR)

_lock = threading.Lock()


def _physics_root() -> str:
    import digital_twin
    return os.path.dirname(os.path.dirname(os.path.abspath(digital_twin.__file__)))


def _physics_data_dir() -> str:
    return os.path.join(_physics_root(), "data")


def resolve_attempt_path(attempt_id: str, rel_path: str) -> str:
    """seed-* attempts point at the precomputed benchmark CSVs that live in
    the digital_twin repo's own data/ dir; every other attempt (real MQTT
    recording or GUI-run optimizer job) was written under THIS repo's own
    data/attempts/<id>/, so its stored path is relative to THIS repo's root."""
    root = _physics_root() if attempt_id.startswith("seed-") else PROJECT_ROOT
    return os.path.join(root, rel_path)

SEED_ALGO_META = {
    "ga": {"label": "Genetic Algorithm", "segments": "ga_segment_targets.csv", "telemetry": "simulated_telemetry_ga.csv"},
    "pso": {"label": "Particle Swarm Optimization", "segments": "pso_segment_targets.csv", "telemetry": "simulated_telemetry_pso.csv"},
    "cma": {"label": "CMA-ES", "segments": "cma_segment_targets.csv", "telemetry": "simulated_telemetry_cma.csv"},
}


def _seed(config, telemetry_mod):
    import pandas as pd
    physics_data_dir = _physics_data_dir()
    out = {}
    for algo, meta in SEED_ALGO_META.items():
        seg_path = os.path.join(physics_data_dir, meta["segments"])
        tel_path = os.path.join(physics_data_dir, meta["telemetry"])
        if not (os.path.isfile(seg_path) and os.path.isfile(tel_path)):
            continue
        try:
            tel = pd.read_csv(tel_path)
            if tel.empty:
                continue
            total_dist_km = tel["s_m"].iloc[-1] / 1000.0
            total_h2_m3 = tel["h2_cumulative_m3"].iloc[-1]
            accessory_j = tel["accessory_energy_cumulative_j"].iloc[-1]
            score = telemetry_mod.h2_score_km_per_m3(total_dist_km, total_h2_m3, accessory_energy_j=accessory_j)
            total_time_s = tel["t_s"].iloc[-1]
            has_gps = "latitude" in tel.columns and "longitude" in tel.columns
        except Exception:
            continue
        aid = f"seed-{algo}"
        out[aid] = {
            "id": aid,
            "name": f"{meta['label']} benchmark (seed)",
            "created_at": "2026-07-16T00:00:00Z",
            "source_type": "simulated",
            "algorithm": algo,
            "vehicle_id": "urban-h2-2027",
            "track_id": "lusail-urban-2027",
            "has_gps": bool(has_gps),
            "telemetry_csv": f"data/{meta['telemetry']}",
            "segment_targets_csv": f"data/{meta['segments']}",
            "qc_report_json": None,
            "summary": {
                "score_km_per_m3": score,
                "h2_total_l": total_h2_m3 * 1000.0,
                "total_time_min": total_time_s / 60.0,
                "avg_speed_kmh": total_dist_km / (total_time_s / 3600.0) if total_time_s > 0 else 0.0,
                "max_speed_kmh": float(tel["v_kmh"].max()),
            },
            "notes": "Precomputed batch run from digital_twin/optimize_*.py (each takes 10s of minutes; not regenerated on request).",
        }

    out.update(_seed_dp())
    out.update(_seed_dp_single())
    return out


# DP: the physics-optimal backward-induction benchmark (Days 4-5) -- a
# different family from GA/PSO/CMA's per-segment gene search (continuous
# velocity-grid DP, not driver-executable per se, the reference number the
# others are measured against). Its telemetry schema is much sparser (no
# lat/lon, no per-row H2/motor_state -- resample_track() never carried
# them), so it can't reuse the loop above; unlike GA/PSO/CMA it's cheap
# enough (~12s) to just recompute fresh rather than trust a stale summary.
# Split out from _seed() so load_attempts() can backfill it alone into an
# attempts.json that was already generated (and cached) before DP existed,
# without re-running the whole seed batch.
def _seed_dp() -> dict:
    dp_tel_path = os.path.join(_physics_data_dir(), "simulated_telemetry_dp.csv")
    if not os.path.isfile(dp_tel_path):
        return {}
    return {"seed-dp": {
        "id": "seed-dp",
        "name": "DP benchmark (seed)",
        "created_at": "2026-07-16T00:00:00Z",
        "source_type": "simulated",
        "algorithm": "dp",
        "vehicle_id": "urban-h2-2027",
        "track_id": "lusail-urban-2027",
        "has_gps": False,
        "telemetry_csv": "data/simulated_telemetry_dp.csv",
        "segment_targets_csv": None,
        "qc_report_json": None,
        "summary": {
            "score_km_per_m3": 349.5,
            "h2_total_l": 35.65,
            "total_time_min": 34.96,
            "avg_speed_kmh": 24.89,
            "max_speed_kmh": None,
        },
        "notes": "Backward-induction physics-optimal reference (digital_twin/optimize_dp.py) -- the benchmark GA/PSO/CMA-ES are measured against, not a driver-executable strategy itself. No GPS/gas-glide data: its track grid never carried those columns.",
    }}


# Single-motor DP: run_dp_benchmark(use_two_motor=False) against the single
# reference motor (config.DEFAULT_MOTOR_NAME), i.e. no buffer-converter loss
# and no motor-switch-time penalty -- the physics ceiling the two-motor
# "seed-dp" rule-mode benchmark above is measured against. Same
# hand-maintained-summary pattern as _seed_dp() (telemetry has no per-row H2
# to recompute the score from live); update both dict and CSV together via
# `run_dp_benchmark(use_two_motor=False, telemetry_out_path=...)` if the
# underlying physics changes.
def _seed_dp_single() -> dict:
    dp_tel_path = os.path.join(_physics_data_dir(), "simulated_telemetry_dp_single_motor.csv")
    if not os.path.isfile(dp_tel_path):
        return {}
    return {"seed-dp-single": {
        "id": "seed-dp-single",
        "name": "DP benchmark - single motor (seed)",
        "created_at": "2026-07-25T00:00:00Z",
        "source_type": "simulated",
        "algorithm": "dp",
        "vehicle_id": "urban-h2-2027",
        "track_id": "lusail-urban-2027",
        "has_gps": False,
        "telemetry_csv": "data/simulated_telemetry_dp_single_motor.csv",
        "segment_targets_csv": None,
        "qc_report_json": None,
        "summary": {
            "score_km_per_m3": 331.4,
            "h2_total_l": 37.91,
            "total_time_min": 35.00,
            "avg_speed_kmh": 24.86,
            "max_speed_kmh": 30.6,
        },
        "notes": "Same backward-induction DP solve as the seed-dp two-motor benchmark, but run against a single reference motor (no buck-converter step-down loss, no motor-switch-time/traction penalty) -- the physics ceiling the two-motor rule-mode hardware is measured against, not the hardware actually on the car.",
    }}


def load_attempts(config=None, telemetry_mod=None) -> dict:
    with _lock:
        if os.path.isfile(ATTEMPTS_JSON):
            try:
                with open(ATTEMPTS_JSON, "r") as f:
                    existing = json.load(f)
            except (json.JSONDecodeError, OSError):
                existing = None
            if existing is not None:
                return existing
        seeded = _seed(config, telemetry_mod) if (config and telemetry_mod) else {}
        os.makedirs(DATA_DIR, exist_ok=True)
        with open(ATTEMPTS_JSON, "w") as f:
            json.dump(seeded, f, indent=2)
        return seeded


def save_attempts(data: dict):
    with _lock:
        os.makedirs(DATA_DIR, exist_ok=True)
        with open(ATTEMPTS_JSON, "w") as f:
            json.dump(data, f, indent=2)


def new_attempt_id() -> str:
    return uuid.uuid4().hex[:12]


def attempt_dir(attempt_id: str) -> str:
    d = os.path.join(ATTEMPTS_DIR, attempt_id)
    os.makedirs(d, exist_ok=True)
    return d


def register_attempt(*, name: str, source_type: str, algorithm, vehicle_id, track_id,
                      has_gps: bool, telemetry_csv_abs: str, segment_targets_csv_abs=None,
                      qc_report_abs=None, summary=None, notes: str = "", attempt_id: str = None) -> dict:
    """telemetry_csv_abs etc. are ABSOLUTE paths already written to disk by the
    caller -- stored back as project-root-relative paths (matches the
    vehicles/tracks convention elsewhere in the registry)."""
    project_root = os.path.abspath(os.path.join(DATA_DIR, '..'))

    def rel(p):
        return os.path.relpath(p, project_root).replace("\\", "/") if p else None

    attempts = load_attempts()
    aid = attempt_id or new_attempt_id()
    doc = {
        "id": aid,
        "name": name,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "source_type": source_type,
        "algorithm": algorithm,
        "vehicle_id": vehicle_id,
        "track_id": track_id,
        "has_gps": bool(has_gps),
        "telemetry_csv": rel(telemetry_csv_abs),
        "segment_targets_csv": rel(segment_targets_csv_abs),
        "qc_report_json": rel(qc_report_abs),
        "summary": summary,
        "notes": notes,
    }
    attempts[aid] = doc
    save_attempts(attempts)
    return doc


def load_chart_data(doc: dict, max_points: int = 800, lap: int = None, use_raw: bool = False) -> dict:
    """Normalizes a saved/seeded attempt's telemetry CSV into one shape the
    Strategy tab can chart regardless of source."""
    import pandas as pd
    aid = doc["id"]
    d = attempt_dir(aid)
    raw_p = os.path.join(d, "telemetry_raw.csv")
    has_raw = os.path.isfile(raw_p)

    csv_path = doc.get("telemetry_csv")
    if use_raw and has_raw:
        csv_path = os.path.relpath(raw_p, PROJECT_ROOT).replace("\\", "/")

    if not csv_path:
        return {"points": [], "has_gps": False, "has_raw": has_raw, "error": "no telemetry file recorded for this attempt"}
    full_path = resolve_attempt_path(doc["id"], csv_path)
    if not os.path.isfile(full_path):
        return {"points": [], "has_gps": False, "has_raw": has_raw, "error": f"telemetry file missing: {csv_path}"}

    df = pd.read_csv(full_path)
    if df.empty:
        return {"points": [], "has_gps": False, "has_raw": has_raw, "error": "telemetry file is empty"}

    lap_col = "lap" if "lap" in df.columns else ("lap_number" if "lap_number" in df.columns else None)
    available_laps = sorted(int(x) for x in df[lap_col].dropna().unique()) if lap_col else []
    if lap is not None and lap_col:
        df = df[df[lap_col] == lap].reset_index(drop=True)
        if df.empty:
            return {"points": [], "has_gps": False, "has_raw": has_raw, "available_laps": available_laps, "error": f"no data for lap {lap}"}

    step = max(1, len(df) // max_points)
    df = df.iloc[::step].reset_index(drop=True)

    # Gas/glide state: "gas" (motor actively driving) vs "glide" (coasting,
    # engine off) vs "brake" -- a simulated attempt has the digital twin's own
    # motor_state column (derived from the sign/magnitude of traction force
    # in simulate.py, valid for both the crude cruise strategy and the GA/PSO/
    # CMA-ES gas-glide strategy). A real recording has no such label, so it's
    # derived from a power threshold instead -- clearly a heuristic, not a
    # measured state, which the frontend must label as such.
    REAL_GAS_POWER_THRESHOLD_W = 15.0
    state = None
    state_is_derived = False

    if doc.get("source_type") == "simulated":
        distance = df["s_m"] / 1000.0 if "s_m" in df.columns else None
        speed = df["v_kmh"] if "v_kmh" in df.columns else None
        lat = df["latitude"] if "latitude" in df.columns else None
        lon = df["longitude"] if "longitude" in df.columns else None
        h2 = df["h2_flow_m3_s"] * 1000.0 * 60.0 if "h2_flow_m3_s" in df.columns else None
        power = df["p_motor_elec_w"] if "p_motor_elec_w" in df.columns else None
        if "motor_state" in df.columns:
            state = df["motor_state"].map({"accel": "gas", "cruise": "glide", "brake": "brake"}).fillna("glide")
    else:
        import mqtt.clean_telemetry as clean_telemetry
        colmap = {}
        for col in df.columns:
            _, canon = clean_telemetry.resolve_rule(col)
            if canon and canon not in colmap:
                colmap[canon] = col
        distance = (df[colmap["distance"]] / 1000.0) if "distance" in colmap else None
        speed = df[colmap["velocity"]] if "velocity" in colmap else None
        lat = df[colmap["latitude"]] if "latitude" in colmap else None
        lon = df[colmap["longitude"]] if "longitude" in colmap else None
        h2 = None
        power = df[colmap["powerW"]] if "powerW" in colmap else None
        if power is not None:
            state = power.apply(lambda p: "gas" if pd.notna(p) and p > REAL_GAS_POWER_THRESHOLD_W else "glide")
            state_is_derived = True

    has_gps = lat is not None and lon is not None and bool(lat.notna().any()) and bool(lon.notna().any())

    def val(series, i):
        if series is None:
            return None
        v = series.iloc[i]
        return float(v) if pd.notna(v) else None

    def state_val(i):
        if state is None:
            return None
        v = state.iloc[i]
        return str(v) if pd.notna(v) else None

    points = [
        {
            "index": i,
            "distance_km": val(distance, i),
            "speed_kmh": val(speed, i),
            "latitude": val(lat, i) if has_gps else None,
            "longitude": val(lon, i) if has_gps else None,
            "h2_flow_lpm": val(h2, i),
            "power_w": val(power, i),
            "state": state_val(i),
        }
        for i in range(len(df))
    ]
    return {
        "points": points,
        "has_gps": has_gps,
        "state_available": state is not None,
        "state_is_derived": state_is_derived,
        "available_laps": available_laps,
    }


def delete_attempt(attempt_id: str) -> bool:
    attempts = load_attempts()
    if attempt_id not in attempts:
        return False
    doc = attempts.pop(attempt_id)
    save_attempts(attempts)
    if not attempt_id.startswith("seed-"):
        d = os.path.join(ATTEMPTS_DIR, attempt_id)
        if os.path.isdir(d):
            import shutil
            shutil.rmtree(d, ignore_errors=True)
    return True


def get_qc_report(doc: dict) -> dict:
    aid = doc["id"]
    d = attempt_dir(aid)
    report_p = os.path.join(d, "qc_report.json")
    if os.path.isfile(report_p):
        try:
            with open(report_p, "r") as f:
                return {"available": True, "report": json.load(f)}
        except Exception as e:
            return {"available": False, "error": str(e)}
    return {"available": False, "message": "No QC report found. Run Clean & Assign Laps to generate quality control analysis."}

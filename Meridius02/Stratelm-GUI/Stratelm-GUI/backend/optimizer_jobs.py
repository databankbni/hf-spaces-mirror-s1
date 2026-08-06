"""
Background jobs for the real GA/PSO/CMA-ES strategy optimizers (Sandbox's
"just physics, flat cruise strategy" was the user's complaint -- this is what
lets the Sandbox actually run digital_twin/optimize_{ga,pso,cma}.py instead
of only ever showing the seeded benchmark runs).

Why a job queue and not a thread-per-algorithm: digital_twin/config.py is
process-global mutable state that vehicle.py/simulate.py now read LIVE on
every single simulation step (see the earlier vehicle.py fix). Two optimizer
runs for two different vehicles executing truly concurrently would stomp on
each other's config.* values mid-simulation and silently corrupt both
results. "Run multiple algorithms at once" is honored by accepting several
algorithms in one request and running them one after another under a single
worker/lock -- the UI can show GA/PSO/CMA all queued together and watch them
complete in turn, which is what the user actually wants to compare, without
the physics engine racing itself.

Each GA/PSO/CMA-ES run takes 10s of minutes (~7s per simulate() call x
pop_size x n_gen -- measured directly against this track). Progress is an
elapsed-time estimate, not a true per-generation callback (safer than
coupling to pymoo internals).
"""

import os
import queue
import sys
import threading
import time
import uuid
from typing import Optional

PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..'))
if PROJECT_ROOT not in sys.path:
    sys.path.append(PROJECT_ROOT)

import attempts as attempts_mod
import registry

SECONDS_PER_EVAL = 7.5  # measured: one simulate() call over the full 4-lap Lusail track

JOBS: dict = {}
_JOBS_LOCK = threading.Lock()
_QUEUE: "queue.Queue" = queue.Queue()
_WORKER_STARTED = False


ALGO_LABELS = {
    "ga": "Genetic Algorithm",
    "pso": "Particle Swarm Optimization",
    "cma": "CMA-ES",
    "dp": "DP (Physics-Optimal)",
    "mpc": "Model Predictive Control",
    "fuzzy": "Fuzzy Logic TSK",
}
DP_SECONDS = 15.0  # measured: full backward-induction pass, ~12s + margin

BEST_DEFAULTS = {"ga": (50, 40), "pso": (20, 30), "cma": (20, 30), "mpc": (20, 30), "fuzzy": (20, 30)}


def _algo_module(algo):
    if algo == "ga":
        import digital_twin.optimize_ga as m
    elif algo == "pso":
        import digital_twin.optimize_pso as m
    elif algo == "cma":
        import digital_twin.optimize_cma as m
    elif algo == "dp":
        import digital_twin.optimize_dp as m
    elif algo == "mpc":
        import digital_twin.mpc as m
    elif algo == "fuzzy":
        import digital_twin.fuzzy_strategy as m
    else:
        raise ValueError(f"unknown algorithm '{algo}'")
    return m


def estimate_seconds(algo: str, pop_size: int, n_gen: int) -> float:
    if algo == "dp":
        return DP_SECONDS
    return max(pop_size * n_gen * SECONDS_PER_EVAL, 5.0)


def _ensure_worker():
    global _WORKER_STARTED
    with _JOBS_LOCK:
        if _WORKER_STARTED:
            return
        _WORKER_STARTED = True
    t = threading.Thread(target=_worker_loop, daemon=True)
    t.start()


def _worker_loop():
    while True:
        item = _QUEUE.get()
        job_id = item[0]
        try:
            _run_job(item)
        except Exception as e:
            with _JOBS_LOCK:
                JOBS[job_id]["status"] = "error"
                JOBS[job_id]["error"] = str(e)
        _QUEUE.task_done()


def submit(*, algo: str, vehicle: dict, track: dict, scenario_name: str,
           motor_name: str, fc_name: str, pop_size: Optional[int] = None, n_gen: Optional[int] = None,
           group_id: str = None) -> str:
    """pop_size/n_gen=None means "use the best/tuned configuration" -- resolved
    here to BEST_DEFAULTS (or left None for dp, which has no such concept)
    rather than passed through as None, so job metadata/ETA/results always
    show the concrete numbers actually used."""
    if pop_size is None or n_gen is None:
        pop_size, n_gen = BEST_DEFAULTS.get(algo, (pop_size, n_gen))
    _ensure_worker()
    job_id = uuid.uuid4().hex[:10]
    job = {
        "id": job_id,
        "group_id": group_id,
        "algo": algo,
        "label": ALGO_LABELS[algo],
        "status": "queued",
        "progress": 0.0,
        "eta_s": estimate_seconds(algo, pop_size, n_gen),
        "started_at": None,
        "queued_at": time.time(),
        "vehicle_id": vehicle["id"],
        "vehicle_name": vehicle["name"],
        "track_id": track["id"],
        "track_name": track["name"],
        "scenario_name": scenario_name,
        "motor_name": motor_name,
        "fc_name": fc_name,
        "pop_size": pop_size,
        "n_gen": n_gen,
        "result": None,
        "error": None,
        "saved_attempt_id": None,
    }
    with _JOBS_LOCK:
        JOBS[job_id] = job
    _QUEUE.put((job_id, algo, vehicle, track, scenario_name, motor_name, fc_name, pop_size, n_gen))
    return job_id


def _run_job(item):
    job_id, algo, vehicle, track, scenario_name, motor_name, fc_name, pop_size, n_gen = item
    job = JOBS[job_id]
    job["status"] = "running"
    job["started_at"] = time.time()

    stop_ticker = threading.Event()

    def _tick():
        while not stop_ticker.is_set():
            elapsed = time.time() - job["started_at"]
            job["progress"] = min(95.0, 100.0 * elapsed / job["eta_s"])
            stop_ticker.wait(2.0)

    ticker = threading.Thread(target=_tick, daemon=True)
    ticker.start()

    import digital_twin.config as config
    import digital_twin.track as track_mod
    import digital_twin.simulate as sim_mod
    import digital_twin.telemetry as telemetry_mod
    import digital_twin.weather as weather_mod

    orig_vehicle_cfg = registry.apply_vehicle(config, vehicle)
    orig_track_cfg = registry.apply_track(config, track)
    try:
        # The optimizers search over the QP-solved shortest-path racing line
        # (digital_twin/track.py's build_racing_line_profile), not the raw
        # Shell GPS backbone -- that's the actual optimization target now that
        # Final_Project's optimize_{ga,pso,cma,dp} all consume it (2026-07-20,
        # "configure the optimal line integration"). GA and DP respect the
        # full_track/lap_distance_km we pass in here; PSO and CMA-ES currently
        # rebuild their own full_track internally from module-default CSV
        # paths regardless of what's passed (a Final_Project-side
        # inconsistency, not fixed here) -- so today they only match this
        # profile when the selected track IS the default Lusail track.
        profile_1lap = track_mod.build_racing_line_profile(
            save=False, racing_line_csv=track.get("racing_line_csv"),
            coordinates_csv=track.get("coordinates_csv"), stop_locations_km=track.get("stop_locations_km"))
        lap_distance_km = profile_1lap["distance_km"].iloc[-1]
        full_track = sim_mod.build_full_attempt_track(profile_1lap, laps=track.get("total_laps", config.TOTAL_LAPS))

        d = attempts_mod.attempt_dir(job_id)
        tel_path = os.path.join(d, "telemetry.csv")
        mod = _algo_module(algo)

        if algo == "dp":
            # Different family (continuous velocity-grid backward induction,
            # not a per-segment gene search): no pop_size/n_gen, no segment
            # targets, and its telemetry schema never carried lat/lon or
            # per-row H2/motor_state (see attempts.py's seed-dp comment).
            dp_result = mod.run_dp_benchmark(
                scenario_name=scenario_name, motor_name=motor_name, fc_name=fc_name,
                full_track=full_track, telemetry_out_path=tel_path,
            )
            stop_ticker.set()
            summary = {
                "score_km_per_m3": dp_result["score_km_per_m3"],
                "h2_total_l": dp_result["h2_m3"] * 1000.0,
                "accessory_h2_equiv_l": telemetry_mod.accessory_h2_equivalent_m3(dp_result["accessory_energy_j"]) * 1000.0,
                "total_time_min": dp_result["time_total_min"],
                "avg_speed_kmh": dp_result["distance_km"] / (dp_result["time_total_min"] / 60.0),
                "max_speed_kmh": None,
            }
            job["progress"] = 100.0
            job["status"] = "done"
            job["result"] = {
                "summary": summary,
                "telemetry_csv": os.path.relpath(tel_path, PROJECT_ROOT).replace("\\", "/"),
                "segment_targets_csv": None,
                "has_gps": False,
            }
            return

        seg_path = os.path.join(d, "segments.csv")
        best_telemetry, best_x, score = mod.optimize_strategy(
            scenario_name=scenario_name, motor_name=motor_name, fc_name=fc_name,
            pop_size=pop_size, n_gen=n_gen,
            full_track=full_track, lap_distance_km=lap_distance_km,
            segment_out_path=seg_path, telemetry_out_path=tel_path,
        )
        stop_ticker.set()

        if best_telemetry is None:
            job["status"] = "error"
            job["error"] = "No feasible solution found (time constraint too strict for these parameters)"
            return

        total_dist_km = best_telemetry["s_m"].iloc[-1] / 1000.0
        total_h2_m3 = best_telemetry["h2_cumulative_m3"].iloc[-1]
        accessory_j = best_telemetry["accessory_energy_cumulative_j"].iloc[-1]
        total_time_s = best_telemetry["t_s"].iloc[-1]
        summary = {
            "score_km_per_m3": score,
            "h2_total_l": total_h2_m3 * 1000.0,
            "accessory_h2_equiv_l": telemetry_mod.accessory_h2_equivalent_m3(accessory_j) * 1000.0,
            "total_time_min": total_time_s / 60.0,
            "avg_speed_kmh": total_dist_km / (total_time_s / 3600.0) if total_time_s > 0 else 0.0,
            "max_speed_kmh": float(best_telemetry["v_kmh"].max()),
        }
        job["progress"] = 100.0
        job["status"] = "done"
        job["result"] = {
            "summary": summary,
            "telemetry_csv": os.path.relpath(tel_path, PROJECT_ROOT).replace("\\", "/"),
            "segment_targets_csv": os.path.relpath(seg_path, PROJECT_ROOT).replace("\\", "/"),
            "has_gps": "latitude" in best_telemetry.columns,
        }
    finally:
        stop_ticker.set()
        registry.restore_config(config, orig_vehicle_cfg)
        registry.restore_config(config, orig_track_cfg)


def get_job(job_id: str):
    return JOBS.get(job_id)


def save_job_as_attempt(job_id: str, name: str, notes: str = ""):
    job = JOBS.get(job_id)
    if not job:
        return None, "job not found"
    if job["status"] != "done":
        return None, f"job is not done yet (status={job['status']})"
    if job.get("saved_attempt_id"):
        return attempts_mod.load_attempts().get(job["saved_attempt_id"]), None

    result = job["result"]
    doc = attempts_mod.register_attempt(
        attempt_id=job_id,
        name=name,
        source_type="simulated",
        algorithm=job["algo"],
        vehicle_id=job["vehicle_id"],
        track_id=job["track_id"],
        has_gps=result["has_gps"],
        telemetry_csv_abs=os.path.join(PROJECT_ROOT, result["telemetry_csv"]),
        segment_targets_csv_abs=os.path.join(PROJECT_ROOT, result["segment_targets_csv"]) if result["segment_targets_csv"] else None,
        summary=result["summary"],
        notes=notes,
    )
    job["saved_attempt_id"] = job_id
    return doc, None


def discard_job(job_id: str):
    job = JOBS.get(job_id)
    if not job:
        return False
    if not job.get("saved_attempt_id"):
        d = os.path.join(attempts_mod.ATTEMPTS_DIR, job_id)
        if os.path.isdir(d):
            import shutil
            shutil.rmtree(d, ignore_errors=True)
    with _JOBS_LOCK:
        JOBS.pop(job_id, None)
    return True
